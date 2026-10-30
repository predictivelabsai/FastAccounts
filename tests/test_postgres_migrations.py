"""Opt-in PostgreSQL migration and payroll immutability coverage."""

import os
import uuid

import pytest


PG_URL = os.getenv("FASTACCOUNTS_TEST_PG_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="FASTACCOUNTS_TEST_PG_URL is not set")


def test_postgres_full_migrations_and_approved_pay_item_immutability():
    from database import Database
    from organisations import OrganisationService
    from payroll import PayrollService

    schema = f"pgtest_{uuid.uuid4().hex}"
    database = Database(url=PG_URL, schema=schema)
    try:
        applied = database.migrate()
        assert len(applied) == 72
        assert applied[-1] == "0072_payroll_dimension_imports"
        assert database.migrate() == []

        organisation = OrganisationService(database).create(
            name="Synthetic PostgreSQL Payroll OÜ",
            country_code="EE",
            entity_type="EE_OU",
            owner_email="owner@example.test",
        )
        service = PayrollService(database)
        service.save_employee(
            organisation["id"], actor="owner@example.test", name="Synthetic employee",
            gross_salary="2000", personal_id="49001010001",
        )
        run = service.create_run(
            organisation["id"], period="2026-10", actor="owner@example.test",
        )
        component_type = next(
            item for item in service.component_types(organisation["id"])
            if item["preset_key"] == "bonus"
        )
        service.update_item(
            organisation["id"], run["id"], run["items"][0]["id"],
            actor="owner@example.test",
            components=[{"type_id": component_type["id"], "amount": "25"}],
        )
        service.approve(organisation["id"], run["id"], actor="owner@example.test")
        with pytest.raises(Exception, match="immutable"):
            with database.transaction() as tx:
                tx.execute(
                    "UPDATE pay_item_components SET amount=1 WHERE organisation_id=?",
                    (organisation["id"],),
                )
    finally:
        connection = database.connect()
        try:
            connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            connection.commit()
        finally:
            database._release(connection)
