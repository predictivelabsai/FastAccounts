from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tsd_apa_history import APAHistoryService
from tsd_apa_xml import generate_apa_xml, transaction_id

FIXTURES = Path(__file__).parent / "fixtures" / "emta"
ORG = {"id":"org-demo", "registration_no":"12345678"}
PAYOUT = {"id":"payout-demo", "payout_date":"2026-10-20"}
RECORD = {"tsd_payment_type":10,"gross_amount":Decimal("100.00"),"tax_free_minimum":Decimal("0"),
          "social_tax_base":Decimal("100"),"social_tax":Decimal("33"),"funded_pension":Decimal("0"),
          "employee_unemployment_insurance":Decimal("0"),"employer_unemployment_insurance":Decimal("0"),
          "income_tax":Decimal("0"),"recipient_personal_id":"49001010018"}


def test_export_history_hash_idempotency_correction_and_cancellation(db, ee_org):
    service = APAHistoryService(db)
    organisation = {"id":ee_org["id"],"registration_no":ee_org["registration_no"]}
    payout = {**PAYOUT,"id":"history-payout"}
    row, first = service.export_version(ee_org["id"], payout, [RECORD], actor="owner@example.test")
    repeated, same = service.export_version(ee_org["id"], payout, [RECORD], actor="owner@example.test")
    assert row["id"] == repeated["id"] and first == same
    assert row["transaction_id"] == transaction_id(ee_org["id"], payout["id"], 1)
    assert row["file_sha256"] == sha256(first).hexdigest()
    changed = {**RECORD,"gross_amount":Decimal("125.00")}
    second, second_xml = service.export_version(ee_org["id"], payout, [changed], actor="owner@example.test")
    assert second["version"] == 2 and second["transaction_id"] == transaction_id(ee_org["id"], payout["id"], 2)
    assert second["operation"] == "M"
    operation_ids = ET.fromstring(second_xml).findall(".//{http://www.xbrl.org/int/gl/cor/2015-03-25}accountSubID")
    assert [node.text for node in operation_ids][-1] == "M"
    assert second_xml != first
    ns = {"cor":"http://www.xbrl.org/int/gl/cor/2015-03-25"}
    cancellation = service.cancellation(ee_org["id"], second["id"], actor="owner@example.test")
    assert cancellation == service._cancellation_xml(ET.fromstring(second_xml),second["transaction_id"],ns)
    root = ET.fromstring(cancellation)
    assert root.findtext(".//cor:uniqueID",namespaces=ns) == second["transaction_id"]
    detail = root.find(".//cor:entryDetail",ns)
    assert detail.findtext("cor:lineNumber",namespaces=ns) == f"{payout['id']}-1"
    assert detail.findtext("cor:lineNumberCounter",namespaces=ns) == "1"
    assert detail.findtext("cor:account/cor:accountSub/cor:accountSubID",namespaces=ns) == "T"
    sample = ET.parse(FIXTURES / "APA_TSD_lahteandmed_ariuhingule_naide_tuhistamine_XML_20251017.xml").getroot()
    assert root.tag == sample.tag
    assert [node.tag for node in root] == [node.tag for node in sample]
    assert [node.tag for node in root.find(".//{http://www.xbrl.org/int/gl/cor/2015-03-25}entryHeader")] == [
        node.tag for node in sample.find(".//{http://www.xbrl.org/int/gl/cor/2015-03-25}entryHeader")]
    with pytest.raises(ValueError,match="already cancelled"):
        service.cancellation(ee_org["id"], second["id"], actor="owner@example.test")
    assert db.one("SELECT status FROM tsd_apa_exports WHERE organisation_id=? AND id=?",(ee_org["id"],second["id"]))["status"] == "Cancelled"
    assert db.scalar("SELECT COUNT(*) FROM tsd_apa_export_cancellations WHERE organisation_id=? AND export_id=?",
                     (ee_org["id"], second["id"])) == 1
    third, third_xml = service.export_version(ee_org["id"], payout,
        [{**changed, "gross_amount": Decimal("130.00")}], actor="owner@example.test")
    assert third["version"] == 3 and third["operation"] == "R"
    root = ET.fromstring(third_xml)
    assert root.findtext(".//{http://www.xbrl.org/int/gl/cor/2015-03-25}lineNumber") == f"{payout['id']}-v3-1"


