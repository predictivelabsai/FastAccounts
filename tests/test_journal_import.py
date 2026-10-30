"""Synthetic offline journal workbook, reviewed posting and API regressions."""
import base64
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from connectors.file_import import parse_journal_workbook
from core_utils import new_id
from import_service import ImportService
from integration_service import AccountMappingService

ACTOR = "owner@example.test"
HEADERS = ["Konto", "Operatsiooni kirjeldus", "Deebet", "Kreedit", "Kuupäev", "Ignored"]


def workbook(blocks=None, *, sheets=1):
    book = Workbook()
    for index in range(sheets):
        sheet = book.active if index == 0 else book.create_sheet()
        sheet.title = f"Synthetic {index + 1}"
        for title, lines in blocks or [("SYNTHETIC JOURNAL 2026", [
            [9911, "Synthetic expense", "12,34", None],
            [9922, "Synthetic payable", None, Decimal("12.34")],
            [9911, "Zero retained in review", 0, None],
        ])]:
            sheet.append([None, title, None])
            sheet.append(HEADERS)
            for line in lines:
                sheet.append(line)
            sheet.append([])
    content = io.BytesIO()
    book.save(content)
    book.close()
    return content.getvalue()


@pytest.fixture
def journal(db, ee_org):
    # Fictional accounts deliberately outside the seeded chart.
    with db.transaction() as tx:
        for code in ("9911", "9922"):
            account = db.one("SELECT * FROM accounts WHERE organisation_id=? LIMIT 1", (ee_org["id"],))
            columns = list(account)
            account.update(id=new_id(), code=code, name=f"Synthetic {code}", system_role=None)
            tx.execute(f"INSERT INTO accounts({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                       tuple(account[column] for column in columns))
    return ImportService(db), ee_org["id"]


def stage(journal, content=None):
    service, oid = journal
    sync = service.run_sync(oid, "file_import", "journal", actor=ACTOR,
                            credentials={"workbook_content": content or workbook()})
    return sync, service.get_staged(oid, sync_run_id=sync["id"])["records"]


def apply(journal, sync, records, **kwargs):
    service, oid = journal
    return service.apply_staged(oid, "file_import", sync["id"],
                                {row["id"]: "apply" for row in records}, actor=ACTOR, **kwargs)


def test_all_titled_blocks_all_sheets_and_deterministic_reparse():
    content = workbook([
        ("GENERIC COST 2026", [[9911, "Expense", 1, None], [9922, "Accrual", None, 1]]),
        ("ANY RECLASSIFICATION", [[9922, "Debit", 2, 0], [9911, "Credit", 0, 2]]),
    ], sheets=2)
    first = parse_journal_workbook(content)
    assert first == parse_journal_workbook(content)
    assert len(first) == 4 and len({block["external_id"] for block in first}) == 4
    assert [block["name"] for block in first[:2]] == ["GENERIC COST 2026", "ANY RECLASSIFICATION"]
    assert first[0]["lines"][0]["debit"] == Decimal("1.00")
    assert first[0]["lines"][0]["credit"] is None


def test_stage_review_date_apply_audit_and_repeat_idempotency(journal, db):
    service, oid = journal
    sync, records = stage(journal)
    review = records[0]["journal_review"]
    assert review["valid"] and review["balanced"]
    assert Decimal(review["debit_total"]) == Decimal(review["credit_total"]) == Decimal("12.34")
    assert len(review["lines"]) == 3
    assert apply(journal, sync, records)["failed"] == 1
    result = apply(journal, sync, records, posting_date="2026-10-31")
    assert result["applied"] == 1
    batch = db.one("SELECT * FROM posting_batches WHERE organisation_id=?", (oid,))
    assert batch["posting_date"] == "2026-10-31" and batch["status"] == "Posted"
    entries = db.rows("SELECT * FROM gl_entries WHERE organisation_id=?", (oid,))
    assert len(entries) == 2
    assert sum(Decimal(str(row["debit"])) for row in entries) == sum(Decimal(str(row["credit"])) for row in entries)
    assert apply(journal, sync, records)["unchanged"] == 1
    again, rows = stage(journal)
    assert apply(journal, again, rows, posting_date="2026-11-01")["unchanged"] == 1
    assert db.scalar("SELECT COUNT(*) FROM posting_batches WHERE organisation_id=?", (oid,)) == 1
    audits = db.rows("SELECT action,details_json FROM audit_events WHERE organisation_id=?", (oid,))
    assert {"integration.records_staged", "integration.staged_applied", "ledger.posted"} <= {a["action"] for a in audits}
    assert "Synthetic expense" not in json.dumps(audits)


def test_unbalanced_block_has_warning_and_never_posts(journal, db):
    sync, rows = stage(journal, workbook([("BAD", [[9911, "D", 10, None], [9922, "C", None, 9]])]))
    assert rows[0]["review_note"] == "Journal block is unbalanced"
    assert not rows[0]["journal_review"]["balanced"]
    assert apply(journal, sync, rows, posting_date="2026-10-31")["failed"] == 1
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 0


def test_mapping_is_confirmed_tenant_scoped_and_can_be_fixed_before_apply(journal, db, uk_org):
    service, oid = journal
    content = workbook([("MAPPING", [["EXT-SYN", "D", 10, None], [9922, "C", None, 10]])])
    sync, rows = stage(journal, content)
    assert rows[0]["journal_review"]["lines"][0]["warning"] == "Journal account is unmapped"
    assert apply(journal, sync, rows, posting_date="2026-10-31")["failed"] == 1
    mappings = AccountMappingService(db)
    other_code = db.scalar("SELECT code FROM accounts WHERE organisation_id=? LIMIT 1", (uk_org["id"],))
    mappings.create(uk_org["id"], "file_import", local_account_code=other_code,
                    external_account_code="EXT-SYN", status="Confirmed", actor=ACTOR)
    assert not service.get_staged(oid, sync_run_id=sync["id"])["records"][0]["journal_review"]["valid"]
    mappings.create(oid, "file_import", local_account_code="9911", external_account_code="EXT-SYN", actor=ACTOR)
    assert apply(journal, sync, rows, posting_date="2026-10-31")["failed"] == 1
    mappings.create(oid, "file_import", local_account_code="9911", external_account_code="EXT-SYN", status="Confirmed", actor=ACTOR)
    assert service.get_staged(oid, sync_run_id=sync["id"])["records"][0]["journal_review"]["valid"]
    assert apply(journal, sync, rows, posting_date="2026-10-31")["applied"] == 1
    with pytest.raises(KeyError):
        service.get_staged(uk_org["id"], sync_run_id=sync["id"])
    with pytest.raises(KeyError):
        service.apply_staged(uk_org["id"], "file_import", sync["id"], {rows[0]["id"]: "apply"}, actor=ACTOR)


@pytest.mark.parametrize("change", ["balance", "inactive", "lock"])
def test_apply_revalidates_balance_accounts_and_period(journal, db, change):
    service, oid = journal
    sync, rows = stage(journal)
    with db.transaction() as tx:
        if change == "balance":
            payload = rows[0]["external_payload"]
            payload["lines"][0]["debit"] = "99"
            tx.execute("UPDATE import_staged_records SET external_payload_json=? WHERE id=?", (json.dumps(payload), rows[0]["id"]))
        elif change == "inactive":
            tx.execute("UPDATE accounts SET active=0 WHERE organisation_id=? AND code='9911'", (oid,))
        else:
            tx.execute("UPDATE fiscal_periods SET status='Locked' WHERE organisation_id=?", (oid,))
    assert apply(journal, sync, rows, posting_date="2026-10-31")["failed"] == 1
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 0


@pytest.mark.parametrize("amount", ["=1+1", "NaN", "Infinity", -1, "bad", "2.001"])
def test_invalid_amounts_and_formulas_remain_invalid_proposals(journal, amount):
    sync, rows = stage(journal, workbook([("BAD", [[9911, "D", amount, None], [9922, "C", None, 2]])]))
    assert rows[0]["journal_review"]["warning"]
    assert apply(journal, sync, rows, posting_date="2026-10-31")["failed"] == 1


def test_optional_dates_loose_headers_and_unknown_columns(journal):
    global HEADERS
    original = HEADERS
    try:
        HEADERS = [" Account code ", "Kirjeldus", "DEEBET", "credit", "Posting date", "Unknown"]
        sync, rows = stage(journal, workbook([("DATES", [[9911, "D", 2, None, date(2026, 10, 31), "ignored"],
                                                        [9922, "C", None, 2, "31.10.2026"]])]))
    finally:
        HEADERS = original
    assert rows[0]["external_payload"]["date"] == "2026-10-31"
    assert apply(journal, sync, rows)["applied"] == 1


def test_different_dates_and_zero_only_blocks_cannot_apply(journal):
    sync, rows = stage(journal, workbook([
        ("DATES", [[9911, "D", 1, None, "2026-10-30"], [9922, "C", None, 1, "2026-10-31"]]),
        ("ZERO", [[9911, "Zero", 0, None], [9922, "Zero", None, 0]]),
    ]))
    assert {row["review_note"] for row in rows} == {"Journal block contains different posting dates", "Journal block must contain a positive balanced posting"}
    assert apply(journal, sync, rows, posting_date="2026-10-31")["failed"] == 2


def test_concurrent_reimports_create_one_posting(journal, db):
    staged = [stage(journal) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: apply(journal, *pair, posting_date="2026-10-31"), staged))
    assert sum(result["applied"] for result in results) == 1
    assert sum(result["unchanged"] for result in results) == 1
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 1


