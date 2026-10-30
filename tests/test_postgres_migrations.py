"""Opt-in PostgreSQL migration and payroll immutability coverage."""

import os
import shutil
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


def test_postgres_upgrade_backfills_preserve_approved_payroll_components(tmp_path):
    from database import Database, MIGRATIONS
    from organisations import OrganisationService

    schema = f"pgtest_{uuid.uuid4().hex}"
    database = Database(url=PG_URL, schema=schema)

    def catalogue_through(version):
        catalogue = tmp_path / f"through_{version}"
        sqlite = catalogue / "sqlite"
        sqlite.mkdir(parents=True, exist_ok=True)
        for migration in (MIGRATIONS / "sqlite").glob("*.sql"):
            if int(migration.stem[:4]) <= version:
                shutil.copy2(migration, sqlite / migration.name)
        return catalogue

    try:
        assert len(database.migrate(migrations=catalogue_through(32))) == 32
        organisation = OrganisationService(database).create(
            name="Synthetic PostgreSQL Upgrade OÜ",
            country_code="EE",
            entity_type="EE_OU",
            owner_email="owner@example.test",
        )
        employee_id = str(uuid.uuid4())
        with database.transaction() as tx:
            tx.execute(
                "INSERT INTO employees(id,organisation_id,name,gross_salary,created_at) "
                "VALUES (?,?,?,?,?)",
                (employee_id, organisation["id"], "Upgrade employee", 2000, "2026-07-01"),
            )
        assert len(database.migrate(migrations=catalogue_through(41))) == 9

        run_id, item_id = str(uuid.uuid4()), str(uuid.uuid4())
        source_run_id, source_item_id = str(uuid.uuid4()), str(uuid.uuid4())
        with database.transaction() as tx:
            tx.execute(
                "INSERT INTO pay_runs(id,organisation_id,period,status,total_gross,total_net,"
                "total_employer_cost,created_by,created_at) VALUES (?,?,?,'Draft',?,?,?,?,?)",
                (run_id, organisation["id"], "2026-07", 2000, 1500, 2676,
                 "owner@example.test", "2026-07-31"),
            )
            tx.execute(
                "INSERT INTO pay_run_items(id,pay_run_id,organisation_id,employee_id,employee_name,"
                "gross_salary,board_member,funded_pension_percent,gross,funded_pension,ui_employee,"
                "tax_free_minimum,income_tax,net,withholding_total,social_tax,ui_employer,employer_cost) "
                "VALUES (?,?,?,?,?,?,0,2,2000,40,32,0,428,1500,500,660,53,2713)",
                (item_id, run_id, organisation["id"], employee_id, "Upgrade employee", 2000),
            )
            component_type = tx.one(
                "SELECT * FROM pay_component_types WHERE organisation_id=? AND preset_key='bonus'",
                (organisation["id"],),
            )
            tx.execute(
                "INSERT INTO pay_item_components(id,organisation_id,item_id,type_id,position,name,amount,"
                "direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,"
                "liability_role) VALUES (?,?,?,?,0,?,25,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), organisation["id"], item_id, component_type["id"],
                 component_type["name"], component_type["direction"], component_type["income_tax"],
                 component_type["social_tax"], component_type["ui_employee"],
                 component_type["ui_employer"], component_type["funded_pension"],
                 component_type["social_minimum"], component_type["liability_role"]),
            )
            tx.execute(
                "INSERT INTO pay_item_context(organisation_id,item_id,apply_tax_free_minimum) "
                "VALUES (?,?,0)",
                (organisation["id"], item_id),
            )
            tx.execute("UPDATE pay_runs SET status='Approved' WHERE id=?", (run_id,))
            tx.execute(
                "INSERT INTO pay_runs(id,organisation_id,period,status,total_gross,total_net,"
                "total_employer_cost,created_by,created_at) VALUES (?,?,?,'Draft',?,?,?,?,?)",
                (source_run_id, organisation["id"], "2026-08", 2000, 1500, 2676,
                 "owner@example.test", "2026-08-31"),
            )
            tx.execute(
                "INSERT INTO pay_run_items(id,pay_run_id,organisation_id,employee_id,employee_name,"
                "gross_salary,board_member,funded_pension_percent,gross,funded_pension,ui_employee,"
                "tax_free_minimum,income_tax,net,withholding_total,social_tax,ui_employer,employer_cost) "
                "VALUES (?,?,?,?,?,?,0,2,2000,40,32,0,428,1500,500,660,53,2713)",
                (source_item_id, source_run_id, organisation["id"], employee_id,
                 "Upgrade employee", 2000),
            )
            tx.execute(
                "INSERT INTO pay_item_components(id,organisation_id,item_id,type_id,position,name,amount,"
                "direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,"
                "liability_role) VALUES (?,?,?,?,0,?,25,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), organisation["id"], source_item_id, component_type["id"],
                 component_type["name"], component_type["direction"], component_type["income_tax"],
                 component_type["social_tax"], component_type["ui_employee"],
                 component_type["ui_employer"], component_type["funded_pension"],
                 component_type["social_minimum"], component_type["liability_role"]),
            )

        assert len(database.migrate(migrations=catalogue_through(48))) == 7
        with database.transaction() as tx:
            tx.execute(
                "UPDATE pay_item_components SET breakdown_json='{}' WHERE organisation_id=? AND item_id=?",
                (organisation["id"], source_item_id),
            )
            tx.execute("UPDATE pay_runs SET status='Approved' WHERE id=?", (source_run_id,))
        applied = database.migrate()
        assert len(applied) == 24
        assert applied[-1] == "0072_payroll_dimension_imports"
        assert database.migrate() == []

        with pytest.raises(Exception, match="immutable"):
            with database.transaction() as tx:
                tx.execute(
                    "UPDATE pay_item_components SET amount=26 WHERE organisation_id=? AND item_id=?",
                    (organisation["id"], item_id),
                )
    finally:
        connection = database.connect()
        try:
            connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            connection.commit()
        finally:
            database._release(connection)
