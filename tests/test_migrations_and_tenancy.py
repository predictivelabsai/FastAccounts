from __future__ import annotations

import sqlite3

import pytest

from database import Database
from organisations import AccessDenied, OrganisationService


def test_empty_migration_is_idempotent(tmp_path):
    db = Database(path=str(tmp_path / "empty.sqlite"))
    assert db.migrate() == ["0001_accounting_core", "0002_integrations", "0003_operations", "0004_document_immutability", "0005_payroll"]
    assert db.migrate() == []
    assert db.scalar("SELECT COUNT(*) FROM schema_migrations") == 5


def test_migration_preserves_existing_data(tmp_path):
    path = str(tmp_path / "upgrade.sqlite")
    db = Database(path=path)
    db.migrate()
    org = OrganisationService(db).create(name="Preserved", country_code="UK",
        entity_type="UK_COMPANY", owner_email="a@example.test")
    assert db.migrate() == []
    assert db.one("SELECT name FROM organisations WHERE id=?", (org["id"],))["name"] == "Preserved"


def test_unsafe_postgres_schema_is_rejected():
    with pytest.raises(ValueError, match="unsafe"):
        Database(url="postgresql://unused", schema='public; DROP SCHEMA public')


def test_postgres_pool_is_singleton_per_url(monkeypatch):
    import database

    created = []

    class FakePool:
        check_connection = staticmethod(lambda connection: None)

        def __init__(self, **kwargs):
            created.append(kwargs)

        def open(self):
            pass

        def close(self):
            pass

    database.close_database_pools()
    monkeypatch.setattr(database, "ConnectionPool", FakePool)
    first = database._postgres_pool("postgresql://example/one")
    second = database._postgres_pool("postgresql://example/one")
    other = database._postgres_pool("postgresql://example/two")

    assert first is second
    assert other is not first
    assert len(created) == 2
    assert created[0]["min_size"] == 0
    assert created[0]["max_size"] == 3
    database.close_database_pools()


def test_organisation_entity_country_and_seed_data(db):
    service = OrganisationService(db)
    with pytest.raises(ValueError, match="does not belong"):
        service.create(name="Wrong", country_code="EE", entity_type="UK_COMPANY", owner_email="a@example.test")
    uk = service.create(name="UK Sole", country_code="UK", entity_type="UK_SOLE_TRADER", owner_email="a@example.test")
    ee = service.create(name="EE FIE", country_code="EE", entity_type="EE_FIE", owner_email="a@example.test")
    assert uk["base_currency"] == "GBP" and ee["base_currency"] == "EUR"
    assert db.scalar("SELECT COUNT(*) FROM accounts WHERE organisation_id=?", (uk["id"],)) == 10
    assert db.scalar("SELECT COUNT(*) FROM tax_codes WHERE organisation_id=?", (ee["id"],)) == 8
    assert db.scalar("SELECT COUNT(*) FROM fiscal_periods WHERE organisation_id=?", (uk["id"],)) == 24
    assert {row["code"]: row["name"] for row in db.rows(
        "SELECT code,name FROM accounts WHERE organisation_id=? AND system_role LIKE 'PAYROLL_%'",
        (ee["id"],),
    )} == {
        "6110": "Palgakulu",
        "6120": "Sotsiaalmaksu kulu",
        "6130": "Tööandja töötuskindlustusmakse kulu",
        "2210": "Palgavõlg töötajatele",
        "2220": "Kinnipeetud tulumaksu võlg",
        "2230": "Pensioni- ja töötuskindlustusmaksete võlg",
        "2240": "Sotsiaalmaksu ja tööandja töötuskindlustuse võlg",
    }


def test_membership_roles_and_tenant_isolation(db, uk_org, ee_org):
    service = OrganisationService(db)
    service.add_member(uk_org["id"], "owner@example.test", "viewer@example.test", "viewer")
    assert [o["id"] for o in service.for_user("viewer@example.test")] == [uk_org["id"]]
    with pytest.raises(AccessDenied):
        service.require(ee_org["id"], "viewer@example.test", {"viewer"})
    with pytest.raises(AccessDenied):
        service.add_member(uk_org["id"], "viewer@example.test", "x@example.test", "viewer")


def test_database_foreign_keys_are_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as tx:
            tx.execute("INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES ('x','missing','x@x.test','viewer','now')")
