from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from tsd_apa_xml import amount, generate_apa_xml, transaction_id

EXAMPLE = Path(__file__).parent / "fixtures" / "emta" / "APA_TSD_lahteandmed_ariuhingule_naide_XML_20251017.xml"
ORG = {"id": "org-1", "registration_no": "12345678"}
PAYOUT = {"id": "payout-1", "payout_date": "2026-10-31"}
RECORD = {
    "tsd_payment_type": 10,
    "gross_amount": Decimal("1234.5"),
    "tax_free_minimum": Decimal("100"),
    "social_tax_base": Decimal("1234.5"),
    "social_tax": Decimal("407.39"),
    "funded_pension": Decimal("24.69"),
    "employee_unemployment_insurance": Decimal("19.75"),
    "employer_unemployment_insurance": Decimal("9.88"),
    "income_tax": Decimal("238.64"),
    "recipient_personal_id": "49001010018",
}


def test_apa_document_matches_example_skeleton_namespaces_and_codes():
    sample = ET.parse(EXAMPLE).getroot()
    output_bytes = generate_apa_xml(ORG, PAYOUT, [RECORD])
    output = ET.fromstring(output_bytes)
    assert output.tag == sample.tag
    assert [node.tag for node in list(output)] == [node.tag for node in list(sample)]
    sample_ns = {event[1] for event in ET.iterparse(EXAMPLE, events=("start-ns",))}
    output_ns = {event[1] for event in ET.iterparse(__import__("io").BytesIO(output_bytes), events=("start-ns",))}
    assert output_ns == sample_ns

    ns = {"x": "http://www.xbrl.org/2003/instance",
          "cor": "http://www.xbrl.org/int/gl/cor/2015-03-25",
          "bus": "http://www.xbrl.org/int/gl/bus/2015-03-25"}
    required = (
        ".//cor:documentInfo/cor:entriesType", ".//cor:documentInfo/cor:uniqueID",
        ".//cor:documentInfo/cor:language", ".//cor:documentInfo/cor:creationDate",
        ".//cor:periodCoveredStart", ".//cor:periodCoveredEnd",
        ".//bus:organizationIdentifier", ".//bus:organizationDescription",
        ".//cor:entryNumber", ".//cor:lineNumberCounter", ".//cor:accountSubID",
        ".//cor:accountSubType", ".//cor:amount", ".//cor:identifierCode",
        ".//cor:identifierDescription", ".//cor:documentDate",
    )
    assert all(output.find(path, ns) is not None for path in required)
    codes = {node.text for node in output.findall(".//cor:accountSub/cor:accountSubType", ns)}
    assert codes == {"VALJAMLIIK2023ap", "TOIMINGUTYYP2023ap"}
    assert {node.text for node in output.findall(".//cor:taxCode", ns)} == {
        "TSD_SM", "TSD_KP", "TSD_TK", "TSD_TTK", "TSD_KTM"
    }
    assert output.findtext(".//bus:measurableDescription", namespaces=ns) == "MVT_610"


def test_apa_output_is_deterministic_and_one_document_per_payout():
    first = generate_apa_xml(ORG, PAYOUT, [RECORD])
    assert first == generate_apa_xml(ORG, PAYOUT, [RECORD])
    another_payout = {"id": "payout-2", "payout_date": PAYOUT["payout_date"]}
    second = generate_apa_xml(ORG, another_payout, [RECORD])
    assert first != second
    assert transaction_id(ORG["id"], PAYOUT["id"]) in first.decode()
    assert transaction_id(ORG["id"], another_payout["id"]) in second.decode()
    assert amount(Decimal("1.2")) == "1.20"
    assert amount(Decimal("0.01")) == "0.01"