@pytest.mark.parametrize(("fixture","status"),[
    ("APA_TSD_20260330_tagasisideraport_kinnitamine_ok.xml","Accepted"),
    ("APA_TSD_20260330_tagasisideraport_kinnitamine_error.xml","Rejected"),
    ("APA_TSD_20260330_tagasisideraport_osaliselt_vigadega.xml","PartiallyRejected"),
    ("APA_TSD_20260330_tagasisideraport_faili_enda_veaga.xml","Rejected"),
])
def test_feedback_import_parses_all_emta_examples_and_unmatched_ids(db, ee_org, fixture, status):
    service = APAHistoryService(db)
    payload = generate_apa_xml({"id":ee_org["id"],"registration_no":ee_org["registration_no"]}, PAYOUT, [RECORD])
    txid = transaction_id(ee_org["id"], PAYOUT["id"])
    export = service.record_export(ee_org["id"], PAYOUT["id"], txid, 1, payload, actor="owner@example.test")
    report = (FIXTURES / fixture).read_bytes()
    result = service.import_feedback(ee_org["id"], txid, report, actor="owner@example.test")
    assert result["matched"] and result["status"] == status
    assert result["messages"]
    assert db.one("SELECT status FROM tsd_apa_exports WHERE organisation_id=? AND id=?",(ee_org["id"],export["id"]))["status"] == status
    unknown = service.import_feedback(ee_org["id"], "unseen-transaction", report, actor="owner@example.test")
    assert unknown["matched"] is False and unknown["status"] == "Unmatched"
    other = __import__("organisations").OrganisationService(db).create(name="Other history tenant",country_code="EE",
        entity_type="EE_OU",owner_email="other@example.test")
    assert service.exports(other["id"]) == []
    assert service.feedback_results(other["id"],export["id"]) == []


def test_history_feedback_routes_enforce_roles_tenants_and_csrf(db, ee_org, monkeypatch):
    from fastapi.testclient import TestClient
    from api_app import api, current_user, User
    from web_app import app
    from organisations import OrganisationService

    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    service = APAHistoryService(db)
    payload = generate_apa_xml({"id":ee_org["id"],"registration_no":ee_org["registration_no"]}, PAYOUT, [RECORD])
    txid = transaction_id(ee_org["id"], PAYOUT["id"])
    export = service.record_export(ee_org["id"], PAYOUT["id"], txid, 1, payload, actor="owner@example.test")
    (tmp_file := FIXTURES / "APA_TSD_20260330_tagasisideraport_kinnitamine_ok.xml")
    current = {"email":"viewer@example.test"}
    api.dependency_overrides[current_user] = lambda: User(email=current["email"])
    client = TestClient(app)
    url = f"/api/organisations/{ee_org['id']}/payroll/tsd-apa/feedback"
    other = OrganisationService(db).create(name="Other route tenant",country_code="EE",entity_type="EE_OU",
                                            owner_email="other@example.test")
    try:
        with db.transaction() as tx:
            tx.execute("INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES ('apa-viewer',?,'viewer@example.test','viewer','2026-10-01')",(ee_org["id"],))
        report = tmp_file.read_bytes()
        assert client.post(url,data={"transaction_id":txid},files={"file":("feedback.xml",report,"application/xml")}).status_code == 403
        token = client.get("/api/csrf").json()["csrf_token"]
        assert client.post(url,data={"transaction_id":txid},files={"file":("feedback.xml",report,"application/xml")},headers={"X-CSRF-Token":token}).status_code == 403
        assert client.get(f"/api/organisations/{ee_org['id']}/payroll/tsd-apa/history",headers={"X-CSRF-Token":token}).status_code == 200
        current["email"] = "owner@example.test"
        assert client.get("/api/csrf").status_code == 200
        token = client.get("/api/csrf").json()["csrf_token"]
        response = client.post(url,data={"transaction_id":txid},files={"file":("feedback.xml",report,"application/xml")},headers={"X-CSRF-Token":token})
        assert response.status_code == 200, response.text
        assert response.json()["matched"] is True
        cancel_payout = {**PAYOUT,"id":"route-cancel-payout"}
        cancel_txid = transaction_id(ee_org["id"], cancel_payout["id"])
        cancel_export = service.record_export(ee_org["id"], cancel_payout["id"], cancel_txid, 1,
            generate_apa_xml({"id":ee_org["id"],"registration_no":ee_org["registration_no"]},cancel_payout,[RECORD]),
            actor="owner@example.test")
        cancel_url = f"/api/organisations/{ee_org['id']}/payroll/tsd-apa/history/{cancel_export['id']}/cancellation.xml"
        assert client.post(cancel_url).status_code == 403
        cancelled = client.post(cancel_url,headers={"X-CSRF-Token":token})
        assert cancelled.status_code == 200 and ET.fromstring(cancelled.content).tag.endswith("}xbrl")
        assert client.get(f"/api/organisations/{other['id']}/payroll/tsd-apa/history",headers={"X-CSRF-Token":token}).status_code == 403
        assert client.get(f"/api/organisations/{ee_org['id']}/payroll/tsd-apa/history/{export['id']}/feedback").status_code == 200
    finally:
        api.dependency_overrides.clear()
