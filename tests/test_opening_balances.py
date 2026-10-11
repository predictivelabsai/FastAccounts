from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core_utils import new_id
from database import reset_database_cache
from documents import DocumentService
from ledger import LedgerService, PostingLine
from opening_balances import OpeningBalanceService, parse_open_items_csv


ACTOR = "owner@example.test"
POSTING_DATE = "2024-02-29"
CSV = ("type,name,original_number,original_date,due_date,amount\n"
       "customer,Synthetic customer,OLD-SALE,2024-01-10,2024-03-10,120.25\n"
       "supplier,Synthetic supplier,OLD-BILL,2024-01-11,2024-03-11,80.10\n")


def accounts(db, org):
    return {a["system_role"]: a["id"] for a in db.rows(
        "SELECT * FROM accounts WHERE organisation_id=?", (org["id"],))}


def entries(db, batch):
    return db.rows("SELECT * FROM gl_entries WHERE posting_batch_id=? ORDER BY line_number", (batch["id"],))


def closes(db, org):
    report = LedgerService(db).balance_sheet(org["id"], as_at=POSTING_DATE)
    assert report["assets"] == report["liabilities_and_equity"]
    assert report["current_earnings"] == Decimal("0.00")


def test_ensure_period_idempotent_and_preserves_existing(db, uk_org):
    service = OpeningBalanceService(db)
    before = db.rows("SELECT * FROM fiscal_periods ORDER BY starts_on")
    with db.transaction() as tx:
        with pytest.raises(ValueError, match="outside configured"):
            LedgerService(db)._validate_period(tx, uk_org["id"], POSTING_DATE)
    for _ in range(2):
        service.ensure_period(uk_org["id"], POSTING_DATE)
    period = db.one("SELECT * FROM fiscal_periods WHERE organisation_id=? AND code='2024-02'", (uk_org["id"],))
    assert period["starts_on"] == "2024-02-01" and period["ends_on"] == POSTING_DATE
    assert period["status"] == "Open"
    assert db.scalar("SELECT COUNT(*) FROM fiscal_periods") == len(before) + 1
    assert db.rows("SELECT * FROM fiscal_periods WHERE code<>'2024-02' ORDER BY starts_on") == before
    with db.transaction() as tx:
        LedgerService(db)._validate_period(tx, uk_org["id"], POSTING_DATE)


def test_ensure_period_never_reopens_covering_period(db, uk_org):
    service = OpeningBalanceService(db)
    service.ensure_period(uk_org["id"], POSTING_DATE)
    period = db.one("SELECT * FROM fiscal_periods WHERE code='2024-02'")
    LedgerService(db).lock_period(period["id"], actor=ACTOR, reason="Synthetic close")
    before = db.rows("SELECT * FROM fiscal_periods")
    with pytest.raises(ValueError, match="must post to an open period"):
        service.ensure_period(uk_org["id"], POSTING_DATE)
    with pytest.raises(ValueError, match="must post to an open period"):
        service.post(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR,
                     lines=[{"account_id": accounts(db, uk_org)["BANK"], "debit": "10"}])
    assert db.rows("SELECT * FROM fiscal_periods") == before
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 0


