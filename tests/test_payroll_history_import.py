from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from connectors.file_import import parse_payroll_history_file
from core_utils import money
from import_service import ImportService
from payroll import PayrollService
from payroll_absences import PayrollAbsenceService
from payroll_calendar import public_holidays

ACTOR = "owner@example.test"
PERSONAL_CODE = "49001010018"


def _stage_and_apply(db, organisation_id, object_type, content, filename):
    service = ImportService(db)
    sync = service.run_sync(
        organisation_id,
        "file_import",
        object_type,
        actor=ACTOR,
        credentials={"workbook_content": content},
        config={"filename": filename},
    )
    review = service.get_staged(organisation_id, sync_run_id=sync["id"])
    result = service.apply_staged(
        organisation_id,
        "file_import",
        sync["id"],
        {row["id"]: "apply" for row in review["records"]},
        actor=ACTOR,
    )
    return sync, review, result


def _employee(db, organisation_id):
    return PayrollService(db).save_employee(
        organisation_id,
        actor=ACTOR,
        name="Synthetic payroll import employee",
        personal_id=PERSONAL_CODE,
        gross_salary="2200",
        apply_tax_free_minimum=False,
    )


def test_csv_and_xlsx_parse_english_and_estonian_headers():
    csv_content = (
        "Isikukood;Puhkusepäevi aastas;Kehtiv alates;Saldo kuupäev;"
        "Põhipuhkuse algsaldo;Lisapuhkuse algsaldo\n"
        f"{PERSONAL_CODE};28;2026-01-01;2026-10-01;4,5;2\n"
    ).encode()
    rows = parse_payroll_history_file(csv_content, "payroll_opening_leave", "balances.csv")
    assert rows[0]["personal_code"] == PERSONAL_CODE
    assert rows[0]["days_per_year"] == "28"
    assert rows[0]["source_key"].startswith("file:")

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Personal code", "Month", "Wage total", "Unpaid absence calendar days"])
    sheet.append([PERSONAL_CODE, "2026-09", 2500.25, 2])
    content = BytesIO()
    workbook.save(content)
    parsed = parse_payroll_history_file(content.getvalue(), "historical_earnings", "history.xlsx")
    assert parsed[0]["earning_month"] == "2026-09"
    assert parsed[0]["wage_total"] == "2500.25"
    with pytest.raises(ValueError, match="malformed or unsupported"):
        parse_payroll_history_file(b"not an xlsx archive", "historical_earnings", "broken.xlsx")


def test_opening_leave_import_is_reviewed_scoped_and_idempotent(db, ee_org, uk_org):
    employee = _employee(db, ee_org["id"])
    from organisations import OrganisationService
    other = OrganisationService(db).create(
        name="Another synthetic payroll tenant", country_code="EE", entity_type="EE_OU", owner_email=ACTOR,
    )
    _employee(db, other["id"])
    content = (
        "personal code,days per year,effective date,cutover date,basic unused days,extended unused days\n"
        f"{PERSONAL_CODE},28,2026-01-01,2026-10-01,4.5,2\n"
    ).encode()
    sync, review, applied = _stage_and_apply(db, ee_org["id"], "payroll_opening_leave", content, "opening.csv")
    record = review["records"][0]
    assert record["matched_local_id"] == employee["id"]
    assert applied["applied"] == 1
    opening = db.one(
        "SELECT * FROM payroll_leave_openings WHERE organisation_id=? AND employee_id=?",
        (ee_org["id"], employee["id"]),
    )
    assert opening["unused_days"] == 4.5 and opening["extended_unused_days"] == 2
    assert opening["reviewed_by"] == ACTOR and opening["reviewed_at"]
    entitlement = db.one(
        "SELECT effective_from,days_per_year FROM payroll_leave_entitlements WHERE organisation_id=? AND employee_id=?",
        (ee_org["id"], employee["id"]),
    )
    assert entitlement["effective_from"] == "2026-01-01" and entitlement["days_per_year"] == 28
    assert db.scalar("SELECT COUNT(*) FROM payroll_leave_openings WHERE organisation_id=?", (other["id"],)) == 0

    _, _, repeated = _stage_and_apply(db, ee_org["id"], "payroll_opening_leave", content, "opening.csv")
    assert repeated["unchanged"] == 1
    assert db.scalar("SELECT COUNT(*) FROM payroll_leave_entitlements WHERE organisation_id=?", (ee_org["id"],)) == 1


