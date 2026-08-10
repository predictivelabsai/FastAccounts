from __future__ import annotations

from decimal import Decimal

import httpx

from documents import DocumentService
from ledger import LedgerService


def _issued(db, org):
    docs=DocumentService(db)
    contact=docs.create_contact(org["id"],name="Email Customer",country_code="GB",contact_type="customer",email="customer@example.invalid")
    accounts={r["system_role"]:r["id"] for r in db.rows("SELECT * FROM accounts WHERE organisation_id=?",(org["id"],))}
    tax=db.one("SELECT id FROM tax_codes WHERE organisation_id=? AND code='UK20'",(org["id"],))["id"]
    day=db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1",(org["id"],))
    invoice=docs.create_invoice(org["id"],contact_id=contact["id"],issue_date=day,actor="a",lines=[{"description":"Service","quantity":1,"unit_price":100,"account_id":accounts["SALES"],"tax_code_id":tax}])
    return docs,docs.issue_invoice(invoice["id"],actor="a"),day


def test_items_are_tenant_scoped(db,uk_org,ee_org):
    docs=DocumentService(db)
    sale=db.one("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'",(uk_org["id"],))["id"]
    item=docs.create_item(uk_org["id"],code="SVC",name="Service",sales_account_id=sale,unit_price="19.99")
    assert item["item_type"]=="service" and Decimal(str(item["unit_price"]))==Decimal("19.99")
    try:
        docs.create_item(ee_org["id"],code="BAD",name="Bad",sales_account_id=sale)
        assert False,"cross-tenant account should fail"
    except ValueError:
        pass


def test_postmark_delivery_records_provider_id(db,uk_org,monkeypatch):
    docs,invoice,_day=_issued(db,uk_org)
    monkeypatch.setenv("POSTMARK_API_TOKEN","test-token");monkeypatch.setenv("FROM_EMAIL","sender@example.invalid")
    client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={"MessageID":"synthetic-message"})))
    delivery=docs.send_invoice_email(invoice["id"],actor="a",client=client)
    assert delivery["status"]=="Sent" and delivery["provider_message_id"]=="synthetic-message"


def test_aging_general_ledger_and_balanced_sheet(db,uk_org):
    _docs,invoice,day=_issued(db,uk_org)
    ledger=LedgerService(db)
    ar=ledger.receivables_aging(uk_org["id"],as_at=day)
    general=ledger.general_ledger(uk_org["id"],start=day,end=day)
    balance=ledger.balance_sheet(uk_org["id"],as_at=day)
    assert ar["total"]==Decimal("120.00") and len(general)==3
    assert balance["assets"]==balance["liabilities_and_equity"]


def test_operations_migration_tables_exist(db):
    tables={row["name"] for row in db.rows("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"items","exchange_rates","invoice_deliveries","bank_rules","invitations","filing_declarations","month_end_checklists","retention_holds","accounting_exports"} <= tables
