"""Organisation-scoped e-invoice routes and atomic draft purchase intake."""
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from core_utils import new_id
from database import reset_database_cache
from documents import DocumentService
from einvoice import parse_purchase
from einvoice import e_arve_xml


ACTOR = "owner@example.test"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    monkeypatch.setenv("FASTACCOUNTS_DATA_DIR", str(tmp_path / "evidence"))
    reset_database_cache()
    from api_app import api
    with TestClient(api, headers={"X-Test-User": ACTOR}) as client:
        yield client
    reset_database_cache()


def purchase():
    return (FIXTURES / "einvoicing_purchase.xml").read_bytes()


def upload(client, org, content=None, **kwargs):
    return client.post(f"/organisations/{org['id']}/e-invoices/import",
                       files={"file": ("purchase.xml", content if content is not None else purchase(), "application/xml")}, **kwargs)


def sale(db, org):
    docs = DocumentService(db)
    contact = docs.create_contact(org["id"], name="Synthetic customer", country_code="EE", registration_no="87654321")
    account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (org["id"],))
    tax = db.scalar("SELECT id FROM tax_codes WHERE organisation_id=? AND kind='standard'", (org["id"],))
    return docs.create_invoice(org["id"], contact_id=contact["id"], issue_date="2026-10-01", actor=ACTOR,
                               lines=[dict(description="Synthetic service", quantity="2", unit_price="50", account_id=account, tax_code_id=tax)])


def test_xml_route_gate_issued_and_tenancy(client, db, ee_org, uk_org):
    invoice = sale(db, ee_org)
    path = f"/organisations/{ee_org['id']}/invoices/{invoice['id']}.xml"
    assert client.get(path).status_code == 422
    assert "Only issued" in client.get(path).json()["detail"]
    docs = DocumentService(db)
    docs.create_bank_account(ee_org["id"], name="Synthetic bank", currency="EUR", iban="EE382200221020145685")
    issued = docs.issue_invoice(invoice["id"], actor=ACTOR)
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    parsed = parse_purchase(response.content)
    assert parsed["invoice_number"] == issued["number"]
    assert parsed["totals"]["gross"] == Decimal("124.00")
    assert ET.fromstring(response.content).findtext(".//PayToAccount") == "EE382200221020145685"
    assert client.get(f"/organisations/{uk_org['id']}/invoices/{invoice['id']}.xml").status_code == 404
    for status in ("Part Paid", "Paid"):
        with db.transaction() as tx:
            tx.execute("UPDATE invoices SET status=? WHERE id=?", (status, invoice["id"]))
        assert client.get(path).status_code == 200


def test_uk_xml_stays_generic(client, db, uk_org):
    invoice = sale(db, uk_org)
    DocumentService(db).issue_invoice(invoice["id"], actor=ACTOR)
    response = client.get(f"/organisations/{uk_org['id']}/invoices/{invoice['id']}.xml")
    assert response.status_code == 200
    assert ET.fromstring(response.content).tag == "FastAccountsInvoice"
    assert ET.fromstring(DocumentService(db).invoice_xml(invoice["id"])).tag == "FastAccountsInvoice"


def test_import_draft_supplier_tax_evidence_and_duplicate(client, db, ee_org):
    original = purchase()
    parsed = parse_purchase(original)
    before = db.scalar("SELECT COUNT(*) FROM gl_entries")
    response = upload(client, ee_org)
    assert response.status_code == 201, response.text
    result = response.json()
    assert set(result) == {"bill_id", "supplier", "total", "warnings"}
    assert result["warnings"] == [] and result["supplier"] == parsed["seller"]["name"]
    assert Decimal(result["total"]) == parsed["totals"]["gross"]
    bill = DocumentService(db).bill(result["bill_id"])
    assert bill["status"] == "Draft" and bill["posting_batch_id"] is None
    assert bill["supplier_number"] == parsed["invoice_number"]
    assert bill["reference"] == parsed["buyer_reference"]
    assert bill["notes"] == f"Imported from e-invoice {parsed['invoice_number']}"
    supplier = db.one("SELECT * FROM contacts WHERE id=?", (bill["contact_id"],))
    assert supplier["contact_type"] == "supplier"
    assert supplier["registration_no"] == parsed["seller"]["registration_no"]
    for line, item in zip(bill["lines"], parsed["items"]):
        code = db.one("SELECT * FROM tax_codes WHERE id=?", (line["tax_code_id"],))
        assert code["organisation_id"] == ee_org["id"]
        assert Decimal(str(code["rate"])) == item["vat_rate"]
    evidence = DocumentService(db).attachments(ee_org["id"], owner_type="bill", owner_id=bill["id"])
    assert len(evidence) == 1 and evidence[0]["filename"] == "purchase.xml"
    assert DocumentService(db).evidence_download(ee_org["id"], evidence[0]["id"])[1] == original
    assert db.scalar("SELECT COUNT(*) FROM gl_entries") == before
    duplicate = upload(client, ee_org)
    assert duplicate.status_code == 409 and "already imported" in duplicate.json()["detail"]
    assert db.scalar("SELECT COUNT(*) FROM contacts WHERE organisation_id=?", (ee_org["id"],)) == 1
    assert db.scalar("SELECT COUNT(*) FROM bills") == 1
    assert db.scalar("SELECT COUNT(*) FROM attachments") == 1


