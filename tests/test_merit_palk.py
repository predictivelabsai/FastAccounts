"""Synthetic Merit Palk contracts and on-demand reviewed imports. No live API calls."""
import base64
import hashlib
import hmac
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from connectors.providers import MeritPalkProvider
from connectors.registry import REGISTRY, connector_for, provider_metadata
from database import reset_database_cache
from import_service import ImportService
from integration_service import AccountMappingService, IntegrationService
from organisations import OrganisationService
from payroll import PayrollService

ACTOR = "owner@example.test"
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
OPTIONS = {"month": "202610", "salary_amount_basis": "monthly"}


def employee():
    return dict(FirstName="Mari", SurName="Testmaa", PersonalCode="49003159999", ImportCode=42,
                Email="mari@example.test", TypeId=1, StartDate="2025-01-01")


def agreement():
    return dict(PersonalCode="49003159999", Amount="2400.1250", Hours="8.00",
                ContractType=1, StartDate="2025-01-01")


@pytest.fixture
def palk(db, ee_org, monkeypatch):
    seen = []
    accounts = db.rows("SELECT code FROM accounts WHERE organisation_id=? ORDER BY code LIMIT 2", (ee_org["id"],))
    state = {
        "getemployees": [employee()], "getpayterms": {"EntryRow": [agreement()]},
        "getglbatch": {"DocNo": "SYNTHETIC-PAY", "BatchDate": "2026-10-24", "EntryRow": [
            {"AccountCode": accounts[0]["code"], "Debit": "2400.13", "Credit": "0", "DepartmentCode": "SYNTHETIC"},
            {"AccountCode": accounts[1]["code"], "Debit": "0", "Credit": "2400.13"}]},
        "getsalaryreport": [{"EmployeeFullName": "Mari Testmaa", "SalaryTypeName": "Base salary", "Month6": "202610", "Hours": "160", "Sum": "2400.13"}],
        "getvacoblig": {"DaysUnused": "12.34", "DaysAcquired": "3.00"},
    }

    def handler(request):
        seen.append(request)
        value = state[request.url.path.rsplit("/", 1)[-1]]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    registration = REGISTRY["merit_palk"]
    monkeypatch.setitem(REGISTRY, "merit_palk", replace(registration, factory=lambda credentials, config:
        MeritPalkProvider(credentials["api_id"], credentials["api_key"], config=config,
                          client=client, clock=lambda: NOW, retries=0)))
    integration = IntegrationService(db)
    public = integration.configure(ee_org["id"], "merit_palk",
        credentials={"api_id": "synthetic-id", "api_key": "synthetic-key-1"}, config={}, actor=ACTOR)
    service = ImportService(db, integration=integration)
    yield service, state, seen, public
    client.close()


def stage(palk, oid, kind="employee", config=None):
    service = palk[0]
    sync = service.run_sync(oid, "merit_palk", kind, actor=ACTOR, config=OPTIONS if config is None else config)
    return sync, service.get_staged(oid, sync_run_id=sync["id"])["records"]


def apply(palk, oid, sync, rows):
    return palk[0].apply_staged(oid, "merit_palk", sync["id"], {row["id"]: "apply" for row in rows}, actor=ACTOR)


def test_exact_signing_utc_and_encoded_plus():
    seen = []
    provider = MeritPalkProvider("synthetic-id", "synthetic-key-1",
        clock=lambda: NOW.astimezone(timezone(timedelta(hours=3))),
        client=httpx.Client(transport=httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(200, json=[]))))
    assert provider.check().ok
    req = seen[0]
    assert req.method == "POST" and req.url.host == "palk.merit.ee" and req.url.path == "/api/v1/getemployees"
    assert req.content == b"{}"
    assert dict(req.url.params) == {"apiId": "synthetic-id", "timestamp": "20261024120000",
                                  "signature": "cb1x4Y6KJS34mE/Z+GzQzoXE+1bRRu3aORcMHPO+vak="}
    assert "%2B" in req.url.query.decode() and "+" not in req.url.query.decode()
    assert req.headers["content-type"] == "application/json"
    provider.post("getemployees", {"PersonalCode": "Sünteetiline"})
    req = seen[-1]
    assert req.url.params["signature"] == base64.b64encode(hmac.new(
        b"synthetic-key-1", b"synthetic-id20261024120000" + req.content, hashlib.sha256).digest()).decode()
    assert "Sünteetiline".encode() in req.content


def test_invalid_credentials_and_naive_clock_do_not_send_requests():
    def forbidden(request):
        raise AssertionError("No request should be sent")
    client = httpx.Client(transport=httpx.MockTransport(forbidden))
    for api_id, key in (("", "synthetic"), ("synthetic", ""), ("synthetic", "salajane-õ")):
        result = MeritPalkProvider(api_id, key, client=client).check()
        assert not result.ok and not result.live and "salajane" not in result.message
    result = MeritPalkProvider("synthetic", "synthetic", clock=lambda: datetime(2026, 10, 24), client=client).check()
    assert not result.ok and not result.live and "timezone" in result.message


