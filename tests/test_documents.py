from __future__ import annotations

from decimal import Decimal

import pytest

from documents import DocumentService


def _setup(db, org, contact_type="both"):
    service = DocumentService(db)
    contact = service.create_contact(org["id"], name="Synthetic Contact", country_code="GB" if org["country_code"] == "UK" else "EE", contact_type=contact_type)
    accounts = {r["system_role"]: r for r in db.rows("SELECT * FROM accounts WHERE organisation_id=?", (org["id"],))}
    taxes = {r["code"]: r for r in db.rows("SELECT * FROM tax_codes WHERE organisation_id=?", (org["id"],))}
    return service, contact, accounts, taxes


@pytest.mark.parametrize("org_fixture,tax_code,total,tax", [("uk_org","UK20",Decimal("240.00"),Decimal("40.00")), ("ee_org","EE24",Decimal("248.00"),Decimal("48.00"))])
def test_country_invoice_rounding_and_issue(request, db, org_fixture, tax_code, total, tax):
    org = request.getfixturevalue(org_fixture)
    service, contact, accounts, taxes = _setup(db, org)
    invoice = service.create_invoice(org["id"], contact_id=contact["id"], issue_date=db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (org["id"],)), actor="owner@example.test",
        lines=[{"description":"Consulting","quantity":"2","unit_price":"100","account_id":accounts["SALES"]["id"],"tax_code_id":taxes[tax_code]["id"]}])
    assert Decimal(str(invoice["total"])) == total and Decimal(str(invoice["tax_total"])) == tax
    issued = service.issue_invoice(invoice["id"], actor="owner@example.test")
    assert issued["number"] == "INV-000001" and issued["status"] == "Issued"
    entries = db.rows("SELECT * FROM gl_entries WHERE posting_batch_id=?", (issued["posting_batch_id"],))
    assert sum(Decimal(str(r["debit"])) for r in entries) == sum(Decimal(str(r["credit"])) for r in entries) == total


def test_inclusive_invoice_and_credit_note(db, uk_org):
    service, contact, accounts, taxes = _setup(db, uk_org)
    issue_date=db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (uk_org["id"],))
    invoice = service.create_invoice(uk_org["id"], contact_id=contact["id"], issue_date=issue_date, actor="a", amount_type="inclusive",
        lines=[{"description":"Inclusive","quantity":1,"unit_price":"120","account_id":accounts["SALES"]["id"],"tax_code_id":taxes["UK20"]["id"]}])
    assert Decimal(str(invoice["subtotal"])) == Decimal("100") and Decimal(str(invoice["tax_total"])) == Decimal("20")
    credit = service.create_invoice(uk_org["id"], contact_id=contact["id"], issue_date=issue_date, actor="a", document_type="credit_note", original_invoice_id=invoice["id"],
        lines=[{"description":"Credit","quantity":1,"unit_price":"100","account_id":accounts["SALES"]["id"],"tax_code_id":taxes["UK20"]["id"]}])
    issued = service.issue_invoice(credit["id"], actor="a")
    assert issued["number"] == "CRN-000001"
    ar = db.one("SELECT g.* FROM gl_entries g JOIN accounts a ON a.id=g.account_id WHERE g.posting_batch_id=? AND a.system_role='AR'", (issued["posting_batch_id"],))
    assert Decimal(str(ar["credit"])) == Decimal("120")


def test_bill_approval_payment_allocation_and_evidence(db, uk_org, tmp_path, monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_DATA_DIR", str(tmp_path / "data"))
    service, contact, accounts, taxes = _setup(db, uk_org)
    date=db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (uk_org["id"],))
    bill=service.create_bill(uk_org["id"],contact_id=contact["id"],supplier_number="SUP-1",bill_date=date,due_date=date,actor="a",
        lines=[{"description":"Hosting","quantity":1,"unit_price":"50","account_id":accounts["EXPENSE"]["id"],"tax_code_id":taxes["UK20"]["id"]}])
    bill=service.submit_bill_for_review(bill["id"],actor="a")
    bill=service.approve_bill(bill["id"],actor="accountant@example.test")
    assert bill["status"] == "Approved"
    bank=service.create_bank_account(uk_org["id"],name="Operating GBP",currency="GBP",sort_code="12-34-56")
    payment=service.record_payment(uk_org["id"],payment_type="supplier_payment",bank_account_id=bank["id"],payment_date=date,amount="60",actor="a",contact_id=contact["id"],allocations=[{"document_type":"bill","document_id":bill["id"],"amount":"60"}])
    assert payment["status"] == "Posted" and service.bill(bill["id"])["status"] == "Paid"
    evidence=service.attach_evidence(uk_org["id"],owner_type="bill",owner_id=bill["id"],filename="../receipt.pdf",content_type="application/pdf",content=b"synthetic receipt",actor="a")
    assert evidence["filename"] == "receipt.pdf" and len(evidence["sha256"]) == 64


def test_pdf_and_xml_exports(db, uk_org):
    service, contact, accounts, taxes = _setup(db, uk_org)
    date=db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (uk_org["id"],))
    invoice=service.create_invoice(uk_org["id"],contact_id=contact["id"],issue_date=date,actor="a",lines=[{"description":"Service","quantity":1,"unit_price":100,"account_id":accounts["SALES"]["id"],"tax_code_id":taxes["UK20"]["id"]}])
    invoice=service.issue_invoice(invoice["id"],actor="a")
    assert service.invoice_pdf(invoice["id"]).startswith(b"%PDF")
    xml=service.invoice_xml(invoice["id"])
    assert b"FastAccountsInvoice" in xml and b"INV-000001" in xml


def test_issued_invoice_accounting_fields_and_lines_are_database_immutable(db, uk_org):
    service, contact, accounts, taxes = _setup(db, uk_org)
    day=db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1",(uk_org["id"],))
    invoice=service.create_invoice(uk_org["id"],contact_id=contact["id"],issue_date=day,actor="a",lines=[{"description":"Locked","quantity":1,"unit_price":100,"account_id":accounts["SALES"]["id"],"tax_code_id":taxes["UK20"]["id"]}])
    invoice=service.issue_invoice(invoice["id"],actor="a")
    with pytest.raises(Exception,match="immutable"):
        with db.transaction() as tx:
            tx.execute("UPDATE invoices SET total=999 WHERE id=?",(invoice["id"],))
    with pytest.raises(Exception,match="immutable"):
        with db.transaction() as tx:
            tx.execute("UPDATE invoice_lines SET net_amount=999 WHERE invoice_id=?",(invoice["id"],))