@pytest.mark.parametrize("org_fixture", ["uk_org", "ee_org"])
@pytest.mark.parametrize("debit,credit,offset_debit,offset_credit", [
    ("100.25", "100.25", "0", "0"), ("100.25", "40.10", "0", "60.15"),
    ("40.10", "100.25", "60.15", "0"),
])
def test_post_balances_and_retained_offset(db, request, org_fixture, debit, credit, offset_debit, offset_credit):
    org = request.getfixturevalue(org_fixture)
    a = accounts(db, org)
    service = OpeningBalanceService(db)
    before = service.snapshot(org["id"], opening_date=POSTING_DATE)
    assert before["opening_batch"] is None
    batch = service.post(org["id"], posting_date=POSTING_DATE, actor=ACTOR,
        lines=[{"account_id": a["BANK"], "debit": debit}, {"account_id": a["CAPITAL"], "credit": credit}])
    posted = entries(db, batch)
    assert batch["voucher_type"] == "opening_balance" and batch["status"] == "Posted"
    assert sum((Decimal(str(e["debit"])) for e in posted), Decimal("0")) == sum(
        (Decimal(str(e["credit"])) for e in posted), Decimal("0"))
    offset = [e for e in posted if e["source_line_type"] == "opening_balance_offset"]
    if debit == credit:
        assert not offset
    else:
        assert offset[0]["account_id"] == a["RETAINED_EARNINGS"]
        assert Decimal(str(offset[0]["debit"])) == Decimal(offset_debit)
        assert Decimal(str(offset[0]["credit"])) == Decimal(offset_credit)
    assert all(e["memo"] == "Opening balances" and e["currency"] == org["base_currency"] for e in posted)
    snapshot = service.snapshot(org["id"], opening_date=POSTING_DATE)
    assert snapshot["opening_batch"]["id"] == batch["id"]
    assert next(r for r in snapshot["accounts"] if r["id"] == a["BANK"])["balance"] == Decimal(debit)
    assert all(r["balance"] == 0 for r in service.snapshot(org["id"], opening_date="2024-02-28")["accounts"])
    closes(db, org)


def test_post_idempotency_compares_input_not_generated_offset(db, uk_org):
    a = accounts(db, uk_org)
    service = OpeningBalanceService(db)
    lines = [{"account_id": a["BANK"], "debit": "100"}, {"account_id": a["CAPITAL"], "credit": "40"}]
    args = dict(posting_date=POSTING_DATE, actor=ACTOR)
    first = service.post(uk_org["id"], lines=lines, **args)
    assert service.post(uk_org["id"], lines=list(reversed(lines)), **args)["id"] == first["id"]
    assert service.post(uk_org["id"], lines=[], **args)["id"] == first["id"]
    equivalent = [{"account_id": a["BANK"], "debit": "50.00"}] * 2 + [lines[1]]
    assert service.post(uk_org["id"], lines=equivalent, **args)["id"] == first["id"]
    for changed in ([{**lines[0], "debit": "101"}, lines[1]],
                    lines + [{"account_id": a["RETAINED_EARNINGS"], "credit": "60"}]):
        with pytest.raises(ValueError, match="already posted; add a correcting journal"):
            service.post(uk_org["id"], lines=changed, **args)
    with pytest.raises(ValueError, match="already posted"):
        service.post(uk_org["id"], lines=lines, posting_date="2024-03-01", actor=ACTOR)
    assert len(entries(db, first)) == 3
    LedgerService(db).reverse(first["id"], reversal_date=POSTING_DATE, actor=ACTOR)
    with pytest.raises(ValueError, match="already posted"):
        service.post(uk_org["id"], lines=lines, **args)


@pytest.mark.parametrize("debit,credit", [("-1", "0"), ("1", "1"), ("NaN", "0"),
    ("Infinity", "0"), ("0.001", "0"), (0.1, "0"), (True, "0"), ("junk", "0")])
def test_invalid_opening_input_rejected_atomically(db, uk_org, debit, credit):
    with pytest.raises(ValueError):
        OpeningBalanceService(db).post(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR,
            lines=[{"account_id": accounts(db, uk_org)["BANK"], "debit": debit, "credit": credit}])
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 0
    assert db.scalar("SELECT COUNT(*) FROM fiscal_periods WHERE code='2024-02'") == 0


@pytest.mark.parametrize("role", ["SALES", "EXPENSE"])
def test_income_expense_rejected(db, uk_org, role):
    with pytest.raises(ValueError, match="income and expense accounts are not allowed"):
        OpeningBalanceService(db).post(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR,
            lines=[{"account_id": accounts(db, uk_org)[role], "debit": "10"}])


def test_missing_retained_and_empty_inputs(db, uk_org):
    a = accounts(db, uk_org)
    service = OpeningBalanceService(db)
    with pytest.raises(ValueError, match="non-zero"):
        service.post(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR, lines=[])
    with db.transaction() as tx:
        tx.execute("UPDATE accounts SET system_role=NULL WHERE id=?", (a["RETAINED_EARNINGS"],))
    with pytest.raises(ValueError, match="RETAINED_EARNINGS"):
        service.post(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR,
                     lines=[{"account_id": a["BANK"], "debit": "10"}])