def test_apa_routes_require_role_and_tenant_and_zip_one_file_per_payout(db, ee_org, legacy_payroll, monkeypatch):
    from fastapi.testclient import TestClient
    from api_app import api
    from organisations import OrganisationService
    from payroll_payouts import PayoutService
    from tsd import TSDExportService
    from test_tsd_export import _approved_run

    run = _approved_run(db, ee_org)
    accounts = db.rows("SELECT id FROM accounts WHERE organisation_id=? AND account_type='Asset' AND active=1 ORDER BY code LIMIT 1", (ee_org["id"],))
    with db.transaction() as tx:
        tx.execute("INSERT INTO bank_accounts(id,organisation_id,ledger_account_id,name,currency,iban_masked,iban,bic) VALUES ('apa-bank',?,?,?,'EUR','********5685','EE382200221020145685','HABAEE2X')",
                   (ee_org["id"], accounts[0]["id"], "APA bank"))
    payouts = PayoutService(db)
    half_amounts = {item["employee_id"]: str(Decimal(item["net"]) / 2) for item in run["items"]}
    payout = payouts.create(ee_org["id"], run["id"], actor="owner@example.test",
                            bank_account_id="apa-bank", amounts=half_amounts)
    payouts.mark_paid(ee_org["id"], payout["id"], "apa-bank", actor="owner@example.test")
    second_payout = payouts.create(ee_org["id"], run["id"], actor="owner@example.test", bank_account_id="apa-bank")
    payouts.mark_paid(ee_org["id"], second_payout["id"], "apa-bank", actor="owner@example.test")
    prep = TSDExportService(db).prepare(ee_org["id"], run["id"], actor="owner@example.test")
    TSDExportService(db).review(ee_org["id"], prep["id"], actor="owner@example.test")
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    client = TestClient(api)
    base = f"/organisations/{ee_org['id']}/pay-runs/{run['id']}/tsd/{prep['id']}"
    assert client.get(base + f"/payouts/{payout['id']}/apa.xml", headers={"X-Test-User": "outsider@example.test"}).status_code == 403
    xml = client.get(base + f"/payouts/{payout['id']}/apa.xml", headers={"X-Test-User": "owner@example.test"})
    repeated_xml = client.get(base + f"/payouts/{payout['id']}/apa.xml", headers={"X-Test-User": "owner@example.test"})
    zipped = client.get(f"/organisations/{ee_org['id']}/payroll/tsd-apa/2026-10.zip",
                        headers={"X-Test-User": "owner@example.test"})
    assert xml.status_code == 200 and ET.fromstring(xml.content).tag.endswith("}xbrl")
    assert repeated_xml.content == xml.content
    history = db.rows("SELECT version,transaction_id,file_sha256,status FROM tsd_apa_exports WHERE organisation_id=? AND payout_id=?",
                      (ee_org["id"], payout["id"]))
    assert len(history) == 1 and history[0]["version"] == 1 and history[0]["status"] == "Exported"
    assert history[0]["transaction_id"] in xml.text and len(history[0]["file_sha256"]) == 64
    assert zipped.status_code == 200
    from zipfile import ZipFile
    import io
    with ZipFile(io.BytesIO(zipped.content)) as archive:
        assert len(archive.namelist()) == 2
        assert ET.fromstring(archive.read(archive.namelist()[0])).tag.endswith("}xbrl")
    other = OrganisationService(db).create(name="Other EE", country_code="EE", entity_type="EE_OU", owner_email="other@example.test")
    tenant_url = f"/organisations/{other['id']}/payroll/tsd-apa/2026-10.zip"
    assert client.get(tenant_url, headers={"X-Test-User": "owner@example.test"}).status_code == 403


def test_apa_export_contains_one_paid_absence_payout(db, ee_org):
    from payroll import PayrollService
    from payroll_absences import PayrollAbsenceService
    from payroll_absence_payouts import AbsencePayoutService
    from payroll_payday import PaydaySettingsService
    from tsd import TSDExportService

    actor = "owner@example.test"
    payroll = PayrollService(db)
    employee = payroll.save_employee(ee_org["id"], actor=actor, name="Absence recipient",
                                     personal_id="49001010018", gross_salary="2000")
    PaydaySettingsService(db).save(ee_org["id"], start_date="2026-01-01", rule_start_date="2026-01-01",
                                   rule="next_month_day", day=10, actor=actor)
    run = payroll.create_run(ee_org["id"], period="2026-10", actor=actor)
    payroll.approve(ee_org["id"], run["id"], actor=actor)
    absence_service = PayrollAbsenceService(db)
    absence = absence_service.save(ee_org["id"], employee["id"], actor=actor, absence_type="annual_leave",
                                   start_date="2026-11-23", end_date="2026-11-27")
    snapshot = absence_service.set_pay_method(ee_org["id"], absence["id"], "fixed_sum", actor=actor, fixed_amount="275")
    payout_service = AbsencePayoutService(db)
    payout = payout_service.create(ee_org["id"], [snapshot["id"]], actor=actor)
    payout_service.approve(ee_org["id"], payout["id"], actor=actor)
    asset = db.one("SELECT id FROM accounts WHERE organisation_id=? AND account_type='Asset' AND active=1 ORDER BY code LIMIT 1", (ee_org["id"],))
    with db.transaction() as tx:
        tx.execute("INSERT INTO bank_accounts(id,organisation_id,ledger_account_id,name,currency) VALUES ('apa-absence-bank',?,?,?,'EUR')",
                   (ee_org["id"], asset["id"], "Absence bank"))
    payout_service.paid(ee_org["id"], payout["id"], "apa-absence-bank", actor=actor)
    tsd = TSDExportService(db)
    preparation = tsd.prepare(ee_org["id"], run["id"], actor=actor)
    tsd.review(ee_org["id"], preparation["id"], actor=actor)
    xml = tsd.export_apa_payout(ee_org["id"], preparation["id"], payout["id"], actor=actor)
    root = ET.fromstring(xml)
    assert root.findtext(".//{http://www.xbrl.org/int/gl/cor/2015-03-25}documentDate") == "2026-11-20"
    assert root.findtext(".//{http://www.xbrl.org/int/gl/cor/2015-03-25}amount") == "275.00"
    archive = tsd.export_apa_month_zip(ee_org["id"], "2026-11", actor=actor)
    from zipfile import ZipFile
    import io
    with ZipFile(io.BytesIO(archive)) as files:
        assert len(files.namelist()) == 1
        assert payout["id"] in files.namelist()[0]
