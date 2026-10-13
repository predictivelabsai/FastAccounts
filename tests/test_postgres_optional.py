from __future__ import annotations

import os
from uuid import uuid4

import pytest

from database import Database
from organisations import OrganisationService


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"),reason="set TEST_POSTGRES_URL for PostgreSQL integration")
def test_postgres_migrations_and_tenant_bootstrap():
    schema="fast_accounts_test_"+uuid4().hex[:10]
    db=Database(url=os.environ["TEST_POSTGRES_URL"],schema=schema)
    assert db.migrate()==["0001_accounting_core","0002_integrations","0003_operations","0004_document_immutability", "0005_payroll", "0006_payroll_part_time_hourly", "0007_automation", "0008_import_staging", "0009_local_accounts", "0010_tsd_export", "0011_account_mappings", "0012_external_gl", "0013_sync_review", "0014_sync_push", "0015_payment_orders", "0016_bank_feed_schedules", "0017_prepayments", "0018_fixed_assets", "0019_master_data_import", "0020_quotes", "0021_periodisation", "0022_payment_links", "0023_analytical_objects", "0024_reminder_rules", "0025_fx_realised", "0026_fx_revaluations", "0027_mfa", "0028_document_settings", "0029_copilot"]
    assert db.migrate()==[]
    org=OrganisationService(db).create(name="Postgres Synthetic",country_code="UK",entity_type="UK_COMPANY",owner_email="pg@example.test")
    assert db.scalar("SELECT COUNT(*) FROM accounts WHERE organisation_id=?",(org["id"],))==17


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"), reason="set TEST_POSTGRES_URL for PostgreSQL integration")
def test_postgres_prepayment_events():
    from decimal import Decimal
    from documents import DocumentService
    from prepayments import PrepaymentService
    schema = "fast_accounts_test_" + uuid4().hex[:10]
    db = Database(url=os.environ["TEST_POSTGRES_URL"], schema=schema)
    db.migrate()
    org = OrganisationService(db).create(name="Postgres prepayment synthetic", country_code="EE",
        entity_type="EE_OU", owner_email="pg@example.test")
    docs, service = DocumentService(db), PrepaymentService(db)
    contact = docs.create_contact(org["id"], name="Synthetic prepayment contact", country_code="EE")
    bank = docs.create_bank_account(org["id"], name="Synthetic bank", currency="EUR")
    day = db.scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (org["id"],))
    accounts = {r["system_role"]: r["id"] for r in db.rows("SELECT * FROM accounts WHERE organisation_id=?", (org["id"],))}
    for side in ["customer", "supplier"]:
        create = dict(side=side, contact_id=contact["id"], bank_account_id=bank["id"], document_date=day,
                      amount="100.01", idempotency_key=side + "-create", actor="pg@example.test")
        prepayment = service.create(org["id"], **create)
        assert service.create(org["id"], **create) == prepayment
        lines = [dict(unit_price="60.01", account_id=accounts["SALES" if side == "customer" else "EXPENSE"])]
        if side == "customer":
            document = docs.create_invoice(org["id"], contact_id=contact["id"], issue_date=day, actor="pg@example.test", lines=lines)
            document = docs.issue_invoice(document["id"], actor="pg@example.test")
        else:
            document = docs.create_bill(org["id"], contact_id=contact["id"], bill_date=day, due_date=day,
                supplier_number="SYN-PG", actor="pg@example.test", lines=lines)
            document = docs.approve_bill(document["id"], actor="pg@example.test")
        allocation = dict(document_type="invoice" if side == "customer" else "bill", document_id=document["id"],
                          allocation_date=day, amount="60.01", idempotency_key=side + "-allocate", actor="pg@example.test")
        first = service.allocate(org["id"], prepayment["id"], **allocation)
        assert service.allocate(org["id"], prepayment["id"], **allocation) == first
        refund = dict(refund_date=day, amount="40", idempotency_key=side + "-refund", actor="pg@example.test")
        last = service.refund(org["id"], prepayment["id"], **refund)
        assert service.refund(org["id"], prepayment["id"], **refund) == last
        assert service.get(org["id"], prepayment["id"])["unallocated_balance"] == Decimal("0")
    assert db.scalar("SELECT SUM(debit)-SUM(credit) FROM gl_entries") == Decimal("0")


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"),reason="set TEST_POSTGRES_URL for PostgreSQL integration")
def test_postgres_payroll_0006_upgrade_and_sample_run(tmp_path, monkeypatch):
    import database
    from payroll import PayrollService
    from seed import SAMPLE_PAYROLL_EMPLOYEES
    schema="fast_accounts_test_"+uuid4().hex[:10]
    old=tmp_path/"old"; (old/"sqlite").mkdir(parents=True)
    for path in (database.MIGRATIONS/"sqlite").glob("000[1-5]*.sql"):
        (old/"sqlite"/path.name).write_text(path.read_text(encoding="utf-8"),encoding="utf-8")
    original=database.MIGRATIONS
    monkeypatch.setattr(database,"MIGRATIONS",old)
    db=Database(url=os.environ["TEST_POSTGRES_URL"],schema=schema)
    db.migrate()
    org=OrganisationService(db).create(name="Postgres EE",country_code="EE",entity_type="EE_OU",owner_email="pg@example.test")
    with db.transaction() as tx:
        tx.execute("INSERT INTO employees(id,organisation_id,name,gross_salary,funded_pension_percent,board_member,created_at) VALUES ('pg-board',?,'Old Board',1500,0,1,'2026-01-01')",(org["id"],))
    monkeypatch.setattr(database,"MIGRATIONS",original)
    assert db.migrate()==["0006_payroll_part_time_hourly", "0007_automation", "0008_import_staging", "0009_local_accounts", "0010_tsd_export", "0011_account_mappings", "0012_external_gl", "0013_sync_review", "0014_sync_push", "0015_payment_orders", "0016_bank_feed_schedules", "0017_prepayments", "0018_fixed_assets", "0019_master_data_import", "0020_quotes", "0021_periodisation", "0022_payment_links", "0023_analytical_objects", "0024_reminder_rules", "0025_fx_realised", "0026_fx_revaluations", "0027_mfa", "0028_document_settings", "0029_copilot"]
    service=PayrollService(db)
    assert service.employees(org["id"])[0]["pay_basis"]=="board_fee"
    for employee in SAMPLE_PAYROLL_EMPLOYEES:
        service.save_employee(org["id"],actor="pg@example.test",**employee)
    hourly={e["id"]:"176" for e in service.employees(org["id"]) if e["pay_basis"]=="hourly"}
    run=service.create_run(org["id"],period="2026-10",actor="pg@example.test",hours=hourly)
    items={i["employee_name"]:i for i in run["items"]}
    assert items["Liis Kuusk"]["social_tax"]=="292.38" and items["Peeter Oja"]["net"]=="1212.70"
    assert service.approve(org["id"],run["id"],actor="pg@example.test")["status"]=="Approved"
    with pytest.raises(Exception):
        with db.transaction() as tx:
            tx.execute("UPDATE employees SET pay_basis='hourly' WHERE id='pg-board'")


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"),reason="set TEST_POSTGRES_URL for PostgreSQL integration")
def test_postgres_local_accounts_flow(monkeypatch):
    import time
    from web import account_auth
    schema="fast_accounts_test_"+uuid4().hex[:10]
    db=Database(url=os.environ["TEST_POSTGRES_URL"],schema=schema)
    db.migrate()
    OrganisationService(db).create(name="Postgres Auth",country_code="EE",entity_type="EE_OU",owner_email="pg@example.test")
    monkeypatch.setattr(account_auth,"get_database",lambda: db)
    import web.google_auth as google_auth
    import database as database_module
    monkeypatch.setattr(database_module,"get_database",lambda: db)
    mails=[]
    monkeypatch.setattr(account_auth,"_send_link",lambda email,name,purpose,token,lang: mails.append((purpose,token)) or True)
    store=account_auth.AccountStore(db)
    store.register("PG@example.test","correct horse battery","PG","en")
    purpose,token=mails[-1]
    assert purpose=="verify" and store.authenticate("pg@example.test","correct horse battery") is None
    assert store.confirm_email(token,"correct horse battery")["email_verified"]==1
    assert store.authenticate("pg@example.test","correct horse battery")["email"]=="pg@example.test"
    store.request_reset("pg@example.test")
    _,reset=mails[-1]
    account=store.reset_password(reset,"brand new password")
    assert account["session_version"]==2 and store.reset_password(reset,"another password!") is None
    assert int(db.scalar("SELECT expires_at FROM auth_tokens WHERE purpose='reset'"))<=int(time.time())+3600
    for _ in range(3):
        store.hit("pg@example.test","login")
    assert int(db.scalar("SELECT attempts FROM auth_rate_limits"))==3
    assert store.link_google("pg@example.test")["id"]==account["id"]
    assert google_auth.access_allowed("pg@example.test")