def test_post_mapping_and_staged_status_roll_back_together(journal, db, monkeypatch):
    service, oid = journal
    sync, rows = stage(journal)

    def fail_mapping(*args, **kwargs):
        raise RuntimeError("Synthetic mapping failure")

    monkeypatch.setattr(service, '_upsert_external_mapping', fail_mapping)
    with pytest.raises(RuntimeError, match="Synthetic mapping failure"):
        apply(journal, sync, rows, posting_date="2026-10-31")
    assert db.scalar('SELECT COUNT(*) FROM posting_batches') == 0
    assert db.scalar('SELECT COUNT(*) FROM gl_entries') == 0
    assert db.scalar('SELECT COUNT(*) FROM external_mappings') == 0
    assert service.get_staged(oid, sync_run_id=sync['id'])['records'][0]['status'] == 'Pending'


def test_rejected_proposal_never_posts(journal, db):
    service, oid = journal
    sync, rows = stage(journal)
    service.apply_staged(oid, 'file_import', sync['id'], {rows[0]['id']: 'reject'}, actor=ACTOR)
    assert apply(journal, sync, rows, posting_date='2026-10-31')['failed'] == 1
    assert apply(journal, sync, rows, posting_date='2026-10-31')['failed'] == 1
    assert service.get_staged(oid, sync_run_id=sync['id'])['records'][0]['status'] == 'Rejected'
    assert db.scalar('SELECT COUNT(*) FROM posting_batches') == 0