@pytest.mark.parametrize("kind,basis,board", [(1, "monthly", False), (2, "board_fee", True), (5, "income_line", False)])
def test_contract_types_import_code_and_salary(palk, ee_org, kind, basis, board):
    palk[1]["getemployees"][0]["TypeId"] = kind
    sync, rows = stage(palk, ee_org["id"])
    payload = rows[0]["external_payload"]
    assert payload["external_id"] == "42" and payload["personal_id"] == "49003159999"
    assert payload["board_member"] is board and payload.get("pay_basis") == basis
    if kind != 5:
        assert Decimal(payload["gross_salary"]) == Decimal("2400.13")
    outcome = apply(palk, ee_org["id"], sync, rows)
    if kind == 5:
        assert payload["merit_palk_income_basis"] == "income_line"
        assert "gross_salary" not in payload and outcome["applied"] == 1
        saved = palk[0].db.one("SELECT * FROM employees WHERE organisation_id=?", (ee_org["id"],))
        assert saved["pay_basis"] == "income_line" and saved["gross_salary"] is None
    else:
        assert outcome["applied"] == 1
        saved = palk[0].db.one("SELECT * FROM employees WHERE organisation_id=?", (ee_org["id"],))
        assert bool(saved["board_member"]) is board and saved["pay_basis"] == basis


@pytest.mark.parametrize("dates", [{"EndDate": "2026-10-01"}, {"StartDate": "2027-01-01"}])
def test_historical_import_does_not_activate_ended_or_future_contracts(palk, ee_org, dates):
    palk[1]["getemployees"][0].update(dates)
    _, rows = stage(palk, ee_org["id"], config=dict(OPTIONS, month="202609"))
    assert rows[0]["external_payload"]["active"] is False


def test_personal_code_then_import_code_upsert_and_salary_agreement(palk, ee_org, db):
    local = PayrollService(db).save_employee(ee_org["id"], name="Previous Name", personal_id="49003159999",
                                            gross_salary="2000", actor=ACTOR)
    sync, rows = stage(palk, ee_org["id"])
    assert rows[0]["matched_local_id"] == local["id"] and rows[0]["match"]["strategy"] == "personal_id"
    assert apply(palk, ee_org["id"], sync, rows)["updated"] == 1
    # The provider mapping survives a changed personal code.
    palk[1]["getemployees"][0]["PersonalCode"] = "49003158888"
    palk[1]["getpayterms"]["EntryRow"][0]["PersonalCode"] = "49003158888"
    sync, rows = stage(palk, ee_org["id"])
    assert rows[0]["match"]["strategy"] == "external_mapping"
    assert apply(palk, ee_org["id"], sync, rows)["updated"] == 1
    palk[1]["getpayterms"]["EntryRow"][0]["Amount"] = "2600"
    sync, rows = stage(palk, ee_org["id"], "salary_agreement")
    assert rows[0]["matched_local_employee_name"] == "Mari Testmaa"
    assert apply(palk, ee_org["id"], sync, rows)["updated"] == 1
    assert Decimal(str(db.scalar("SELECT gross_salary FROM employees WHERE id=?", (local["id"],)))) == Decimal("2600")
    assert db.scalar("SELECT COUNT(*) FROM employees WHERE organisation_id=?", (ee_org["id"],)) == 1
    sync, rows = stage(palk, ee_org["id"], "salary_agreement")
    assert apply(palk, ee_org["id"], sync, rows)["unchanged"] == 1


def test_import_code_identity_is_shared_between_employee_and_agreement_pulls(palk, ee_org, db):
    sync, rows = stage(palk, ee_org["id"])
    assert apply(palk, ee_org["id"], sync, rows)["applied"] == 1
    palk[1]["getemployees"][0]["PersonalCode"] = "49003158888"
    palk[1]["getpayterms"]["EntryRow"][0]["PersonalCode"] = "49003158888"
    sync, rows = stage(palk, ee_org["id"], "salary_agreement")
    assert rows[0]["match"]["strategy"] == "external_mapping"
    assert apply(palk, ee_org["id"], sync, rows)["updated"] == 1
    assert db.scalar("SELECT COUNT(*) FROM employees WHERE organisation_id=?", (ee_org["id"],)) == 1


@pytest.mark.parametrize("change", ["unconfirmed", "missing", "multiple", "unknown"])
def test_ambiguous_pay_terms_block_apply(palk, ee_org, change):
    options = dict(OPTIONS)
    if change == "unconfirmed":
        options.pop("salary_amount_basis")
    elif change == "missing":
        palk[1]["getpayterms"]["EntryRow"] = []
    elif change == "multiple":
        palk[1]["getpayterms"]["EntryRow"].append(agreement())
    else:
        palk[1]["getemployees"][0]["TypeId"] = 5 if change == "services" else 4
    sync, rows = stage(palk, ee_org["id"], config=options)
    assert rows[0]["review_note"]
    assert apply(palk, ee_org["id"], sync, rows)["failed"] == 1


def test_request_fields_and_personal_code_fallback(palk, ee_org):
    palk[1]["getemployees"][0].pop("ImportCode")
    _, rows = stage(palk, ee_org["id"], "salary_agreement", dict(OPTIONS, month="202402", personal_code="49003159999"))
    assert rows[0]["external_id"] == "49003159999"
    assert json.loads(palk[2][0].content) == {"Month6": "202402", "PersonalCode": "49003159999"}
    assert json.loads(palk[2][1].content) == {"StartMonth": "202402", "EndMonth": "202402", "PersonalID": "49003159999"}