def test_import_reuses_registry_match_ignores_other_tenants_and_customers(client, db, ee_org, uk_org):
    seller = parse_purchase(purchase())["seller"]
    docs = DocumentService(db)
    foreign = docs.create_contact(uk_org["id"], name="Foreign contact", country_code="EE", registration_no=seller["registration_no"], contact_type="supplier")
    customer = docs.create_contact(ee_org["id"], name="Customer only", country_code="EE", registration_no=seller["registration_no"], contact_type="customer")
    first = upload(client, ee_org)
    assert first.status_code == 201
    contact_id = docs.bill(first.json()["bill_id"])["contact_id"]
    assert contact_id not in {foreign["id"], customer["id"]}
    with db.transaction() as tx:
        tx.execute("UPDATE contacts SET name='Existing supplier name' WHERE id=?", (contact_id,))
    root = ET.fromstring(purchase())
    document = root.find("{*}Invoice") if root.tag.split("}")[-1] == "E_Invoice" else root
    document.set("invoiceId", "SECOND-001")
    document.find("{*}InvoiceInformation/{*}InvoiceNumber").text = "SECOND-001"
    second = upload(client, ee_org, ET.tostring(root))
    assert second.status_code == 201, second.text
    assert second.json()["supplier"] == "Existing supplier name"
    assert docs.bill(second.json()["bill_id"])["contact_id"] == contact_id


@pytest.mark.parametrize("content", [b"garbage", b"<html/>", b"<E_Invoice/>"])
def test_invalid_xml_is_400_and_no_side_effects(client, db, ee_org, content):
    response = upload(client, ee_org, content)
    assert response.status_code == 400
    for table in ("contacts", "bills", "attachments"):
        assert db.scalar(f"SELECT COUNT(*) FROM {table}") == 0


def test_mismatched_declaration_is_400(client, db, ee_org):
    root = ET.fromstring(purchase())
    root.find(".//{*}InvoiceSumGroup/{*}TotalSum").text = "99999.99"
    response = upload(client, ee_org, ET.tostring(root))
    assert response.status_code == 400 and "difference" in response.json()["detail"]
    assert db.scalar("SELECT COUNT(*) FROM bills") == 0


def test_unknown_rates_and_zero_rate(client, db, ee_org):
    with db.transaction() as tx:
        tx.execute("UPDATE tax_codes SET active=0 WHERE organisation_id=? AND rate>0", (ee_org["id"],))
    response = upload(client, ee_org)
    assert response.status_code == 400 and "Unknown VAT rates:" in response.json()["detail"]
    assert db.scalar("SELECT COUNT(*) FROM contacts") == 0
    # A foreign seller at zero VAT is accepted by numeric tax mapping.
    root = ET.fromstring(purchase())
    doc = root.find("{*}Invoice")
    for entry in doc.findall("{*}InvoiceItem/{*}InvoiceItemGroup/{*}ItemEntry"):
        net = entry.findtext("{*}ItemSum")
        for tag, value in (("VATRate", "0"), ("VATSum", "0"), ("SumAfterVAT", net)):
            entry.find("{*}VAT/{*}" + tag).text = value
        entry.find("{*}ItemTotalSum").text = net
    summary = doc.find("{*}InvoiceSumGroup")
    for vat in summary.findall("{*}VAT"):
        summary.remove(vat)
    summary.find("{*}TotalVATSum").text = "0.00"
    summary.find("{*}TotalSum").text = summary.findtext("{*}InvoiceSum")
    payment = doc.find("{*}PaymentInfo")
    if payment is not None:
        doc.remove(payment)
    response = upload(client, ee_org, ET.tostring(root))
    assert response.status_code == 201, response.text
    assert all(line["tax_rate"] == 0 for line in DocumentService(db).bill(response.json()["bill_id"])["lines"])


