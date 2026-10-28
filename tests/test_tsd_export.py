from __future__ import annotations

import csv
import io
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from connectors.providers import EMTATSDExportProvider
from payroll import PayrollService
from tsd import (
    TSD_AMOUNT_FIELDS,
    TSD_NS,
    TSD_PAYMENT_FIELDS,
    TSDExportService,
    XBRL_GL_CORE_NS,
)


ACTOR = "owner@example.test"


def _approved_run(db, organisation):
    payroll = PayrollService(db)
    first = payroll.save_employee(
        organisation["id"], actor=ACTOR, name="Ada Arvutaja",
        personal_id="49001010018", gross_salary="2000",
        apply_tax_free_minimum=True,
    )
    payroll.save_employee(
        organisation["id"], actor=ACTOR, name="Bert Juhatuse liige",
        personal_id="38002020029", gross_salary="500", board_member=True,
    )
    run = payroll.create_run(organisation["id"], period="2026-10", actor=ACTOR)
    payroll.save_employee(
        organisation["id"], employee_id=first["id"], actor=ACTOR,
        personal_id="59912319999",
    )
    return payroll.approve(organisation["id"], run["id"], actor=ACTOR)


def _reviewed_preparation(db, organisation):
    run = _approved_run(db, organisation)
    service = TSDExportService(db)
    preparation = service.prepare(organisation["id"], run["id"], actor=ACTOR)
    assert preparation["status"] == "Review Required"
    with pytest.raises(ValueError, match="review"):
        service.export_xbrl_gl(organisation["id"], preparation["id"], actor=ACTOR)
    service.review(organisation["id"], preparation["id"], actor=ACTOR)
    return service, run, preparation


def test_xbrl_gl_has_one_complete_transaction_per_payment_and_reconciles(db, ee_org):
    service, run, preparation = _reviewed_preparation(db, ee_org)
    payload = service.export_xbrl_gl(ee_org["id"], preparation["id"], actor=ACTOR)
    root = ET.fromstring(payload)
    ns = {"gl": XBRL_GL_CORE_NS, "tsd": TSD_NS}
    headers = root.findall(".//gl:entryHeader", ns)
    assert len(headers) == len(run["items"]) == 2
    details = [header.find("gl:entryDetail", ns) for header in headers]
    assert all(detail is not None for detail in details)
    for detail in details:
        assert all(detail.find(f"tsd:{field}", ns) is not None for field in TSD_PAYMENT_FIELDS)
        assert detail.findtext("tsd:currency", namespaces=ns) == "EUR"
        assert detail.findtext("tsd:payment_date", namespaces=ns) == "2026-10-31"
        assert detail.findtext("tsd:filing_deadline", namespaces=ns) == "2026-11-10"
        assert detail.findtext("tsd:annex", namespaces=ns) == "1"
    personal_ids = {detail.findtext("tsd:recipient_personal_id", namespaces=ns) for detail in details}
    assert personal_ids == {"49001010018", "38002020029"}
    totals = {
        field: sum(
            (Decimal(detail.findtext(f"tsd:{field}", namespaces=ns)) for detail in details),
            Decimal("0"),
        )
        for field in TSD_AMOUNT_FIELDS
    }
    assert totals["gross_amount"] == Decimal(run["total_gross"])
    assert totals["net_amount"] == Decimal(run["total_net"])
    assert totals["employer_cost"] == Decimal(run["total_employer_cost"])
    assert root.findtext(".//tsd:annexScope", namespaces=ns) == "1-2"
    assert root.findtext(".//tsd:validationStatus", namespaces=ns) == "NOT_LIVE_VERIFIED_AGAINST_EMTA"


def test_transitional_csv_has_declared_fields_and_reconciles(db, ee_org):
    service, run, preparation = _reviewed_preparation(db, ee_org)
    payload = service.export_csv(ee_org["id"], preparation["id"], actor=ACTOR)
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    assert tuple(rows[0]) == TSD_PAYMENT_FIELDS
    assert len(rows) == len(run["items"])
    assert {row["payment_classification"] for row in rows} == {
        "EMPLOYMENT_SALARY", "BOARD_MEMBER_FEE"
    }
    assert sum((Decimal(row["gross_amount"]) for row in rows), Decimal("0")) == Decimal(run["total_gross"])
    assert sum((Decimal(row["net_amount"]) for row in rows), Decimal("0")) == Decimal(run["total_net"])
    assert sum((Decimal(row["employer_cost"]) for row in rows), Decimal("0")) == Decimal(run["total_employer_cost"])
    sync = db.one(
        "SELECT * FROM sync_runs WHERE organisation_id=? AND id=?",
        (ee_org["id"], preparation["id"]),
    )
    assert sync["direction"] == "export" and sync["object_type"] == "tsd"
    assert sync["status"] == "Completed" and sync["write_count"] == 2