@pytest.mark.parametrize("content", [b"", b"not excel", b"x" * 2_000_001], ids=["empty", "invalid", "oversize"])
def test_invalid_workbook_is_rejected(content):
    with pytest.raises(ValueError):
        parse_journal_workbook(content)


def test_api_role_tenant_and_csrf_matrix(journal, db, uk_org, monkeypatch):
    from api_app import api, current_user, User
    from database import reset_database_cache
    from organisations import OrganisationService
    from web_app import app

    service, oid = journal
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    reset_database_cache()
    organisations = OrganisationService(db)
    for role in ("administrator", "accountant", "approver", "viewer"):
        organisations.add_member(oid, ACTOR, f"{role}@example.test", role)
    base = f"/organisations/{oid}/integrations/file_import"
    body = {"object_type": "journal", "xlsx_base64": base64.b64encode(workbook()).decode()}
    try:
        with TestClient(api, headers={"X-Test-User": ACTOR}) as client:
            for role in ("owner", "administrator", "accountant", "approver", "viewer", "outsider"):
                headers = {"X-Test-User": f"{role}@example.test"}
                allowed = role in {"owner", "administrator"}
                response = client.post(base + "/import", json=body, headers=headers)
                assert response.status_code == (200 if allowed else 403)
                sync = response.json() if allowed else client.post(base + "/import", json=body).json()
                url = base + f"/sync/{sync['id']}"
                assert client.get(url, headers=headers).status_code == (200 if allowed else 403)
                records = client.get(url).json()["records"]
                applied = client.post(url + "/apply", headers=headers,
                                      json={"decisions": {records[0]["id"]: "apply"}, "posting_date": "2026-10-31"})
                assert applied.status_code == (200 if allowed else 403)
            assert client.get(f"/organisations/{uk_org['id']}/integrations/file_import/sync/{sync['id']}").status_code == 404
            assert client.post(base + "/import", json={"object_type": "journal", "xlsx_base64": "!bad"}).status_code == 422
        api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
        with TestClient(app) as client:
            assert client.post('/api' + base + '/import', json=body).status_code == 403
            token = client.get('/api/csrf').json()['csrf_token']
            headers = {'X-CSRF-Token': token}
            sync = client.post('/api' + base + '/import', json=body, headers=headers).json()
            url = '/api' + base + f"/sync/{sync['id']}"
            record = client.get(url).json()['records'][0]
            decisions = {'decisions': {record['id']: 'apply'}, 'posting_date': '2026-10-31'}
            assert client.post(url + '/apply', json=decisions).status_code == 403
            assert client.post(url + '/apply', json=decisions, headers=headers).status_code == 200
    finally:
        api.dependency_overrides.clear()
        reset_database_cache()


