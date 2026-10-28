"""FastAccounts test setup."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FASTACCOUNTS_SECRET", "test-session-secret")
os.environ.setdefault("FASTACCOUNTS_ALLOW_TEST_AUTH", "true")
os.environ.setdefault("FASTACCOUNTS_DEFAULT_LANG", "en")
os.environ.setdefault("FASTACCOUNTS_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
def db(tmp_path):
    from database import Database
    database = Database(path=str(tmp_path / "test.sqlite"))
    database.migrate()
    return database


@pytest.fixture
def uk_org(db):
    from organisations import OrganisationService
    return OrganisationService(db).create(
        name="Synthetic UK Ltd", country_code="UK", entity_type="UK_COMPANY",
        owner_email="owner@example.test", registration_no="01234567", vat_no="GB123456789",
    )


@pytest.fixture
def ee_org(db):
    from organisations import OrganisationService
    return OrganisationService(db).create(
        name="Synthetic Eesti OÜ", country_code="EE", entity_type="EE_OU",
        owner_email="owner@example.test", registration_no="12345678", vat_no="EE123456789",
    )


@pytest.fixture
def legacy_payroll():
    """Seed pre-0037 payroll without calling services which require its schema."""
    def seed(database, organisation_id, *, name, gross, fte='1', actor='owner@example.test'):
        from core_utils import db_number
        from payroll import AMOUNTS, PayrollService, calculate_pay
        person = dict(gross_salary=gross, funded_pension_percent=2,
                      apply_tax_free_minimum=False, board_member=False)
        amounts = calculate_pay(person, period='2026-10')
        with database.transaction() as tx:
            tx.execute("INSERT INTO employees(id,organisation_id,name,gross_salary,fte,created_at) "
                       "VALUES ('legacy-employee',?,?,?,?,'2026-01-01')", (organisation_id, name, gross, fte))
            tx.execute("INSERT INTO pay_runs(id,organisation_id,period,total_gross,total_net,total_employer_cost,created_by,created_at) "
                       "VALUES ('legacy-run',?,'2026-10',?,?,?,?, '2026-10-31')",
                       (organisation_id, *(db_number(amounts[k]) for k in ('gross', 'net', 'employer_cost')), actor))
            columns = ('id', 'pay_run_id', 'organisation_id', 'employee_id', 'employee_name',
                       'gross_salary', 'board_member', 'funded_pension_percent', 'pay_basis', 'fte', *AMOUNTS)
            values = ('legacy-item', 'legacy-run', organisation_id, 'legacy-employee', name,
                      gross, 0, 2, 'monthly', fte, *(db_number(amounts[k]) for k in AMOUNTS))
            tx.execute('INSERT INTO pay_run_items(' + ','.join(columns) + ') VALUES (' +
                       ','.join('?' for _ in columns) + ')', values)
            tx.execute("INSERT INTO pay_item_context(organisation_id,item_id,apply_tax_free_minimum) "
                       "VALUES (?,'legacy-item',0)", (organisation_id,))
        return PayrollService(database).runs(organisation_id)[0]
    return seed