def test_tsd_scope_confirmation_and_tenant_gates(db, ee_org, uk_org):
    service = TSDExportService(db)
    with pytest.raises(ValueError, match="Estonian"):
        service.prepare(uk_org["id"], "missing", actor=ACTOR)
    payroll = PayrollService(db)
    payroll.save_employee(
        ee_org["id"], actor=ACTOR, name="No identifier", gross_salary="2000"
    )
    draft = payroll.create_run(ee_org["id"], period="2026-10", actor=ACTOR)
    with pytest.raises(ValueError, match="approved"):
        service.prepare(ee_org["id"], draft["id"], actor=ACTOR)
    approved = payroll.approve(ee_org["id"], draft["id"], actor=ACTOR)
    with pytest.raises(ValueError, match="personal ID"):
        service.prepare(ee_org["id"], approved["id"], actor=ACTOR)


def test_tsd_api_review_gate_and_file_downloads(db, ee_org, monkeypatch):
    run = _approved_run(db, ee_org)
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    from api_app import api

    client = TestClient(api)
    headers = {"X-Test-User": ACTOR}
    base = f"/organisations/{ee_org['id']}/pay-runs/{run['id']}/tsd"
    prepared = client.post(base + "/prepare", headers=headers)
    assert prepared.status_code == 200, prepared.text
    preparation_id = prepared.json()["id"]
    assert client.get(base + f"/{preparation_id}/export.xbrl.xml", headers=headers).status_code == 422
    reviewed = client.post(base + f"/{preparation_id}/review", headers=headers)
    assert reviewed.status_code == 200, reviewed.text
    xml = client.get(base + f"/{preparation_id}/export.xbrl.xml", headers=headers)
    csv_response = client.get(base + f"/{preparation_id}/export.csv", headers=headers)
    assert xml.status_code == 200 and xml.content.startswith(b"<?xml")
    assert xml.headers["content-disposition"].endswith('tsd-2026-10.xbrl.xml"')
    assert csv_response.status_code == 200
    assert csv_response.content.startswith(b"\xef\xbb\xbfdeclaration,")


def test_tsd_provider_is_export_only():
    with pytest.raises(PermissionError, match="direct TSD filing is not enabled"):
        EMTATSDExportProvider().submit({"declaration": "TSD"})


def test_services_contract_income_line_can_prepare_and_export(db, ee_org):
    payroll = PayrollService(db)
    payroll.save_employee(ee_org["id"], actor=ACTOR, name="Contractor Test",
                          personal_id="49001010018", pay_basis="income_line")
    run = payroll.create_run(ee_org["id"], period="2026-10", actor=ACTOR)
    kind = next(t for t in payroll.component_types(ee_org["id"]) if t["preset_key"] == "contract")
    payroll.update_item(ee_org["id"], run["id"], run["items"][0]["id"], actor=ACTOR,
                        components=[{"type_id": kind["id"], "amount": "2000"}])
    payroll.approve(ee_org["id"], run["id"], actor=ACTOR)
    service = TSDExportService(db)
    prepared = service.prepare(ee_org["id"], run["id"], actor=ACTOR)
    assert prepared["records"][0]["payment_classification"] == "CONTRACTOR_FEE"
    service.review(ee_org["id"], prepared["id"], actor=ACTOR)
    rows = list(csv.DictReader(io.StringIO(service.export_csv(
        ee_org["id"], prepared["id"], actor=ACTOR).decode("utf-8-sig"))))
    assert rows[0]["pay_basis"] == "income_line"
    assert rows[0]["gross_amount"] == "2000.00"
    root = ET.fromstring(service.export_xbrl_gl(ee_org["id"], prepared["id"], actor=ACTOR))
    assert root.findtext(".//{*}payment_classification") == "CONTRACTOR_FEE"