def test_salary_agreements_preserved_without_employee_list_entry(palk, ee_org):
    palk[1]["getemployees"] = []
    palk[1]["getpayterms"]["EntryRow"][0]["Employee Name"] = "Mari Testmaa"
    sync, rows = stage(palk, ee_org["id"], "salary_agreement")
    assert rows[0]["external_payload"]["name"] == "Mari Testmaa"
    assert rows[0]["external_id"] == "49003159999"
    assert apply(palk, ee_org["id"], sync, rows)["applied"] == 1


def test_multiple_employee_contracts_are_reviewed_without_guessing(palk, ee_org):
    second = dict(palk[1]["getemployees"][0], ImportCode=43)
    palk[1]["getemployees"].append(second)
    sync, rows = stage(palk, ee_org["id"])
    assert len(rows) == 2 and all("multiple contracts" in row["review_note"] for row in rows)
    assert apply(palk, ee_org["id"], sync, rows)["failed"] == 2
    sync, rows = stage(palk, ee_org["id"], "salary_agreement")
    assert "multiple contracts" in rows[0]["review_note"]
    assert apply(palk, ee_org["id"], sync, rows)["failed"] == 1


def test_gl_stages_balanced_journal_posts_once_and_preserves_source(palk, ee_org, db):
    sync, rows = stage(palk, ee_org["id"], "gl_entry")
    assert rows[0]["object_type"] == "journal" and rows[0]["journal_review"]["balanced"]
    assert rows[0]["external_payload"]["merit_palk_source"]["EntryRow"][0]["DepartmentCode"] == "SYNTHETIC"
    assert db.scalar("SELECT COUNT(*) FROM posting_batches WHERE organisation_id=?", (ee_org["id"],)) == 0
    assert apply(palk, ee_org["id"], sync, rows)["applied"] == 1
    again, repeated = stage(palk, ee_org["id"], "gl_entry")
    assert apply(palk, ee_org["id"], again, repeated)["unchanged"] == 1
    entries = db.rows("SELECT debit,credit FROM gl_entries WHERE organisation_id=?", (ee_org["id"],))
    assert sum(Decimal(str(row["debit"])) for row in entries) == sum(Decimal(str(row["credit"])) for row in entries) == Decimal("2400.13")
    assert db.scalar("SELECT COUNT(*) FROM posting_batches WHERE voucher_type='merit_palk_journal'") == 1
    assert json.loads(palk[2][0].content) == {"Month": "202610"}


def test_gl_mapping_is_provider_scoped_and_unbalanced_is_blocked(palk, ee_org, db):
    code = palk[1]["getglbatch"]["EntryRow"][0]["AccountCode"]
    palk[1]["getglbatch"]["EntryRow"][0]["AccountCode"] = "SYNTHETIC-EXTERNAL"
    maps = AccountMappingService(db)
    maps.create(ee_org["id"], "file_import", local_account_code=code,
                external_account_code="SYNTHETIC-EXTERNAL", status="Confirmed", actor=ACTOR)
    sync, rows = stage(palk, ee_org["id"], "gl_entry")
    assert not rows[0]["journal_review"]["valid"]
    assert apply(palk, ee_org["id"], sync, rows)["failed"] == 1
    maps.create(ee_org["id"], "merit_palk", local_account_code=code,
                external_account_code="SYNTHETIC-EXTERNAL", status="Confirmed", actor=ACTOR)
    assert apply(palk, ee_org["id"], sync, rows)["applied"] == 1
    palk[1]["getglbatch"]["DocNo"] = "UNBALANCED"
    palk[1]["getglbatch"]["EntryRow"][1]["Credit"] = "1"
    sync, rows = stage(palk, ee_org["id"], "gl_entry")
    assert not rows[0]["journal_review"]["balanced"]
    assert apply(palk, ee_org["id"], sync, rows)["failed"] == 1


def test_gl_changed_posted_batch_requires_explicit_correction(palk, ee_org, db):
    sync, rows = stage(palk, ee_org["id"], "gl_entry")
    assert apply(palk, ee_org["id"], sync, rows)["applied"] == 1
    palk[1]["getglbatch"]["EntryRow"][0]["Debit"] = "2600"
    palk[1]["getglbatch"]["EntryRow"][1]["Credit"] = "2600"
    sync, rows = stage(palk, ee_org["id"], "gl_entry")
    result = apply(palk, ee_org["id"], sync, rows)
    assert result["failed"] == 1 and "reverse the original" in result["outcomes"][0]["reason"]
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 1


@pytest.mark.parametrize("change", ["lock", "inactive"])
def test_gl_apply_rechecks_period_and_accounts(palk, ee_org, db, change):
    sync, rows = stage(palk, ee_org["id"], "gl_entry")
    with db.transaction() as tx:
        if change == "lock":
            tx.execute("UPDATE fiscal_periods SET status='Locked' WHERE organisation_id=?", (ee_org["id"],))
        else:
            tx.execute("UPDATE accounts SET active=0 WHERE organisation_id=?", (ee_org["id"],))
    assert apply(palk, ee_org["id"], sync, rows)["failed"] == 1
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 0


