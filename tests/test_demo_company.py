"""Per-account synthetic demo company: content, balance, idempotency and isolation."""
from __future__ import annotations

import socket
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from database import reset_database_cache


@pytest.fixture
def demo_db(db, monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "true")
    reset_database_cache()
    yield db
    reset_database_cache()


def _counts(db, organisation_id: str) -> dict:
    return {table: db.scalar(f"SELECT COUNT(*) FROM {table} WHERE organisation_id=?", (organisation_id,))
            for table in ("contacts", "invoices", "bills", "bank_transactions", "employees", "pay_runs")}


def test_seed_demo_company_creates_balanced_synthetic_books_for_the_owner(demo_db):
    from seed import DEMO_COMPANY_NAME, seed_demo_company

    organisation = seed_demo_company("Owner@Example.test ")
    assert organisation["name"] == DEMO_COMPANY_NAME
    assert organisation["country_code"] == "EE" and organisation["base_currency"] == "EUR"
    membership = demo_db.one("SELECT email,role FROM memberships WHERE organisation_id=?", (organisation["id"],))
    assert membership == {"email": "owner@example.test", "role": "owner"}
    counts = _counts(demo_db, organisation["id"])
    assert counts == {"contacts": 10, "invoices": 18, "bills": 8, "bank_transactions": counts["bank_transactions"],
                      "employees": 7, "pay_runs": 2}
    assert counts["bank_transactions"] >= 15
    runs = {row["period"]: row["status"] for row in demo_db.rows(
        "SELECT period,status FROM pay_runs WHERE organisation_id=?", (organisation["id"],))}
    assert runs == {"2026-09": "Approved", "2026-10": "Draft"}
    totals = demo_db.one("SELECT SUM(debit) AS debit, SUM(credit) AS credit FROM gl_entries WHERE organisation_id=?",
                         (organisation["id"],))
    assert Decimal(str(totals["debit"])) == Decimal(str(totals["credit"])) > 0
    # Every write is attributed to the account that asked for the demo, not the shared demo user.
    actors = {row["actor"] for row in demo_db.rows("SELECT DISTINCT actor FROM audit_events WHERE organisation_id=?",
                                                   (organisation["id"],))}
    assert actors == {"owner@example.test"}
    assert all(row["email"].endswith(("@example.invalid", "@demo-ou.example")) for row in demo_db.rows(
        "SELECT email FROM employees WHERE organisation_id=? UNION ALL SELECT email FROM contacts WHERE organisation_id=?",
        (organisation["id"], organisation["id"])))


def test_seed_demo_company_is_idempotent_and_scoped_per_account(demo_db):
    from organisations import OrganisationService
    from seed import DEMO_COMPANY_NAME, seed_demo_company

    first = seed_demo_company("owner@example.test")
    before = _counts(demo_db, first["id"])
    again = seed_demo_company("owner@example.test")
    assert again["id"] == first["id"]
    assert _counts(demo_db, first["id"]) == before

    # A same-named company owned by someone else is never reused or modified.
    foreign = OrganisationService(demo_db).create(name=DEMO_COMPANY_NAME, country_code="EE", entity_type="EE_OU",
                                                  owner_email="someone@example.test")
    other = seed_demo_company("second@example.test")
    assert other["id"] not in {first["id"], foreign["id"]}
    assert _counts(demo_db, foreign["id"])["invoices"] == 0
    assert not demo_db.one("SELECT id FROM memberships WHERE organisation_id=? AND email=?",
                           (first["id"], "second@example.test"))


def test_demo_organisation_endpoint_returns_the_callers_company(demo_db, monkeypatch):
    from api_app import api

    def blocked(*args, **kwargs):
        raise AssertionError("Live network is forbidden")

    with TestClient(api, headers={"X-Test-User": "owner@example.test"}) as client:
        with monkeypatch.context() as network:
            network.setattr(socket.socket, "connect", blocked)
            created = client.post("/demo-organisation")
            assert created.status_code == 201, created.text
            listed = client.get("/organisations").json()
            assert created.json()["id"] in {item["id"] for item in listed}
            assert client.post("/demo-organisation").json()["id"] == created.json()["id"]