def test_browser_upload_review_mapping_and_apply(journal, db, monkeypatch):
    """Drive the real SPA and API offline, including the attached XLSX bytes."""
    from pathlib import Path
    from urllib.parse import urlsplit
    from api_app import api
    from database import reset_database_cache
    from web_app import app

    playwright = pytest.importorskip("playwright.sync_api")
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    monkeypatch.setenv("FASTACCOUNTS_DEFAULT_LANG", "en")
    reset_database_cache()
    html = TestClient(app).get('/auth/test').text
    root = Path(__file__).resolve().parents[1]
    content = workbook([
        ("BROWSER VALID", [["EXT-BROWSER", "D", 5, None], [9922, "C", None, 5]]),
        ("BROWSER UNBALANCED", [[9911, "D", 2, None], [9922, "C", None, 1]]),
    ])
    try:
        with TestClient(api, headers={"X-Test-User": ACTOR}) as client, playwright.sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))

            def respond(route):
                path = urlsplit(route.request.url).path
                if path == '/app':
                    return route.fulfill(body=html, content_type='text/html')
                if path.startswith('/static/'):
                    return route.fulfill(path=str(root / path.lstrip('/')))
                if path == '/api/csrf':
                    return route.fulfill(json={'csrf_token': 'synthetic'})
                if path.startswith('/api/'):
                    response = client.request(route.request.method, path[4:], content=route.request.post_data,
                                              headers={'Content-Type': 'application/json'})
                    return route.fulfill(status=response.status_code, body=response.content,
                                         content_type=response.headers.get('content-type', 'application/json'))
                return route.fulfill(status=404)

            page.route('**/*', respond)
            page.goto('http://workspace.test/app#imports')
            page.get_by_role('button', name='Import journal workbook', exact=True).click()
            page.locator('[name=journal_file]').set_input_files({'name': 'synthetic.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'buffer': content})
            page.get_by_role('button', name='Stage import', exact=True).click()
            playwright.expect(page.get_by_text('BROWSER VALID', exact=True)).to_be_visible()
            bad = page.locator('tr').filter(has=page.get_by_text('BROWSER UNBALANCED', exact=True))
            playwright.expect(bad.locator('[data-decision=apply]')).to_be_disabled()
            page.get_by_role('button', name='Map journal account', exact=True).click()
            page.locator('[name=local_account_code]').select_option('9911')
            page.get_by_role('button', name='Confirm mapping', exact=True).click()
            good = page.locator('tr').filter(has=page.get_by_text('BROWSER VALID', exact=True))
            playwright.expect(good.locator('[data-decision=apply]')).to_be_enabled()
            page.locator('[name=journal_posting_date]').fill('2026-10-31')
            good.locator('[data-decision=apply]').check()
            bad.locator('[data-decision=reject]').check()
            page.get_by_role('button', name='Apply decisions', exact=True).click()
            playwright.expect(good.get_by_text('Applied', exact=True)).to_be_visible()
            playwright.expect(bad.get_by_text('Rejected', exact=True)).to_be_visible()
            assert db.scalar('SELECT COUNT(*) FROM posting_batches') == 1
            assert not errors
            browser.close()
    finally:
        reset_database_cache()