def test_vacation_display_only_and_salary_report_contract(palk, ee_org, db):
    options = dict(OPTIONS, personal_code="42", balance_date="2026-10-23")
    sync, rows = stage(palk, ee_org["id"], "vacation_balance", options)
    assert rows[0]["display_only"] and rows[0]["external_payload"]["DaysUnused"] == "12.34"
    assert "Display-only" in rows[0]["review_note"]
    assert json.loads(palk[2][-1].content) == {"ContractCode": "42", "Date": "2026-10-23"}
    with pytest.raises(ValueError, match="Display-only"):
        apply(palk, ee_org["id"], sync, rows)
    _, salary_rows = stage(palk, ee_org["id"], "salary_hours")
    assert "unique local employee" in salary_rows[0]["review_note"]
    palk[1]["getsalaryreport"][0]["Month6"] = "202402"
    connector = connector_for("merit_palk", credentials={"api_id": "synthetic-id", "api_key": "synthetic-key-1"}, config={"month": "202402"})
    report = connector.pull("salary_hours")
    assert report.records[0]["hours"] == Decimal("160.00")
    assert json.loads(palk[2][-1].content) == {"StartDate": "2024-02-01", "EndDate": "2024-02-29", "Language": "EN", "SortOption": 2}
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 0


@pytest.mark.parametrize("response,message,live", [
    (httpx.Response(401), "PRO licence", True),
    (httpx.Response(400), "request data", True),
    (httpx.Response(200, content=b"invalid"), "invalid JSON", True),
    (httpx.Response(200, json={"error": "private"}), "invalid data response", True),
    (httpx.ConnectError("private key must not leak"), "connection error or timeout", False),
    (httpx.ReadTimeout("private key must not leak"), "connection error or timeout", False),
])
def test_safe_errors_in_check_and_sync(palk, ee_org, response, message, live):
    palk[1]["getemployees"] = response
    provider = connector_for("merit_palk", credentials={"api_id": "synthetic-id", "api_key": "synthetic-key-1"})
    check = provider.check()
    assert not check.ok and check.live is live and message in check.message
    with pytest.raises(ValueError, match=message):
        stage(palk, ee_org["id"])
    assert "private" not in str(palk[0].syncs(ee_org["id"], "merit_palk"))


def test_result_ceiling_invalid_month_and_response_validation(palk, ee_org):
    palk[1]["getemployees"] *= 100
    with pytest.raises(ValueError, match="100 records"):
        stage(palk, ee_org["id"])
    for month in ("202613", "2026-01", "bad"):
        with pytest.raises(ValueError, match="YYYYMM"):
            stage(palk, ee_org["id"], config={"month": month})
    with pytest.raises(ValueError, match="requires a contract"):
        stage(palk, ee_org["id"], "vacation_balance")


def test_salary_hours_create_draft_decimal_round_trip_and_idempotency(palk, ee_org, db):
    sync, rows = stage(palk, ee_org["id"])
    apply(palk, ee_org["id"], sync, rows)
    palk[1]["getsalaryreport"][0]["Sum"] = "2500.125"
    sync, rows = stage(palk, ee_org["id"], "salary_hours")
    assert Decimal(rows[0]["external_payload"]["gross_pay"]) == Decimal("2500.13")
    assert apply(palk, ee_org["id"], sync, rows)["applied"] == 1
    run = PayrollService(db).runs(ee_org["id"])[0]
    assert run["status"] == "Draft" and Decimal(run["total_gross"]) == Decimal("2500.13")
    assert Decimal(str(db.scalar("SELECT gross_salary FROM employees WHERE organisation_id=?", (ee_org["id"],)))) == Decimal("2400.13")
    assert apply(palk, ee_org["id"], sync, rows)["unchanged"] == 1
    again, records = stage(palk, ee_org["id"], "salary_hours")
    assert apply(palk, ee_org["id"], again, records)["unchanged"] == 1
    assert db.scalar("SELECT COUNT(*) FROM pay_runs") == 1
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 0


def test_salary_hours_hourly_draft_reconciles_gross_and_preserves_rate(palk, ee_org, db):
    payroll = PayrollService(db)
    person = payroll.save_employee(ee_org["id"], name="Mari Testmaa", pay_basis="hourly", hourly_rate="15", actor=ACTOR)
    run = payroll.create_run(ee_org["id"], period="2026-10", hours={person["id"]: "150"}, actor=ACTOR)
    sync, rows = stage(palk, ee_org["id"], "salary_hours")
    assert apply(palk, ee_org["id"], sync, rows)["applied"] == 1
    saved = payroll.runs(ee_org["id"])[0]
    item = saved["items"][0]
    assert Decimal(item["hours"]) == Decimal("160")
    assert Decimal(item["gross"]) == Decimal("2400.13") and Decimal(item["hourly_rate"]) == Decimal("15")
    assert Decimal(item["components"][0]["amount"]) == Decimal("0.13")
    palk[1]["getsalaryreport"][0].update(Hours="170", Sum="2600.50")
    changed, records = stage(palk, ee_org["id"], "salary_hours")
    assert apply(palk, ee_org["id"], changed, records)["updated"] == 1
    item = payroll.runs(ee_org["id"])[0]["items"][0]
    assert Decimal(item["gross"]) == Decimal("2600.50")
    assert len(item["components"]) == 1 and Decimal(item["components"][0]["amount"]) == Decimal("50.50")


