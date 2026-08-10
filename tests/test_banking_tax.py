from __future__ import annotations

from decimal import Decimal

import pytest

from banking import BankingService
from documents import DocumentService
from tax import TaxService


def _invoice(db, org, amount="100"):
    docs=DocumentService(db)
    contact=docs.create_contact(org["id"],name="Bank Customer",country_code="GB" if org["country_code"]=="UK" else "EE")
    accounts={r["system_role"]:r["id"] for r in db.rows("SELECT * FROM accounts WHERE organisation_id=?",(org["id"],))}
    tax_code="UK20" if org["country_code"]=="UK" else "EE24"
    tax=db.one("SELECT id FROM tax_codes WHERE organisation_id=? AND code=?",(org["id"],tax_code))["id"]
    posting_date=db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1",(org["id"],))
    invoice=docs.create_invoice(org["id"],contact_id=contact["id"],issue_date=posting_date,actor="a",lines=[{"description":"Work","quantity":1,"unit_price":amount,"account_id":accounts["SALES"],"tax_code_id":tax}])
    return docs,contact,docs.issue_invoice(invoice["id"],actor="a"),posting_date


def test_csv_import_duplicate_and_match_reconciliation(db, uk_org):
    docs,contact,invoice,posting_date=_invoice(db,uk_org)
    bank=docs.create_bank_account(uk_org["id"],name="Main",currency="GBP")
    content=f"date,amount,currency,counterparty,reference,id\n{posting_date},120.00,GBP,Bank Customer,{invoice['number']},tx-1\n".encode()
    service=BankingService(db)
    first=service.import_csv(uk_org["id"],bank["id"],content,actor="a")
    second=service.import_csv(uk_org["id"],bank["id"],content,actor="a")
    assert first["imported"]==1 and second["duplicate"]
    transaction=db.one("SELECT * FROM bank_transactions WHERE import_id=?",(first["id"],))
    suggestions=service.suggest(transaction["id"])
    assert suggestions[0]["target_id"]==invoice["id"] and "exact amount" in suggestions[0]["reasons"]
    result=service.reconcile_to_document(transaction["id"],target_type="invoice",target_id=invoice["id"],actor="a")
    assert result["amount"]==Decimal("120.00")
    assert docs.invoice(invoice["id"])["status"]=="Paid"
    assert db.one("SELECT status FROM bank_transactions WHERE id=?",(transaction["id"],))["status"]=="Reconciled"


def test_camt_import(db, ee_org):
    docs=DocumentService(db)
    bank=docs.create_bank_account(ee_org["id"],name="EE Bank",currency="EUR")
    xml=b'''<?xml version="1.0"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt><Stmt><Ntry><Amt Ccy="EUR">12.34</Amt><CdtDbtInd>DBIT</CdtDbtInd><BookgDt><Dt>2026-01-10</Dt></BookgDt><NtryDtls><TxDtls><Refs><AcctSvcrRef>abc</AcctSvcrRef></Refs><RmtInf><Ustrd>Fee</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry></Stmt></BkToCstmrStmt></Document>'''
    result=BankingService(db).import_camt053(ee_org["id"],bank["id"],xml,actor="a")
    row=db.one("SELECT * FROM bank_transactions WHERE import_id=?",(result["id"],))
    assert Decimal(str(row["amount"]))==Decimal("-12.34") and row["reference"]=="Fee"


@pytest.mark.parametrize("org_fixture,expected_key,expected_output",[("uk_org","box1_vat_due_sales","20.00"),("ee_org","kmd_4_output_vat","24.00")])
def test_country_tax_workpaper_review_and_export(request,db,org_fixture,expected_key,expected_output):
    org=request.getfixturevalue(org_fixture)
    docs,contact,invoice,posting_date=_invoice(db,org)
    service=TaxService(db)
    workpaper=service.prepare(org["id"],period_start=posting_date,period_end=posting_date)
    assert str(workpaper["boxes"][expected_key])==expected_output
    with pytest.raises(ValueError,match="review"):
        service.export_csv(workpaper["id"],actor="a")
    service.review(workpaper["id"],actor="accountant@example.test")
    exported=service.export_csv(workpaper["id"],actor="accountant@example.test")
    assert expected_key.encode() in exported
    planned=service.plan_direct_filing(workpaper["id"],actor="accountant@example.test")
    assert planned["status"]=="Planned" and "disabled" in planned["message"]
