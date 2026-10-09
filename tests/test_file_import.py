"""Offline universal employee-file connector and reviewed pipeline."""
from __future__ import annotations

from decimal import Decimal

import pytest

from connectors.file_import import FileImportConnector
from import_service import ImportService


def test_check_is_ready_offline_and_does_not_claim_a_live_endpoint():
    result = FileImportConnector("", {}).check()

    assert result.provider == "file_import"
    assert result.operation == "check"
    assert result.ok is True
    assert result.live is False
    assert result.message == (
        "File import is ready; upload an employee CSV export to stage records."
    )


def test_parses_bom_comma_crlf_quoted_fields_english_aliases_and_passthrough():
    content = (
        "\ufeffEmployee ID,Full name,e-mail,Gross salary,Status,Department\r\n"
        '42,"Maasik, Mari",mari@example.test,2100.005,active,Finance\r\n'
        ",,,,,\r\n"
    )

    result = FileImportConnector(content, {}).pull("employee")

    assert result.cursor is None
    assert result.live is False
    assert result.records == ({
        "external_id": "42",
        "name": "Maasik, Mari",
        "email": "mari@example.test",
        "gross_salary": Decimal("2100.01"),
        "active": True,
        "file_Department": "Finance",
    },)


def test_parses_semicolon_estonian_aliases_and_status_values():
    content = (
        "Töötaja ID;Nimi;E-post;Palk;Isikukood;Staatus\n"
        "1;Mari Maasik;mari@example.test;2000;49001010001;aktiivne\n"
        "2;Jüri Tamm;juri@example.test;1800;39001010002;tööl\n"
        "3;Kati Kask;kati@example.test;1700;49001010003;\n"
        "4;Peeter Pärn;peeter@example.test;1600;39001010004;vanemapuhkus\n"
    )

    records = FileImportConnector(content, {}).pull("employees").records

    assert [record["active"] for record in records] == [True, True, True, False]
    assert records[0]["personal_id"] == "49001010001"
    assert records[0]["gross_salary"] == Decimal("2000.00")


def test_parses_tab_delimiter_and_omits_blank_or_zero_salary():
    content = "ID\tName\tBase salary\n1\tHourly One\t0\n2\tHourly Two\t\n"

    records = FileImportConnector(content, {}).pull("employee").records

    assert len(records) == 2
    assert all("gross_salary" not in record for record in records)
    assert all(record["active"] is True for record in records)


def test_generated_external_id_is_stable_for_identical_reimports():
    content = "Name,Email,Salary\nMari Maasik,mari@example.test,2100\n"

    first = FileImportConnector(content, {}).pull("employee").records[0]
    second = FileImportConnector(content, {}).pull("employee").records[0]

    assert first["external_id"] == second["external_id"]
    assert first["external_id"].startswith("file-")
    assert len(first["external_id"]) == 21


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "CSV content is empty"),
        ("\ufeff \r\n", "CSV content is empty"),
        ("Mari,mari@example.test\n", "header row is missing or unrecognized"),
        ("Email,Salary\nmari@example.test,1000\n", "missing required 'name' column"),
        ("Name,Email\nMari,mari@example.test,extra\n", "row 2 has 3 values"),
        ("Name,Email\n,mari@example.test\n", "row 2 has no employee name"),
    ],
)
def test_parser_errors_are_clear(content, message):
    with pytest.raises(ValueError, match=message):
        FileImportConnector(content, {}).pull("employee")


def test_duplicate_rows_dedupe_and_reimport_apply_is_idempotent(db, ee_org):
    content = (
        "Name,Email,Salary,Personal ID,Status,Team\n"
        "Mari Maasik,mari@example.test,2100,49001010001,active,Finance\n"
        "Mari Maasik,mari@example.test,2100,49001010001,active,Finance\n"
    )
    service = ImportService(db)

    first = service.run_sync(
        ee_org["id"],
        "file_import",
        "employee",
        actor="owner@example.test",
        credentials={"csv_content": content},
    )
    assert first["provider"] == "file_import"
    assert first["object_type"] == "employee"
    assert first["direction"] == "import"
    assert first["read_count"] == 2
    assert first["staged_counts"]["Pending"] == 1
    assert first["cursor_before"] is None and first["cursor_after"] is None
    staged = service.get_staged(ee_org["id"], sync_run_id=first["id"])["records"]
    assert staged[0]["external_payload"]["file_Team"] == "Finance"

    applied = service.apply_staged(
        ee_org["id"],
        "file_import",
        first["id"],
        {staged[0]["id"]: "apply"},
        actor="owner@example.test",
    )
    assert applied["applied"] == 1
    employee_id = applied["outcomes"][0]["employee_id"]
    employee = db.one(
        "SELECT * FROM employees WHERE organisation_id=? AND id=?",
        (ee_org["id"], employee_id),
    )
    assert employee["name"] == "Mari Maasik"
    assert str(employee["gross_salary"]) == "2100"
    mapping = db.one(
        "SELECT * FROM external_mappings WHERE organisation_id=? "
        "AND provider='file_import' AND object_type='employee'",
        (ee_org["id"],),
    )
    assert mapping["local_id"] == employee_id

    second = service.run_sync(
        ee_org["id"],
        "file_import",
        "employees",
        actor="owner@example.test",
        credentials={"csv_content": content},
    )
    repeated = service.get_staged(ee_org["id"], sync_run_id=second["id"])["records"]
    unchanged = service.apply_staged(
        ee_org["id"],
        "file_import",
        second["id"],
        {repeated[0]["id"]: "apply"},
        actor="owner@example.test",
    )
    assert unchanged["unchanged"] == 1
    assert db.scalar(
        "SELECT COUNT(*) FROM employees WHERE organisation_id=?", (ee_org["id"],)
    ) == 1
    assert content not in "".join(
        row["details_json"]
        for row in db.rows(
            "SELECT details_json FROM audit_events WHERE organisation_id=?",
            (ee_org["id"],),
        )
    )