def test_salary_hours_updates_changed_draft_and_refuses_approved_reports(palk, ee_org, db):
    payroll = PayrollService(db)
    payroll.save_employee(ee_org["id"], name="Mari Testmaa", gross_salary="2400", actor=ACTOR)
    sync, rows = stage(palk, ee_org["id"], "salary_hours")
    assert apply(palk, ee_org["id"], sync, rows)["applied"] == 1
    palk[1]["getsalaryreport"][0]["Sum"] = "2600"
    changed, records = stage(palk, ee_org["id"], "salary_hours")
    assert apply(palk, ee_org["id"], changed, records)["updated"] == 1
    run = payroll.runs(ee_org["id"])[0]
    assert Decimal(run["total_gross"]) == Decimal("2600")
    approved = payroll.approve(ee_org["id"], run["id"], actor=ACTOR)
    before = db.rows("SELECT * FROM gl_entries")
    assert apply(palk, ee_org["id"], sync, rows)["failed"] == 1
    assert payroll.runs(ee_org["id"])[0] == approved
    assert db.rows("SELECT * FROM gl_entries") == before
    assert db.scalar("SELECT status FROM import_staged_records WHERE id=?", (rows[0]["id"],)) == "Applied"
    fresh, proposals = stage(palk, ee_org["id"], "salary_hours")
    assert apply(palk, ee_org["id"], fresh, proposals)["failed"] == 1
    assert payroll.runs(ee_org["id"])[0] == approved


def test_services_contract_without_salary_agreement_uses_income_components(palk, ee_org, db):
    palk[1]["getemployees"][0]["TypeId"] = 5
    palk[1]["getpayterms"]["EntryRow"] = []
    sync, rows = stage(palk, ee_org["id"], config={"month": "202610"})
    assert not rows[0]["review_note"] and apply(palk, ee_org["id"], sync, rows)["applied"] == 1
    palk[1]["getsalaryreport"][0].update(SalaryTypeName="Töövõtulepingu tasu", Sum="100.12", Hours="0")
    sync, rows = stage(palk, ee_org["id"], "salary_hours")
    assert apply(palk, ee_org["id"], sync, rows)["applied"] == 1
    payroll = PayrollService(db)
    run = payroll.runs(ee_org["id"])[0]
    item = run["items"][0]
    assert item["pay_basis"] == "income_line" and Decimal(item["gross_salary"]) == 0
    assert Decimal(item["gross"]) == Decimal("100.12")
    assert Decimal(item["social_tax_minimum_topup"]) == 0
    assert item["components"][0]["name"] == "Töövõtulepingu tasu"
    assert apply(palk, ee_org["id"], sync, rows)["unchanged"] == 1
    palk[1]["getsalaryreport"][0]["Sum"] = "200.13"
    changed, records = stage(palk, ee_org["id"], "salary_hours")
    assert apply(palk, ee_org["id"], changed, records)["updated"] == 1
    item = payroll.runs(ee_org["id"])[0]["items"][0]
    assert Decimal(item["gross"]) == Decimal("200.13") and len(item["components"]) == 1
    manual = payroll.update_item(ee_org["id"], run["id"], item["id"], actor=ACTOR,
        components=[{"type_id": item["components"][0]["type_id"], "amount": "300"}])
    palk[1]["getsalaryreport"][0]["Sum"] = "400"
    changed, records = stage(palk, ee_org["id"], "salary_hours")
    assert apply(palk, ee_org["id"], changed, records)["failed"] == 1
    assert payroll.runs(ee_org["id"])[0] == manual


@pytest.mark.parametrize("change", ["unknown_type", "foreign_name", "ambiguous_name", "bad_hours", "minimum"])
def test_salary_hours_warning_tenancy_and_atomic_failure(palk, ee_org, db, change):
    payroll = PayrollService(db)
    payroll.save_employee(ee_org["id"], name="Mari Testmaa", gross_salary="2400", actor=ACTOR)
    other = OrganisationService(db).create(name="Foreign payroll", country_code="EE", entity_type="EE_OU", owner_email=ACTOR)
    foreign = payroll.save_employee(other["id"], name="Foreign Name", gross_salary="2400", actor=ACTOR)
    report = palk[1]["getsalaryreport"][0]
    if change == "unknown_type":
        report["SalaryTypeName"] = "Unknown custom taxable pay"
    elif change == "foreign_name":
        report["EmployeeFullName"] = "Foreign Name"
    elif change == "ambiguous_name":
        payroll.save_employee(ee_org["id"], name="MARI TESTMAA", gross_salary="2400", actor=ACTOR)
    elif change == "bad_hours":
        report["Hours"] = "745"
        local = db.one("SELECT id FROM employees WHERE organisation_id=?", (ee_org["id"],))
        payroll.save_employee(ee_org["id"], employee_id=local["id"], pay_basis="hourly", hourly_rate="15", actor=ACTOR)
    else:
        report["Sum"] = "100"
    sync, rows = stage(palk, ee_org["id"], "salary_hours")
    if change in {"unknown_type", "foreign_name", "ambiguous_name"}:
        assert rows[0]["review_note"]
    assert apply(palk, ee_org["id"], sync, rows)["failed"] == 1
    assert db.scalar("SELECT COUNT(*) FROM pay_runs WHERE organisation_id=?", (ee_org["id"],)) == 0
    assert db.scalar("SELECT gross_salary FROM employees WHERE id=?", (foreign["id"],)) == 2400