def test_history_import_drives_november_leave_average_from_april_to_september(db, ee_org):
    employee = _employee(db, ee_org["id"])
    lines = ["personal code,month,wage total,unpaid absence calendar days"]
    lines.extend(f"{PERSONAL_CODE},2026-{month:02d},3000,2" for month in range(4, 10))
    content = ("\n".join(lines) + "\n").encode()
    _, review, result = _stage_and_apply(db, ee_org["id"], "historical_earnings", content, "history.csv")
    assert len(review["records"]) == result["applied"] == 6
    _, _, repeated = _stage_and_apply(db, ee_org["id"], "historical_earnings", content, "history.csv")
    assert repeated["unchanged"] == 6
    payroll = PayrollService(db)
    october = payroll.create_run(ee_org["id"], period="2026-10", actor=ACTOR)
    payroll.approve(ee_org["id"], october["id"], actor=ACTOR)
    absence_service = PayrollAbsenceService(db)
    absence = absence_service.save(
        ee_org["id"], employee["id"], actor=ACTOR, absence_type="annual_leave",
        start_date="2026-11-02", end_date="2026-11-03",
    )
    saved = absence_service.set_pay_method(ee_org["id"], absence["id"], "average", actor=ACTOR)
    average = saved["breakdown"]["average"]
    holidays = sum(date(2026, 4, 1) <= day <= date(2026, 9, 30) for day in public_holidays(2026))
    denominator = 183 - holidays - 12
    assert average["source_months"] == [f"2026-{month:02d}" for month in range(4, 10)]
    assert average["event_date"] == "2026-10-30"
    assert Decimal(average["wage_total"]) == Decimal("18000.00")
    assert average["unpaid_absence_days"] == 12
    assert Decimal(average["average_daily_pay"]) == money(Decimal("18000") / Decimal(denominator))
    assert average["historical_earning_count"] == 6


def test_import_errors_malformed_files_roles_csrf_and_tenant_scope(db, ee_org, monkeypatch):
    from api_app import User, api, current_user
    from organisations import OrganisationService
    from web_app import app

    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    OrganisationService(db).add_member(ee_org["id"], ACTOR, "viewer@example.test", "viewer")
    foreign_org = OrganisationService(db).create(
        name="Private synthetic payroll tenant", country_code="EE", entity_type="EE_OU",
        owner_email="foreign-owner@example.test",
    )
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    client = TestClient(app)
    url = f"/api/organisations/{ee_org['id']}/payroll/history-imports/historical_earnings"
    csv_content = b"personal code,month,wage total,unpaid absence calendar days\n"
    try:
        no_csrf = client.post(url, files={"file": ("history.csv", csv_content, "text/csv")})
        assert no_csrf.status_code == 403
        token = client.get("/api/csrf").json()["csrf_token"]
        headers = {"X-CSRF-Token": token}
        empty_sync = client.post(url, headers=headers, files={"file": ("history.csv", csv_content, "text/csv")})
        assert empty_sync.status_code == 201
        apply_url = f"/api/organisations/{ee_org['id']}/payroll/history-imports/{empty_sync.json()['id']}/apply"
        assert client.post(apply_url, json={"decisions": {}}).status_code == 403
        malformed = client.post(url, headers=headers, files={"file": ("history.csv", b"not a valid header\n", "text/csv")})
        assert malformed.status_code == 422
        wrong_extension = client.post(url, headers=headers, files={"file": ("history.txt", csv_content, "text/plain")})
        assert wrong_extension.status_code == 422
        foreign = client.post(
            f"/api/organisations/{foreign_org['id']}/payroll/history-imports/historical_earnings",
            headers=headers, files={"file": ("history.csv", csv_content, "text/csv")},
        )
        assert foreign.status_code == 403

        api.dependency_overrides[current_user] = lambda: User(email="viewer@example.test")
        denied = client.post(url, headers=headers, files={"file": ("history.csv", csv_content, "text/csv")})
        assert denied.status_code == 403
    finally:
        api.dependency_overrides.clear()


def test_row_level_errors_are_staged_for_review(db, ee_org):
    _employee(db, ee_org["id"])
    content = (
        "personal code,month,wage total,unpaid absence calendar days\n"
        f"{PERSONAL_CODE},2026-05,not-money,2\n"
        f"{PERSONAL_CODE},2026-06,2500,1,extra\n"
    ).encode()
    service = ImportService(db)
    sync = service.run_sync(
        ee_org["id"], "file_import", "historical_earnings", actor=ACTOR,
        credentials={"workbook_content": content}, config={"filename": "history.csv"},
    )
    rows = service.get_staged(ee_org["id"], sync_run_id=sync["id"])["records"]
    assert len(rows) == 2 and all(row["matched_local_id"] for row in rows)
    assert all(row["review_note"] for row in rows)
    outcomes = service.apply_staged(
        ee_org["id"], "file_import", sync["id"], {row["id"]: "apply" for row in rows}, actor=ACTOR,
    )
    assert outcomes["failed"] == 2
    assert db.scalar("SELECT COUNT(*) FROM payroll_historical_earnings WHERE organisation_id=?", (ee_org["id"],)) == 0