@pytest.mark.parametrize("org_fixture", ["uk_org", "ee_org"])
def test_open_items_control_contact_balances_and_idempotency(db, request, org_fixture):
    org = request.getfixturevalue(org_fixture)
    service = OpeningBalanceService(db)
    a = accounts(db, org)
    preview = parse_open_items_csv(CSV)
    assert preview["totals"] == {"customer": Decimal("120.25"), "supplier": Decimal("80.10")}
    batch = service.post_open_items(org["id"], posting_date=POSTING_DATE, actor=ACTOR, rows=CSV)
    assert batch["voucher_id"] == hashlib.sha256(CSV.encode()).hexdigest()[:16]
    posted = entries(db, batch)
    assert len(posted) == 4
    for role, debit, credit, number, due in (("AR", "120.25", "0", "OLD-SALE", "2024-03-10"),
                                           ("AP", "0", "80.10", "OLD-BILL", "2024-03-11")):
        entry = next(e for e in posted if e["account_id"] == a[role])
        assert entry["contact_id"] and entry["due_date"] == due
        assert entry["memo"].startswith(f"Opening: {number} 2024-01-")
        assert Decimal(str(entry["debit"])) == Decimal(debit)
        assert Decimal(str(entry["credit"])) == Decimal(credit)
        contact_balance = sum((Decimal(str(e["debit"])) - Decimal(str(e["credit"])) for e in db.rows(
            "SELECT * FROM gl_entries WHERE organisation_id=? AND contact_id=?", (org["id"], entry["contact_id"]))), Decimal("0"))
        assert contact_balance == Decimal(debit) - Decimal(credit)
    before = db.rows("SELECT * FROM contacts"), db.rows("SELECT * FROM gl_entries")
    assert service.post_open_items(org["id"], posting_date=POSTING_DATE, actor=ACTOR, rows=CSV)["id"] == batch["id"]
    assert before == (db.rows("SELECT * FROM contacts"), db.rows("SELECT * FROM gl_entries"))
    different = service.post_open_items(org["id"], posting_date=POSTING_DATE, actor=ACTOR,
                                       rows=CSV.replace("120.25", "10.25"))
    assert different["id"] != batch["id"]
    assert db.scalar("SELECT COUNT(*) FROM contacts") == 2
    assert db.scalar("SELECT COUNT(*) FROM invoices") == db.scalar("SELECT COUNT(*) FROM bills") == 0
    closes(db, org)
    with pytest.raises(ValueError, match="file already posted"):
        service.post_open_items(org["id"], posting_date="2024-03-01", actor=ACTOR, rows=CSV)


def test_contact_reuse_flags_and_tenant_scope(db, uk_org, ee_org):
    docs = DocumentService(db)
    contact = docs.create_contact(uk_org["id"], name="Synthetic customer", country_code="GB", contact_type="supplier")
    foreign = docs.create_contact(ee_org["id"], name="Synthetic supplier", country_code="EE")
    OpeningBalanceService(db).post_open_items(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR, rows=CSV)
    assert db.scalar("SELECT contact_type FROM contacts WHERE id=?", (contact["id"],)) == "both"
    assert db.scalar("SELECT COUNT(*) FROM contacts WHERE organisation_id=?", (uk_org["id"],)) == 2
    assert not db.one("SELECT id FROM gl_entries WHERE contact_id=?", (foreign["id"],))


@pytest.mark.parametrize("bad", [
    CSV.replace("customer,", "other,", 1), CSV.replace("120.25", "-1"), CSV.replace("120.25", "0"),
    CSV.replace("120.25", "NaN"), CSV.replace("120.25", "0.001"), CSV.replace("2024-01-10", "bad"),
    CSV.replace("2024-03-10", "bad"), CSV.replace("Synthetic customer", ""),
    CSV.replace("OLD-SALE", ""), CSV.replace("120.25", "120.25,extra"),
    CSV.replace("120.25", '"unterminated'),
])
def test_csv_errors_include_row_numbers(bad):
    with pytest.raises(ValueError, match="Row [23]"):
        parse_open_items_csv(bad)


