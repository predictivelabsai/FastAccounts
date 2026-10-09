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