def test_employee_cap_filters_use_only_documented_fields(palk, ee_org):
    for size in (100, 101):
        palk[1]["getemployees"] = [employee()] * size
        with pytest.raises(ValueError, match="100 records"):
            stage(palk, ee_org["id"], config=dict(OPTIONS, personal_code="49003159999"))
        assert json.loads(palk[2][-1].content) == {"Month6": "202610", "PersonalCode": "49003159999"}
    palk[1]["getemployees"] = [employee()]
    _, rows = stage(palk, ee_org["id"], config=dict(OPTIONS, personal_code="49003159999"))
    assert len(rows) == 1


def test_salary_hours_refuses_component_collision_without_changing_draft(palk, ee_org, db):
    payroll = PayrollService(db)
    payroll.save_employee(ee_org["id"], name="Mari Testmaa", gross_salary="2400", actor=ACTOR)
    run = payroll.create_run(ee_org["id"], period="2026-10", actor=ACTOR)
    kind = next(t for t in payroll.component_types(ee_org["id"]) if t["preset_key"] == "author")
    before = payroll.update_item(ee_org["id"], run["id"], run["items"][0]["id"], actor=ACTOR,
                                 components=[{"type_id": kind["id"], "amount": "100"}])
    palk[1]["getsalaryreport"].append(dict(palk[1]["getsalaryreport"][0], SalaryTypeName=kind["name"], Sum="100", Hours="0"))
    sync, rows = stage(palk, ee_org["id"], "salary_hours")
    result = apply(palk, ee_org["id"], sync, rows)
    assert result["failed"] == 1 and "already exists" in result["outcomes"][0]["reason"]
    assert payroll.runs(ee_org["id"])[0] == before


def test_salary_hours_does_not_consume_unselected_or_rejected_hours(palk, ee_org, db):
    payroll = PayrollService(db)
    payroll.save_employee(ee_org["id"], name="Mari Testmaa", gross_salary="2400", actor=ACTOR)
    payroll.save_employee(ee_org["id"], name="Hourly Person", pay_basis="hourly", hourly_rate="15", actor=ACTOR)
    palk[1]["getsalaryreport"].append(dict(palk[1]["getsalaryreport"][0], EmployeeFullName="Hourly Person"))
    sync, rows = stage(palk, ee_org["id"], "salary_hours")
    mari = next(r for r in rows if r["external_payload"]["name"] == "Mari Testmaa")
    hourly = next(r for r in rows if r["external_payload"]["name"] == "Hourly Person")
    result = palk[0].apply_staged(ee_org["id"], "merit_palk", sync["id"],
        {mari["id"]: "apply", hourly["id"]: "reject"}, actor=ACTOR)
    assert result["failed"] == 1 and result["rejected"] == 1
    assert db.scalar("SELECT COUNT(*) FROM pay_runs") == 0


def test_income_line_draft_cannot_be_approved_without_income(palk, ee_org, db):
    payroll = PayrollService(db)
    person = payroll.save_employee(ee_org["id"], name="Contract Person", pay_basis="income_line", actor=ACTOR)
    assert person["gross_salary"] is None
    run = payroll.create_run(ee_org["id"], period="2026-10", actor=ACTOR)
    with pytest.raises(ValueError, match="positive gross"):
        payroll.approve(ee_org["id"], run["id"], actor=ACTOR)
    assert payroll.runs(ee_org["id"])[0]["status"] == "Draft"
    assert db.scalar("SELECT COUNT(*) FROM posting_batches") == 0


def test_salary_hours_concurrent_apply_creates_one_draft(palk, ee_org, db):
    from concurrent.futures import ThreadPoolExecutor
    PayrollService(db).save_employee(ee_org["id"], name="Mari Testmaa", gross_salary="2400", actor=ACTOR)
    sync, rows = stage(palk, ee_org["id"], "salary_hours")
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: apply(palk, ee_org["id"], sync, rows), range(2)))
    assert sum(result["applied"] for result in outcomes) == 1
    assert sum(result["unchanged"] for result in outcomes) == 1
    assert db.scalar("SELECT COUNT(*) FROM pay_runs") == 1
    assert db.scalar("SELECT COUNT(*) FROM pay_run_items") == 1