def test_csv_header_empty_bom_and_multiple_errors():
    for text in ("", "wrong,columns\n", "type,name,original_number,original_date,due_date,amount\n"):
        with pytest.raises(ValueError, match="Row [12]"):
            parse_open_items_csv(text)
    assert parse_open_items_csv("\ufeff" + CSV) == parse_open_items_csv(CSV)
    with pytest.raises(ValueError, match="Row 2:.*Row 3:"):
        parse_open_items_csv(CSV.replace("120.25", "-1").replace("80.10", "-2"))


@pytest.mark.parametrize("operation", ["balances", "items"])
def test_failed_post_rolls_back_periods_contacts_and_ledger(db, uk_org, monkeypatch, operation):
    import ledger
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic audit failure")
    monkeypatch.setattr(ledger, "audit", fail)
    with pytest.raises(RuntimeError, match="Synthetic audit failure"):
        service = OpeningBalanceService(db)
        if operation == "items":
            service.post_open_items(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR, rows=CSV)
        else:
            service.post(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR,
                         lines=[{"account_id": accounts(db, uk_org)["BANK"], "debit": "10"}])
    for table in ("contacts", "gl_entries", "posting_batches"):
        assert db.scalar(f"SELECT COUNT(*) FROM {table}") == 0
    assert db.scalar("SELECT COUNT(*) FROM fiscal_periods WHERE code='2024-02'") == 0


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    reset_database_cache()
    from api_app import api
    with TestClient(api, headers={"X-Test-User": ACTOR}) as client:
        yield client
    reset_database_cache()


def test_routes_preview_posts_and_tenant_validation(client, db, uk_org, ee_org):
    base = f"/organisations/{uk_org['id']}/opening-balance"
    snapshot = client.get(base, params={"opening_date": POSTING_DATE})
    assert snapshot.status_code == 200 and snapshot.json()["opening_batch"] is None
    preview = client.get(base + "/open-items/preview", params={"csv_content": CSV})
    assert preview.status_code == 200 and Decimal(str(preview.json()["totals"]["customer"])) == Decimal("120.25")
    assert client.post(base + "/open-items/preview", json={"csv_content": CSV}).status_code == 200
    payload = {"posting_date": POSTING_DATE, "lines": [{"account_id": accounts(db, ee_org)["BANK"], "debit": "10"}]}
    foreign = client.post(base, json=payload)
    assert foreign.status_code == 404 and foreign.json() == {"detail": "Account not found in this organisation or inactive"}
    payload["lines"][0]["account_id"] = "missing"
    assert client.post(base, json=payload).status_code == 404
    payload["lines"][0]["account_id"] = accounts(db, uk_org)["BANK"]
    response = client.post(base, json=payload)
    assert response.status_code == 201, response.text
    assert client.post(base, json=payload).json()["id"] == response.json()["id"]
    payload["lines"][0]["debit"] = "11"
    assert client.post(base, json=payload).status_code == 422
    raw = {"posting_date": POSTING_DATE, "csv_content": CSV}
    first = client.post(base + "/open-items", json=raw)
    assert first.status_code == 201, first.text
    assert client.post(base + "/open-items", json=raw).json()["id"] == first.json()["id"]
    parsed = client.post(base + "/open-items", json={"posting_date": POSTING_DATE, "rows": preview.json()["rows"]})
    assert parsed.status_code == 201, parsed.text
    for body in ({"posting_date": POSTING_DATE}, {**raw, "rows": []}):
        assert client.post(base + "/open-items", json=body).status_code == 422
    assert client.get(base, params={"opening_date": "invalid"}).status_code == 422
    closes(db, uk_org)


