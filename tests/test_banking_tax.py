from __future__ import annotations

from decimal import Decimal

import pytest

from banking import BankingService
from documents import DocumentService
from tax import (KMD_ICS_PURCHASE_WARNING, KMD_ICS_SUPPLY_WARNING,
                 KMD_REVERSE_CHARGE_WARNING, TaxService)


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


def _tax_document(db, org, code, amount="100", *, purchase=False, credit=False,
                  posted=True, posting_date=None, original_invoice_id=None):
    docs = DocumentService(db)
    date = posting_date or db.scalar(
        "SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1",
        (org["id"],))
    contact = docs.create_contact(org["id"], name="Synthetic EU Partner",
                                  country_code="LT", contact_type="both", vat_no="LT123456789")
    account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role=?",
                        (org["id"], "EXPENSE" if purchase else "SALES"))
    tax = db.scalar("SELECT id FROM tax_codes WHERE organisation_id=? AND code=?",
                    (org["id"], code))
    lines = [{"description": "Synthetic activity", "quantity": 1, "unit_price": amount,
              "account_id": account, "tax_code_id": tax}]
    if purchase:
        document = docs.create_bill(
            org["id"], contact_id=contact["id"], supplier_number=contact["id"],
            bill_date=date, due_date=date, lines=lines, actor="a",
            document_type="supplier_credit" if credit else "bill")
        if posted:
            document = docs.approve_bill(document["id"], actor="a")
    else:
        document = docs.create_invoice(
            org["id"], contact_id=contact["id"], issue_date=date, lines=lines, actor="a",
            document_type="credit_note" if credit else "invoice",
            original_invoice_id=original_invoice_id)
        if posted:
            document = docs.issue_invoice(document["id"], actor="a")
    return document, date


@pytest.mark.parametrize("basis,expected", [("accrual", "80.00"), ("cash", "30.00")])
def test_kmd_ics_supply_includes_credits_and_cash_weighting(db, ee_org, basis, expected):
    invoice, date = _tax_document(db, ee_org, "EEICS")
    credit, _ = _tax_document(db, ee_org, "EEICS", "20", credit=True,
                              original_invoice_id=invoice["id"])
    # Synthetic payment allocations exercise the existing cash weighting without a bank feed.
    with db.transaction() as tx:
        tx.execute("UPDATE invoices SET paid_total=? WHERE id=?", ("50", invoice["id"]))
        tx.execute("UPDATE invoices SET paid_total=? WHERE id=?", ("20", credit["id"]))
    _tax_document(db, ee_org, "EE0", "10")
    workpaper = TaxService(db).prepare(ee_org["id"], period_start=date, period_end=date, basis=basis)
    assert workpaper["boxes"]["kmd_3_1_intra_community_supply"] == Decimal(expected)
    assert workpaper["boxes"]["kmd_3_zero_rate_supply"] == Decimal(expected) + (Decimal("10") if basis == "accrual" else 0)
    assert KMD_ICS_SUPPLY_WARNING in workpaper["warnings"]
    assert len(workpaper["warnings"]) == (2 if basis == "cash" else 1)
    service = TaxService(db)
    assert service.get(workpaper["id"])["boxes"]["kmd_3_1_intra_community_supply"] == expected
    service.review(workpaper["id"], actor="a")
    assert f"kmd_3_1_intra_community_supply,{expected}".encode() in service.export_csv(workpaper["id"], actor="a")


def test_kmd_ics_box_absent_without_posted_period_and_tenant_evidence(db, ee_org):
    from organisations import OrganisationService
    other = OrganisationService(db).create(name="Other synthetic EE", country_code="EE",
        entity_type="EE_OU", owner_email="other@example.test")
    _, date = _tax_document(db, ee_org, "EEICS", posted=False)
    _tax_document(db, ee_org, "EERC", purchase=True, posted=False)
    _tax_document(db, other, "EEICS")
    _tax_document(db, other, "EERC", purchase=True)
    _tax_document(db, ee_org, "EEICS", posting_date=date[:8] + "02")
    workpaper = TaxService(db).prepare(ee_org["id"], period_start=date, period_end=date)
    assert "kmd_3_1_intra_community_supply" not in workpaper["boxes"]
    assert workpaper["boxes"]["kmd_3_zero_rate_supply"] == Decimal("0.00")
    assert workpaper["warnings"] == []


def test_kmd_present_ics_rows_netting_to_zero_keep_the_box(db, ee_org):
    invoice, date = _tax_document(db, ee_org, "EEICS")
    _tax_document(db, ee_org, "EEICS", credit=True, original_invoice_id=invoice["id"])
    workpaper = TaxService(db).prepare(ee_org["id"], period_start=date, period_end=date)
    assert workpaper["boxes"]["kmd_3_1_intra_community_supply"] == Decimal("0.00")
    assert workpaper["warnings"] == [KMD_ICS_SUPPLY_WARNING]


@pytest.mark.parametrize("purchase", [False, True])
def test_kmd_reverse_charge_is_warned_once_without_guessed_boxes(db, ee_org, purchase):
    _, date = _tax_document(db, ee_org, "EERC", purchase=purchase)
    _tax_document(db, ee_org, "EERC", "20", purchase=purchase)
    workpaper = TaxService(db).prepare(ee_org["id"], period_start=date, period_end=date)
    assert workpaper["warnings"] == [KMD_REVERSE_CHARGE_WARNING]
    assert set(workpaper["boxes"]) == {"kmd_1_taxable_supply_24", "kmd_2_reduced_rate_supply",
        "kmd_3_zero_rate_supply", "kmd_4_output_vat", "kmd_5_input_vat", "kmd_12_vat_payable"}
    assert workpaper["boxes"]["kmd_4_output_vat"] == Decimal("28.80")


def test_kmd_intra_eu_purchase_is_not_treated_as_supply_or_acquisition(db, ee_org):
    _, date = _tax_document(db, ee_org, "EEICS", purchase=True)
    workpaper = TaxService(db).prepare(ee_org["id"], period_start=date, period_end=date)
    assert workpaper["warnings"] == [KMD_ICS_PURCHASE_WARNING]
    assert "kmd_3_1_intra_community_supply" not in workpaper["boxes"]
    assert workpaper["boxes"]["kmd_3_zero_rate_supply"] == Decimal("0.00")


def test_uk_reverse_charge_does_not_get_kmd_warnings(db, uk_org):
    _, date = _tax_document(db, uk_org, "UKRC", purchase=True)
    workpaper = TaxService(db).prepare(uk_org["id"], period_start=date, period_end=date)
    assert workpaper["warnings"] == []
    assert all(key.startswith("box") for key in workpaper["boxes"])


def test_kmd_coverage_copy_in_all_locales():
    from web.i18n import catalog
    for lang in ("en", "et", "lt", "lv"):
        copy = catalog(lang)["workspace"]
        for key in ("kmd_3_1_intra_community_supply", KMD_REVERSE_CHARGE_WARNING,
                    KMD_ICS_PURCHASE_WARNING, KMD_ICS_SUPPLY_WARNING):
            assert copy[key].strip()
            if lang != "en":
                assert copy[key] != key