def test_evidence_failure_rolls_back_supplier_bill_and_file(client, db, ee_org, monkeypatch, tmp_path):
    import documents
    real_audit = documents.audit

    def fail_attachment(tx, oid, actor, action, *args, **kwargs):
        if action == "evidence.attached":
            raise RuntimeError("Synthetic evidence failure")
        return real_audit(tx, oid, actor, action, *args, **kwargs)

    monkeypatch.setattr(documents, "audit", fail_attachment)
    before = db.rows("SELECT * FROM audit_events")
    with pytest.raises(RuntimeError, match="Synthetic evidence failure"):
        upload(client, ee_org)
    for table in ("contacts", "bills", "bill_lines", "attachments"):
        assert db.scalar(f"SELECT COUNT(*) FROM {table}") == 0
    assert db.rows("SELECT * FROM audit_events") == before
    assert not list((tmp_path / "evidence").rglob("*.xml"))


def test_import_authorisation_and_csrf(client, db, ee_org):
    from api_app import api, current_user, User
    from starlette.middleware.sessions import SessionMiddleware
    with db.transaction() as tx:
        tx.execute("INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,'viewer','2026-10-01')",
                   (new_id(), ee_org["id"], "viewer@example.test"))
    assert upload(client, ee_org, headers={"X-Test-User": "viewer@example.test"}).status_code == 403
    assert upload(client, ee_org, headers={"X-Test-User": "outsider@example.test"}).status_code == 403
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        with TestClient(SessionMiddleware(api, secret_key="synthetic-csrf-test")) as session_client:
            assert upload(session_client, ee_org).status_code == 403
    finally:
        api.dependency_overrides.pop(current_user, None)


def test_import_preserves_inclusive_vat_rounding_on_approval(client, db, ee_org):
    invoice = dict(number="INCLUSIVE-100", issue_date="2026-10-01", due_date="2026-10-15",
                   currency="EUR", line_amount_type="inclusive", lines=[
                       dict(description="Inclusive purchase", quantity="1", unit_price="100",
                            net_amount="80.65", tax_amount="19.35", gross_amount="100", tax_rate="24")])
    content = e_arve_xml(dict(name="Synthetic inclusive supplier", registration_no="87654321"), {}, invoice, None)
    response = upload(client, ee_org, content)
    assert response.status_code == 201, response.text
    docs = DocumentService(db)
    bill = docs.bill(response.json()["bill_id"])
    assert Decimal(str(bill["subtotal"])) == Decimal("80.65")
    assert Decimal(str(bill["tax_total"])) == Decimal("19.35")
    assert Decimal(str(bill["lines"][0]["unit_price"])) == Decimal("80.65")
    assert Decimal(str(bill["lines"][0]["recoverable_tax"])) == Decimal("19.35")
    approved = docs.approve_bill(bill["id"], actor=ACTOR)
    entries = db.rows("SELECT * FROM gl_entries WHERE posting_batch_id=?", (approved["posting_batch_id"],))
    assert sum(Decimal(str(entry["debit"])) - Decimal(str(entry["credit"])) for entry in entries) == 0
    assert Decimal(str(approved["total"])) == Decimal("100")


def test_declared_vat_cannot_change_tax_arbitrarily(db, ee_org):
    docs = DocumentService(db)
    supplier = docs.create_contact(ee_org["id"], name="Synthetic supplier", country_code="EE")
    account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='EXPENSE'", (ee_org["id"],))
    tax = db.scalar("SELECT id FROM tax_codes WHERE organisation_id=? AND code='EE24'", (ee_org["id"],))
    with pytest.raises(ValueError, match="Declared bill VAT"):
        docs.create_bill(ee_org["id"], contact_id=supplier["id"], supplier_number="INVALID-VAT",
                         bill_date="2026-10-01", due_date="2026-10-15", actor=ACTOR, declared_vat=["50"],
                         lines=[dict(description="Service", unit_price="80.65", account_id=account, tax_code_id=tax)])
    assert db.scalar("SELECT COUNT(*) FROM bills") == 0