def test_route_roles_csrf_and_missing_organisation(client, db, uk_org):
    from api_app import api, current_user, User
    from starlette.middleware.sessions import SessionMiddleware
    base = f"/organisations/{uk_org['id']}/opening-balance"
    with db.transaction() as tx:
        tx.execute("INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,'viewer','2026-10-01')",
                   (new_id(), uk_org["id"], "viewer@example.test"))
    viewer = {"X-Test-User": "viewer@example.test"}
    payload = {"posting_date": POSTING_DATE, "lines": []}
    assert client.get(base, params={"opening_date": POSTING_DATE}, headers=viewer).status_code == 200
    assert client.get(base + "/open-items/preview", params={"csv_content": CSV}, headers=viewer).status_code == 200
    assert client.post(base, json=payload, headers=viewer).status_code == 403
    assert client.post(base + "/open-items", json={"posting_date": POSTING_DATE, "csv_content": CSV}, headers=viewer).status_code == 403
    assert client.get(base, params={"opening_date": POSTING_DATE}, headers={"X-Test-User": "outsider@example.test"}).status_code == 403
    assert client.get("/organisations/missing/opening-balance", params={"opening_date": POSTING_DATE}).status_code == 403
    # Match other organisation routes: missing membership is forbidden. Services
    # return not-found for missing organisations independently of the role gate.
    with pytest.raises(KeyError, match="Organisation not found"):
        OpeningBalanceService(db).snapshot("missing", opening_date=POSTING_DATE)
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        with TestClient(SessionMiddleware(api, secret_key="synthetic-csrf")) as session:
            assert session.post(base, json=payload).status_code == 403
            assert session.post(base + "/open-items", json={"posting_date": POSTING_DATE, "csv_content": CSV}).status_code == 403
            token = session.get("/csrf").json()["csrf_token"]
            valid = session.post(base + "/open-items", headers={"X-CSRF-Token": token},
                                 json={"posting_date": POSTING_DATE, "csv_content": CSV})
            assert valid.status_code == 201, valid.text
    finally:
        api.dependency_overrides.pop(current_user, None)


