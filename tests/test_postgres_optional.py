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
    assert db.migrate()==["0001_accounting_core","0002_integrations","0003_operations","0004_document_immutability", "0005_payroll", "0006_automation"]
    assert db.migrate()==[]
    org=OrganisationService(db).create(name="Postgres Synthetic",country_code="UK",entity_type="UK_COMPANY",owner_email="pg@example.test")
    assert db.scalar("SELECT COUNT(*) FROM accounts WHERE organisation_id=?",(org["id"],))==10