def test_income_line_migration_preserves_approved_payroll(tmp_path, legacy_payroll):
    from database import Database, MIGRATIONS
    from shutil import copyfile
    old = tmp_path / "migrations"
    (old / "sqlite").mkdir(parents=True)
    for path in (MIGRATIONS / "sqlite").glob("*.sql"):
        if path.stem < "0035":
            copyfile(path, old / "sqlite" / path.name)
    db = Database(path=str(tmp_path / "upgrade.sqlite"))
    db.migrate(migrations=old)
    org = OrganisationService(db).create(name="Migration fixture", country_code="EE", entity_type="EE_OU", owner_email=ACTOR)
    payroll = PayrollService(db)
    run = legacy_payroll(db, org['id'], name='Existing Person', gross='2400', fte='0.75', actor=ACTOR)
    payroll.approve(org['id'], run['id'], actor=ACTOR)
    tables = ("employees", "pay_runs", "pay_run_items", "pay_item_context", "gl_entries", "posting_batches")
    before = {t: db.rows(f"SELECT * FROM {t} ORDER BY 1") for t in tables}
    assert db.migrate() == ["0035_payroll_income_line", "0036_payroll_component_catalogue", "0037_employee_tax_settings", "0038_payroll_payday_rules", "0039_payroll_payouts", "0040_payroll_settlement_dates", "0041_payroll_sepa_details", "0042_payroll_component_metadata", "0043_payroll_absences", "0044_payroll_absence_day_freeze", "0045_payroll_history', '0046_payroll_absence_pay"]
    for table in tables:
        actual = db.rows(f'SELECT * FROM {table} ORDER BY 1')
        assert [{key: row[key] for key in original} for row, original in zip(actual, before[table], strict=True)] == before[table]
    assert db.rows("PRAGMA foreign_key_check") == [] and db.migrate() == []


def test_vault_and_tenant_isolation(palk, ee_org, uk_org, db):
    public = palk[3]
    assert "credentials" not in public and "synthetic-key" not in str(public)
    encrypted = db.scalar("SELECT encrypted_credentials FROM integration_connections WHERE id=?", (public["id"],))
    assert "synthetic" not in encrypted
    other = OrganisationService(db).create(name="Other Synthetic OÜ", country_code="EE", entity_type="EE_OU", owner_email=ACTOR)
    foreign = PayrollService(db).save_employee(other["id"], name="Mari Testmaa", personal_id="49003159999", gross_salary="1000", actor=ACTOR)
    sync, rows = stage(palk, ee_org["id"])
    assert rows[0]["matched_local_employee_id"] is None
    assert apply(palk, ee_org["id"], sync, rows)["applied"] == 1
    assert db.scalar("SELECT gross_salary FROM employees WHERE id=?", (foreign["id"],)) == 1000
    with pytest.raises(KeyError, match="Sync run not found"):
        palk[0].get_staged(uk_org["id"], sync_run_id=sync["id"])
    with pytest.raises(KeyError, match="Sync run not found"):
        apply(palk, uk_org["id"], sync, rows)
    with pytest.raises(KeyError, match="configured"):
        stage(palk, uk_org["id"])
    fields = provider_metadata("merit_palk")["credential_fields"]
    assert [field["name"] for field in fields] == ["api_id", "api_key"]
    assert fields[1]["input_type"] == "secret"


@pytest.fixture
def palk_api(palk, db, monkeypatch):
    from api_app import api
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    reset_database_cache()
    with TestClient(api, headers={"X-Test-User": ACTOR}) as client:
        yield client
    reset_database_cache()


def test_on_demand_api_roles_csrf_and_tenant_boundary(palk_api, palk, ee_org, uk_org, db):
    from api_app import api
    from api_app import require_csrf
    client = palk_api
    base = f"/organisations/{ee_org['id']}/integrations/merit_palk"
    organisation = OrganisationService(db)
    for role in ("administrator", "accountant", "viewer", "approver"):
        organisation.add_member(ee_org["id"], ACTOR, f"{role}@example.test", role)
    for role in ("owner", "administrator", "accountant", "viewer", "approver"):
        headers = {"X-Test-User": ACTOR if role == "owner" else f"{role}@example.test"}
        permitted = role in {"owner", "administrator"}
        for path, body in (("", {"credentials": {"api_id": "synthetic-id", "api_key": "synthetic-key-1"}, "config": {}}),
                           ("/test", {"credentials": {"api_id": "synthetic-id", "api_key": "synthetic-key-1"}, "config": {}}),
                           ("/sync", {"object_type": "employee", "config": OPTIONS})):
            response = client.post(base + path, json=body, headers=headers)
            assert response.status_code == (200 if permitted else 403), response.text
    summary = client.post(base + "/sync", json={"object_type": "vacation_balance", "config": {"personal_code": "42"}}).json()
    assert client.get(base + f"/sync/{summary['id']}").json()["records"][0]["display_only"]
    assert client.get(f"/organisations/{uk_org['id']}/integrations/merit_palk/sync/{summary['id']}").status_code == 404
    for role in ("accountant", "viewer", "approver"):
        headers = {"X-Test-User": f"{role}@example.test"}
        assert client.get(base + f"/sync/{summary['id']}", headers=headers).status_code == 403
        assert client.post(base + f"/sync/{summary['id']}/apply", json={"decisions": {}}, headers=headers).status_code == 403
    for route in api.routes:
        if "/integrations/{provider}" in route.path and route.methods == {"POST"}:
            assert require_csrf in [dependency.call for dependency in route.dependant.dependencies]