def test_workspace_opening_balances_and_open_items_browser(client, db, uk_org, monkeypatch, tmp_path):
    from urllib.parse import urlsplit
    from playwright.sync_api import sync_playwright, expect
    from web_app import app

    monkeypatch.setenv("FASTACCOUNTS_DEFAULT_LANG", "en")
    html = TestClient(app).get("/auth/test").text
    root = Path(__file__).resolve().parents[1]
    errors = []
    a = accounts(db, uk_org)
    account_rows = {r["id"]: r for r in db.rows("SELECT * FROM accounts WHERE organisation_id=?", (uk_org["id"],))}
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            url = urlsplit(route.request.url)
            if url.path == "/api/csrf":
                return route.fulfill(json={"csrf_token": "synthetic-browser-csrf"})
            if url.path.startswith("/api/"):
                headers = {k: v for k, v in route.request.headers.items() if k in {"content-type", "x-csrf-token"}}
                response = client.request(route.request.method, url.path[4:] + ("?" + url.query if url.query else ""),
                    content=route.request.post_data_buffer, headers=headers)
                return route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)
            if url.path == "/app":
                return route.fulfill(body=html, content_type="text/html")
            if url.path in {"/static/app.js", "/static/app.css"}:
                return route.fulfill(path=str(root / url.path.lstrip("/")))
            return route.fulfill(status=404)

        page.route("**/*", respond)
        page.goto("http://workspace.test/app#accounting")
        page.get_by_role("button", name="Opening balances", exact=True).click()
        page.get_by_label("Posting date", exact=True).fill(POSTING_DATE)
        for role, side, amount in (("BANK", "Debit", "100.25"), ("CAPITAL", "Credit", "40.10")):
            account = account_rows[a[role]]
            page.get_by_role("spinbutton", name=f"{side} {account['code']} {account['name']}", exact=True).fill(amount)
        expect(page.locator("[data-opening-totals]")).to_contain_text("Retained earnings offset: Credit 60.15 GBP")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        assert page.locator(".dialog-card").evaluate("el => el.scrollWidth <= el.clientWidth")
        page.screenshot(path=str(tmp_path / "opening-balances-mobile.png"), full_page=True)
        page.get_by_role("button", name="Post opening balances", exact=True).click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        page.get_by_role("button", name="Opening balances", exact=True).click()
        expect(page.locator("[data-opening-status]")).to_contain_text("Opening balances already posted")
        expect(page.get_by_role("button", name="Post opening balances", exact=True)).to_be_disabled()
        page.get_by_role("dialog").get_by_role("button", name="Close", exact=True).click()
        page.get_by_role("button", name="Opening receivables/payables", exact=True).click()
        page.get_by_label("Posting date", exact=True).fill(POSTING_DATE)
        file_input = page.get_by_label("CSV file", exact=True)
        file_input.set_input_files({"name": "synthetic-opening.csv", "mimeType": "text/csv", "buffer": CSV.encode()})
        expect(page.get_by_role("button", name="Post opening items", exact=True)).to_be_disabled()
        page.get_by_role("button", name="Preview opening items", exact=True).click()
        expect(page.locator("[data-opening-items-preview]")).to_contain_text("OLD-SALE")
        expect(page.locator("[data-opening-items-preview]")).to_contain_text("Customer total: £120.25")
        assert page.locator(".dialog-card").evaluate("el => el.scrollWidth <= el.clientWidth")
        # Changing the file invalidates the reviewed content until another preview.
        file_input.set_input_files({"name": "synthetic-opening-again.csv", "mimeType": "text/csv", "buffer": CSV.encode()})
        expect(page.get_by_role("button", name="Post opening items", exact=True)).to_be_disabled()
        page.get_by_role("button", name="Preview opening items", exact=True).click()
        expect(page.get_by_role("button", name="Post opening items", exact=True)).to_be_enabled()
        page.screenshot(path=str(tmp_path / "opening-items-mobile.png"), full_page=True)
        page.get_by_role("button", name="Post opening items", exact=True).click()
        expect(page.get_by_role("dialog")).to_have_count(0)
        assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 2
        assert db.scalar("SELECT COUNT(*) FROM contacts") == 2
        assert not errors
        closes(db, uk_org)
        browser.close()


@pytest.mark.parametrize("operation", ["balances", "items"])
def test_concurrent_retries_have_one_batch(db, uk_org, operation):
    from concurrent.futures import ThreadPoolExecutor
    a = accounts(db, uk_org)
    def post():
        service = OpeningBalanceService(db)
        if operation == "items":
            return service.post_open_items(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR, rows=CSV)
        return service.post(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR,
                            lines=[{"account_id": a["BANK"], "debit": "10"}])
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: post(), range(2)))
    assert results[0]["id"] == results[1]["id"]
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 1
    assert db.scalar("SELECT COUNT(*) FROM contacts") == (2 if operation == "items" else 0)


@pytest.mark.parametrize("side,role,kind", [("customer", "AR", "Asset"), ("supplier", "AP", "Liability")])
def test_one_sided_items_and_missing_control(db, uk_org, side, role, kind):
    service = OpeningBalanceService(db)
    a = accounts(db, uk_org)
    row = next(r for r in parse_open_items_csv(CSV)["rows"] if r["type"] == side)
    with db.transaction() as tx:
        tx.execute("UPDATE accounts SET active=0 WHERE id=?", (a[role],))
    with pytest.raises(ValueError, match=role):
        service.post_open_items(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR, rows=[row])
    assert db.scalar("SELECT COUNT(*) FROM contacts") == 0
    assert db.scalar("SELECT COUNT(*) FROM fiscal_periods WHERE code='2024-02'") == 0
    with db.transaction() as tx:
        tx.execute("UPDATE accounts SET active=1 WHERE id=?", (a[role],))
    batch = service.post_open_items(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR, rows=[row])
    assert len(entries(db, batch)) == 2
    assert service.post_open_items(uk_org["id"], posting_date=POSTING_DATE, actor=ACTOR, rows=[row])["id"] == batch["id"]
    closes(db, uk_org)
