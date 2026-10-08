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
    assert db.migrate()==["0001_accounting_core","0002_integrations","0003_operations","0004_document_immutability", "0005_payroll", "0006_payroll_part_time_hourly", "0007_automation"]
    assert db.migrate()==[]
    org=OrganisationService(db).create(name="Postgres Synthetic",country_code="UK",entity_type="UK_COMPANY",owner_email="pg@example.test")
    assert db.scalar("SELECT COUNT(*) FROM accounts WHERE organisation_id=?",(org["id"],))==10


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
    assert db.migrate()==["0006_payroll_part_time_hourly"]
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