def test_api_pro_licence_errors_and_real_csrf(palk_api, palk, ee_org):
    from api_app import api, current_user, User
    from web_app import app
    base = f"/organisations/{ee_org['id']}/integrations/merit_palk"
    palk[1]["getemployees"] = httpx.Response(401)
    checked = palk_api.post(base + "/test", json={})
    assert checked.status_code == 200 and not checked.json()["ok"]
    assert "PRO licence" in checked.json()["message"]
    synced = palk_api.post(base + "/sync", json={"object_type": "employee"})
    assert synced.status_code == 422 and "PRO licence" in synced.text
    assert "synthetic-key" not in checked.text + synced.text
    palk[1]["getemployees"] = [employee()]
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        with TestClient(app) as client:
            body = {"object_type": "employee", "config": OPTIONS}
            assert client.post('/api' + base + '/sync', json=body).status_code == 403
            token = client.get('/api/csrf').json()['csrf_token']
            assert client.post('/api' + base + '/sync', json=body, headers={'X-CSRF-Token': token}).status_code == 200
    finally:
        api.dependency_overrides.clear()


def test_services_contract_employee_is_editable_through_payroll_api(palk_api, palk, ee_org):
    palk[1]["getemployees"][0]["TypeId"] = 5
    sync, rows = stage(palk, ee_org["id"])
    assert apply(palk, ee_org["id"], sync, rows)["applied"] == 1
    base = f"/organisations/{ee_org['id']}/employees"
    person = palk_api.get(base).json()[0]
    assert person["gross_salary"] is None and person["pay_basis"] == "income_line"
    response = palk_api.patch(base + "/" + person["id"], json={"name": "Mari Contract", "pay_basis": "income_line"})
    assert response.status_code == 200, response.text
    assert response.json()["gross_salary"] is None


def test_browser_configure_test_choose_month_review_and_display_only(palk_api, palk, ee_org, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    from web_app import app
    monkeypatch.setenv("FASTACCOUNTS_DEFAULT_LANG", "en")
    html = TestClient(app).get("/auth/test").text
    root = Path(__file__).resolve().parents[1]
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == "/app":
                return route.fulfill(body=html, content_type="text/html")
            if path.startswith("/static/"):
                file = root / path.lstrip("/")
                return route.fulfill(path=str(file)) if file.is_file() else route.fulfill(status=404)
            if path == "/api/csrf":
                return route.fulfill(json={"csrf_token": "synthetic"})
            if path.startswith("/api/"):
                payload = route.request.post_data_json if route.request.post_data else None
                response = palk_api.request(route.request.method, path.removeprefix("/api"), json=payload)
                return route.fulfill(status=response.status_code, body=response.content, content_type="application/json")
            return route.fulfill(status=404)

        page.route("**/*", respond)
        page.goto("http://workspace.test/app#integrations")
        card = page.locator('.integration-provider[data-provider="merit_palk"]')
        import_button = card.get_by_role("button", name="Import data", exact=True)
        playwright.expect(import_button).to_be_disabled()
        card.get_by_role("button", name="Test connection", exact=True).click()
        page.locator('.dialog [name="api_id"]').fill("synthetic-id")
        page.locator('.dialog [name="api_key"]').fill("synthetic-key-1")
        page.locator('.dialog [data-action="testConnection"]').click()
        playwright.expect(import_button).to_be_enabled()
        page.locator('.dialog [data-close]').click()
        import_button.click()
        dialog = page.locator('.dialog')
        assert dialog.locator('[name="object_type"] option').count() == 5
        dialog.locator('[name="month"]').fill("2026-10")
        dialog.locator('[name="monthly_amounts"]').check()
        dialog.locator('[type="submit"]').click()
        playwright.expect(page.locator('#app-content h1')).to_have_text("Review employee import")
        page.locator('[data-decision="apply"]').check()
        page.get_by_role("button", name="Apply decisions", exact=True).click()
        playwright.expect(page.locator('.outcome-summary')).to_be_visible()
        page.get_by_role("link", name="Back to integrations", exact=True).first.click()
        import_button.click()
        dialog.locator('[name="object_type"]').select_option("vacation_balance")
        dialog.locator('[name="personal_code"]').fill("42")
        dialog.locator('[type="submit"]').click()
        playwright.expect(page.locator('#app-content')).to_contain_text("Display-only snapshot")
        playwright.expect(page.locator('[data-decision]')).to_have_count(0)
        playwright.expect(page.get_by_role("button", name="Apply decisions", exact=True)).to_be_disabled()
        page.get_by_text("View source record", exact=True).click()
        playwright.expect(page.locator('pre')).to_contain_text("DaysUnused")
        page.get_by_role("link", name="Back to integrations", exact=True).first.click()
        import_button.click()
        dialog.locator('[name="object_type"]').select_option("salary_hours")
        dialog.locator('[name="month"]').fill("2026-10")
        dialog.locator('[type="submit"]').click()
        playwright.expect(page.locator('#app-content')).to_contain_text("2026-10")
        playwright.expect(page.locator('#app-content')).to_contain_text("2400.13")
        page.locator('[data-decision="apply"]').check()
        page.get_by_role("button", name="Apply decisions", exact=True).click()
        playwright.expect(page.locator('.outcome-summary')).to_be_visible()
        page.locator('.app-nav[data-view="payroll"]').click()
        playwright.expect(page.locator('#app-content')).to_contain_text("2026-10")
        playwright.expect(page.locator('#app-content')).to_contain_text("Draft")
        assert not errors
        browser.close()
