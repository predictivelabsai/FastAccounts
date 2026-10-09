"""Reviewed, tenant-scoped employee imports with no provider network calls."""
from __future__ import annotations

import json
from decimal import Decimal
import socket
from dataclasses import replace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx

from api_app import api, current_user, require_csrf
from connectors.base import ConnectorResult
from connectors.providers import FastHRProvider, PersonioProvider
from connectors.registry import REGISTRY
from database import reset_database_cache
from import_service import ImportService
from integration_service import CredentialVault, IntegrationService
from organisations import OrganisationService
from payroll import PayrollService


class FakeConnector:
    key = "xero"

    def __init__(self, records=(), *, cursors=(), ok=True, message="Synthetic pull"):
        self.records = tuple(records)
        self.cursors = list(cursors)
        self.ok = ok
        self.message = message
        self.seen_cursors = []

    def check(self):
        return ConnectorResult(self.key, "check", True, True, "Synthetic check")

    def pull(self, object_type, *, cursor=None):
        self.seen_cursors.append(cursor)
        next_cursor = self.cursors.pop(0) if self.cursors else cursor
        return ConnectorResult(
            self.key,
            f"pull:{object_type}",
            self.ok,
            True,
            self.message,
            self.records,
            next_cursor,
        )

    def push(self, object_type, records):
        raise AssertionError((object_type, records))


@pytest.fixture
def import_setup(db, ee_org, monkeypatch):
    key = Fernet.generate_key().decode()
    vault = CredentialVault(key)
    integration = IntegrationService(db, vault)
    integration.configure(
        ee_org["id"],
        "xero",
        credentials={"access_token": "stored-synthetic-secret", "tenant_id": "tenant"},
        config={"source": "synthetic"},
        actor="owner@example.test",
    )

    def install(fake):
        monkeypatch.setitem(
            REGISTRY, "xero", replace(REGISTRY["xero"], factory=lambda credentials, config: fake)
        )
        return ImportService(db, integration=integration)

    return install


def _employee(name, external_id, **changes):
    return {
        "external_id": external_id,
        "name": name,
        "gross_salary": "2000.005",
        "funded_pension_percent": "2",
        **changes,
    }


def test_sync_stages_deduplicates_matches_and_round_trips_cursor(
    db, ee_org, import_setup
):
    payroll = PayrollService(db)
    email_match = payroll.save_employee(
        ee_org["id"], actor="owner@example.test", name="Email Match", email="match@example.test",
        personal_id="49001010001", gross_salary="1800",
    )
    personal_match = payroll.save_employee(
        ee_org["id"], actor="owner@example.test", name="Personal Match", email="other@example.test",
        personal_id="49001010002", gross_salary="1900",
    )
    payroll.save_employee(
        ee_org["id"], actor="owner@example.test", name="Ambiguous One", email="shared@example.test",
        gross_salary="1700",
    )
    payroll.save_employee(
        ee_org["id"], actor="owner@example.test", name="Ambiguous Two", email="shared@example.test",
        gross_salary="1750",
    )
    fake = FakeConnector(
        [
            _employee("Old duplicate", "dup", email="none@example.test"),
            _employee("Latest duplicate", "dup", email="match@example.test"),
            _employee("By personal ID", "personal", personal_id="49001010002"),
            _employee("Ambiguous", "ambiguous", email="shared@example.test"),
        ],
        cursors=["employees-page-2", "employees-page-3"],
    )
    service = import_setup(fake)
    first = service.run_sync(
        ee_org["id"], "xero", "employees", actor="owner@example.test"
    )
    assert first["read_count"] == 4
    assert first["staged_counts"]["Pending"] == 3
    assert first["status"] == "Review Required"
    assert first["cursor"] == "employees-page-2"
    staged = service.get_staged(ee_org["id"], sync_run_id=first["id"])["records"]
    by_external = {row["external_id"]: row for row in staged}
    assert by_external["dup"]["external_payload"]["name"] == "Latest duplicate"
    assert by_external["dup"]["matched_local_employee_id"] == email_match["id"]
    assert by_external["personal"]["matched_local_employee_id"] == personal_match["id"]
    assert by_external["ambiguous"]["matched_local_employee_id"] is None
    assert by_external["ambiguous"]["review_note"].startswith("Ambiguous employee match:")

    second = service.run_sync(
        ee_org["id"], "xero", "employees", actor="owner@example.test"
    )
    assert fake.seen_cursors == [None, "employees-page-2"]
    assert second["cursor_before"] == "employees-page-2"
    assert second["cursor_after"] == "employees-page-3"


def test_apply_creates_maps_is_idempotent_and_updates_by_external_mapping(
    db, ee_org, import_setup
):
    fake = FakeConnector([_employee("Imported Employee", "worker-1")])
    service = import_setup(fake)
    sync = service.run_sync(ee_org["id"], "xero", "employees", actor="owner@example.test")
    staged_id = service.get_staged(ee_org["id"], sync_run_id=sync["id"])["records"][0]["id"]
    first = service.apply_staged(
        ee_org["id"], "xero", sync["id"], {staged_id: "apply"}, actor="owner@example.test"
    )
    assert first["applied"] == 1 and first["failed"] == 0
    employee_id = first["outcomes"][0]["employee_id"]
    employee = db.one("SELECT * FROM employees WHERE organisation_id=? AND id=?", (ee_org["id"], employee_id))
    assert str(employee["gross_salary"]) == "2000.01"
    mapping = db.one(
        "SELECT * FROM external_mappings WHERE organisation_id=? AND provider='xero' AND external_id='worker-1'",
        (ee_org["id"],),
    )
    assert mapping["local_id"] == employee_id
    assert mapping["ownership"] == "external" and mapping["direction"] == "import"

    second = service.apply_staged(
        ee_org["id"], "xero", sync["id"], {staged_id: "apply"}, actor="owner@example.test"
    )
    assert second["unchanged"] == 1
    assert db.scalar("SELECT COUNT(*) FROM employees WHERE organisation_id=?", (ee_org["id"],)) == 1

    with db.transaction() as tx:
        tx.execute(
            "UPDATE import_staged_records SET external_payload_json=?,status='Pending' WHERE organisation_id=? AND id=?",
            (json.dumps(_employee("Imported Employee Updated", "worker-1", gross_salary="2200")), ee_org["id"], staged_id),
        )
    updated = service.apply_staged(
        ee_org["id"], "xero", sync["id"], {staged_id: "apply"}, actor="owner@example.test"
    )
    assert updated["updated"] == 1
    assert db.one("SELECT name,gross_salary FROM employees WHERE id=?", (employee_id,))["name"] == "Imported Employee Updated"
    assert db.scalar("SELECT COUNT(*) FROM employees WHERE organisation_id=?", (ee_org["id"],)) == 1


def test_apply_validation_failures_raise_conflicts_and_batch_continues(
    db, ee_org, import_setup
):
    PayrollService(db).save_employee(
        ee_org["id"], actor="owner@example.test", name="Existing Name", gross_salary="1600"
    )
    records = [
        _employee("Valid Employee", "valid"),
        {"external_id": "missing-name", "gross_salary": "1000"},
        _employee("Zero Salary", "zero", gross_salary="0"),
        _employee("Wrong Salary", "wrong", gross_salary=["not", "money"]),
        _employee("Existing Name", "clash"),
        _employee("Bad Pension", "pension", funded_pension_percent="3"),
    ]
    service = import_setup(FakeConnector(records))
    sync = service.run_sync(ee_org["id"], "xero", "employees", actor="owner@example.test")
    staged = service.get_staged(ee_org["id"], sync_run_id=sync["id"])["records"]
    result = service.apply_staged(
        ee_org["id"],
        "xero",
        sync["id"],
        {row["id"]: "apply" for row in staged},
        actor="owner@example.test",
    )
    assert result["applied"] == 1
    assert result["failed"] == 5
    assert result["conflicts_raised"] == 5
    assert result["summary"]["conflict_count"] == 5
    assert result["summary"]["staged_counts"] == {
        "Pending": 0, "Approved": 0, "Rejected": 0, "Applied": 1, "Failed": 5,
    }
    assert db.scalar("SELECT COUNT(*) FROM sync_conflicts WHERE sync_run_id=?", (sync["id"],)) == 5
    assert db.scalar("SELECT COUNT(*) FROM employees WHERE organisation_id=?", (ee_org["id"],)) == 2
    assert all(item.get("reason") for item in result["outcomes"] if item["outcome"] == "failed")


def test_decision_omissions_rejection_and_tenant_scope(db, ee_org, import_setup):
    service = import_setup(FakeConnector([_employee("Pending", "pending"), _employee("Reject", "reject")]))
    sync = service.run_sync(ee_org["id"], "xero", "employees", actor="owner@example.test")
    staged = service.get_staged(ee_org["id"], sync_run_id=sync["id"])["records"]
    empty = service.apply_staged(
        ee_org["id"], "xero", sync["id"], {}, actor="owner@example.test"
    )
    assert empty["outcomes"] == [] and empty["summary"]["staged_counts"]["Pending"] == 2
    rejected = service.apply_staged(
        ee_org["id"], "xero", sync["id"], {staged[1]["id"]: "reject"}, actor="owner@example.test"
    )
    assert rejected["rejected"] == 1
    assert rejected["summary"]["staged_counts"]["Pending"] == 1

    other = OrganisationService(db).create(
        name="Other Eesti OÜ", country_code="EE", entity_type="EE_OU",
        owner_email="other@example.test",
    )
    with pytest.raises(KeyError, match="Sync run not found"):
        service.get_staged(other["id"], sync_run_id=sync["id"])


def test_sync_requires_connection_and_records_connector_failure(db, ee_org, import_setup, monkeypatch):
    unconfigured = OrganisationService(db).create(
        name="Unconfigured Eesti OÜ", country_code="EE", entity_type="EE_OU",
        owner_email="other@example.test",
    )
    with pytest.raises(KeyError, match="must be configured"):
        ImportService(db).run_sync(
            unconfigured["id"], "xero", "employees", actor="other@example.test"
        )
    assert db.scalar("SELECT COUNT(*) FROM sync_runs WHERE organisation_id=?", (unconfigured["id"],)) == 0

    service = import_setup(FakeConnector(ok=False, message="Synthetic provider unavailable"))
    with pytest.raises(ValueError, match="Synthetic provider unavailable"):
        service.run_sync(ee_org["id"], "xero", "employees", actor="owner@example.test")
    failed = db.one(
        "SELECT * FROM sync_runs WHERE organisation_id=? ORDER BY created_at DESC,id DESC LIMIT 1",
        (ee_org["id"],),
    )
    assert failed["status"] == "Failed"
    assert failed["error_message"] == "Synthetic provider unavailable"
    assert db.scalar("SELECT COUNT(*) FROM import_staged_records WHERE sync_run_id=?", (failed["id"],)) == 0

    key = Fernet.generate_key().decode()
    roadmap_integration = IntegrationService(db, CredentialVault(key))
    roadmap_integration.configure(
        ee_org["id"], "hibob", credentials={}, config={}, actor="owner@example.test"
    )
    with pytest.raises(ValueError, match="Adapter not yet built"):
        ImportService(db, integration=roadmap_integration).run_sync(
            ee_org["id"], "hibob", "employees", actor="owner@example.test"
        )
    roadmap_run = db.one(
        "SELECT * FROM sync_runs WHERE organisation_id=? AND provider='hibob'",
        (ee_org["id"],),
    )
    assert roadmap_run["status"] == "Failed" and roadmap_run["read_count"] == 0


def test_fasthr_sync_apply_and_repeat_are_idempotent(db, ee_org, monkeypatch):
    vault = CredentialVault(Fernet.generate_key().decode())
    integration = IntegrationService(db, vault)
    integration.configure(
        ee_org["id"],
        "fasthr",
        credentials={"base_url": "https://fasthr.example.test", "token": "synthetic-token"},
        config={},
        actor="owner@example.test",
    )
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "data": [{
                "id": 42,
                "code": "EMP-42",
                "first_name": "  Mari ",
                "last_name": " Maasik  ",
                "email": "mari@example.test",
                "dept_id": 7,
                "designation": "Account Manager",
                "manager_id": 3,
                "branch": "Tallinn",
                "status": "Active",
                "date_of_joining": "2025-05-06",
                "gender": "Female",
                "base_salary": 25200,  # annual; FastAccounts stores 2100.00/month
            }],
            "meta": {"total": 1, "limit": 200, "offset": 0},
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))

    def factory(credentials, config):
        return FastHRProvider(
            base_url=credentials["base_url"],
            token=credentials["token"],
            client=client,
        )

    monkeypatch.setitem(REGISTRY, "fasthr", replace(REGISTRY["fasthr"], factory=factory))
    service = ImportService(db, integration=integration)

    first_sync = service.run_sync(
        ee_org["id"], "fasthr", "employees", actor="owner@example.test"
    )
    staged = service.get_staged(ee_org["id"], sync_run_id=first_sync["id"])["records"]
    assert staged[0]["external_payload"]["fasthr_designation"] == "Account Manager"
    first_apply = service.apply_staged(
        ee_org["id"],
        "fasthr",
        first_sync["id"],
        {staged[0]["id"]: "apply"},
        actor="owner@example.test",
    )
    assert first_apply["applied"] == 1
    employee_id = first_apply["outcomes"][0]["employee_id"]
    employee = db.one(
        "SELECT * FROM employees WHERE organisation_id=? AND id=?",
        (ee_org["id"], employee_id),
    )
    assert employee["name"] == "Mari Maasik"
    assert str(employee["gross_salary"]) == "2100"
    mapping = db.one(
        "SELECT * FROM external_mappings WHERE organisation_id=? AND provider='fasthr' "
        "AND object_type='employees' AND external_id='42'",
        (ee_org["id"],),
    )
    assert mapping["local_id"] == employee_id

    second_sync = service.run_sync(
        ee_org["id"], "fasthr", "employees", actor="owner@example.test"
    )
    repeated = service.get_staged(ee_org["id"], sync_run_id=second_sync["id"])["records"]
    second_apply = service.apply_staged(
        ee_org["id"],
        "fasthr",
        second_sync["id"],
        {repeated[0]["id"]: "apply"},
        actor="owner@example.test",
    )
    assert second_apply["unchanged"] == 1
    assert db.scalar(
        "SELECT COUNT(*) FROM employees WHERE organisation_id=?", (ee_org["id"],)
    ) == 1
    assert len(requests) == 2
    assert all(request.headers["authorization"] == "Bearer synthetic-token" for request in requests)


def test_personio_sync_stages_missing_salary_and_apply_continues_after_exact_failure(
    db, ee_org, monkeypatch,
):
    secret = "personio-secret-must-not-leak"
    vault = CredentialVault(Fernet.generate_key().decode())
    integration = IntegrationService(db, vault)
    connection = integration.configure(
        ee_org["id"],
        "personio",
        credentials={"client_id": "synthetic-client-id", "client_secret": secret},
        config={"salary_attribute": "dynamic_12345"},
        actor="owner@example.test",
    )
    assert secret not in json.dumps(connection)

    def attribute(label, value, value_type="standard"):
        return {"label": label, "value": value, "type": value_type, "universal_id": None}

    def handler(request):
        if request.url.path == "/v1/auth":
            return httpx.Response(200, json={
                "success": True,
                "data": {"token": "synthetic-token", "expires_in": 86400, "scope": "employees"},
            })
        return httpx.Response(200, json={
            "success": True,
            "data": [
                {
                    "id": 101,
                    "attributes": {
                        "first_name": attribute("First name", "Missing"),
                        "last_name": attribute("Last name", "Salary"),
                        "email": attribute("Email", "missing.salary@example.test"),
                        "status": attribute("Status", "active"),
                    },
                },
                {
                    "id": 102,
                    "attributes": {
                        "first_name": attribute("First name", "Mapped"),
                        "last_name": attribute("Last name", "Salary"),
                        "email": attribute("Email", "mapped.salary@example.test"),
                        "status": attribute("Status", "active"),
                        "dynamic_12345": attribute("Monthly salary", "2100", "decimal"),
                    },
                },
            ],
            "metadata": {"total_elements": 2, "current_page": 1, "total_pages": 1},
            "offset": 0,
            "limit": 100,
        })

    client = httpx.Client(transport=httpx.MockTransport(handler))
    captured = {}

    def factory(credentials, config):
        captured.update(credentials=credentials, config=config)
        return PersonioProvider(
            credentials["client_id"],
            credentials["client_secret"],
            salary_attribute=config["salary_attribute"],
            client=client,
        )

    monkeypatch.setitem(REGISTRY, "personio", replace(REGISTRY["personio"], factory=factory))
    service = ImportService(db, integration=integration)
    sync = service.run_sync(
        ee_org["id"], "personio", "employees", actor="owner@example.test",
    )
    staged = service.get_staged(ee_org["id"], sync_run_id=sync["id"])["records"]
    assert len(staged) == 2
    staged_by_external = {row["external_id"]: row for row in staged}
    assert "gross_salary" not in staged_by_external["101"]["external_payload"]
    assert "pay_basis" not in staged_by_external["101"]["external_payload"]
    assert captured == {
        "credentials": {"client_id": "synthetic-client-id", "client_secret": secret},
        "config": {"salary_attribute": "dynamic_12345"},
    }

    applied = service.apply_staged(
        ee_org["id"],
        "personio",
        sync["id"],
        {row["id"]: "apply" for row in staged},
        actor="owner@example.test",
    )
    assert applied["failed"] == 1
    assert applied["applied"] == 1
    failed = next(outcome for outcome in applied["outcomes"] if outcome["outcome"] == "failed")
    assert failed["reason"] == "Gross salary is required"
    assert db.scalar(
        "SELECT COUNT(*) FROM employees WHERE organisation_id=?", (ee_org["id"],),
    ) == 1
    assert secret not in json.dumps(applied)


@pytest.fixture
def import_api(db, ee_org, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Live network is forbidden")

    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "true")
    monkeypatch.setenv("FASTACCOUNTS_ENCRYPTION_KEY", Fernet.generate_key().decode())
    reset_database_cache()
    with TestClient(api, headers={"X-Test-User": "owner@example.test"}) as client:
        with monkeypatch.context() as network:
            network.setattr(socket.socket, "connect", blocked)
            yield client, f"/organisations/{ee_org['id']}"
    reset_database_cache()


def test_import_routes_authorise_redact_and_audit_ids(import_api, db, ee_org, monkeypatch):
    client, base = import_api
    secret = "route-secret-must-not-leak"
    configured = client.post(base + "/integrations/xero", json={
        "credentials": {"access_token": secret, "tenant_id": "tenant"}, "config": {},
    })
    assert configured.status_code == 200
    fake = FakeConnector([_employee("API Employee", "api-worker", personal_id="49001010009")])
    captured = {}

    def factory(credentials, config):
        captured.update(credentials=credentials, config=config)
        return fake

    monkeypatch.setitem(REGISTRY, "xero", replace(REGISTRY["xero"], factory=factory))

    synced = client.post(base + "/integrations/xero/sync", json={"object_type": "employees"})
    assert synced.status_code == 200, synced.text
    sync = synced.json()
    assert secret not in synced.text
    assert captured == {
        "credentials": {"access_token": secret, "tenant_id": "tenant"},
        "config": {},
    }
    review = client.get(base + f"/integrations/xero/sync/{sync['id']}")
    assert review.status_code == 200
    assert review.json()["records"][0]["external_payload"]["personal_id"] == "49001010009"
    staged_id = review.json()["records"][0]["id"]
    applied = client.post(
        base + f"/integrations/xero/sync/{sync['id']}/apply",
        json={"decisions": {staged_id: "apply"}},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == 1 and secret not in applied.text
    listed = client.get(base + "/integrations/xero/syncs")
    assert listed.status_code == 200 and listed.json()[0]["id"] == sync["id"]

    OrganisationService(db).add_member(
        ee_org["id"], "owner@example.test", "accountant@example.test", "accountant"
    )
    OrganisationService(db).add_member(
        ee_org["id"], "owner@example.test", "administrator@example.test", "administrator"
    )
    assert client.get(
        base + "/integrations/xero/syncs",
        headers={"X-Test-User": "administrator@example.test"},
    ).status_code == 200
    accountant = {"X-Test-User": "accountant@example.test"}
    for method, path, body in (
        ("POST", "/integrations/xero/sync", {"object_type": "employees"}),
        ("GET", f"/integrations/xero/sync/{sync['id']}", None),
        ("POST", f"/integrations/xero/sync/{sync['id']}/apply", {"decisions": {}}),
        ("GET", "/integrations/xero/syncs", None),
    ):
        assert client.request(method, base + path, headers=accountant, json=body).status_code == 403

    routes = [route for route in api.routes if "/integrations/{provider}/sync" in route.path]
    assert len(routes) == 4
    for route in routes:
        expected = current_user if route.methods == {"GET"} else require_csrf
        assert expected in [dependency.call for dependency in route.dependant.dependencies]

    audits = db.rows(
        "SELECT object_id,details_json FROM audit_events WHERE organisation_id=? "
        "AND action LIKE 'integration.%' ORDER BY created_at,id",
        (ee_org["id"],),
    )
    assert any(item["object_id"] == sync["id"] for item in audits)
    audit_text = json.dumps(audits)
    assert "49001010009" not in audit_text
    assert "API Employee" not in audit_text
    assert "2000.005" not in audit_text
    assert secret not in audit_text


def test_fasthr_import_applies_part_time_and_hourly_and_skips_unpaid(db, ee_org, monkeypatch):
    from connectors.providers import FASTHR_NO_PAY_AMOUNT

    vault = CredentialVault(Fernet.generate_key().decode())
    integration = IntegrationService(db, vault)
    integration.configure(
        ee_org["id"],
        "fasthr",
        credentials={"base_url": "https://fasthr.example.test", "token": "synthetic-token"},
        config={},
        actor="owner@example.test",
    )
    rows = [
        {"id": 1, "first_name": "Kadri", "last_name": "Kask", "status": "Active",
         "base_salary": 30000, "working_time_ratio": 1.0, "personal_code": "49403136526"},
        {"id": 2, "first_name": "Liis", "last_name": "Kuusk", "status": "Active",
         "base_salary": 13620, "working_time_ratio": 0.5},
        {"id": 3, "first_name": "Rasmus", "last_name": "Mets", "status": "Active",
         "base_salary": 0, "hourly_rate": 8, "working_time_ratio": 1.0},
        {"id": 4, "first_name": "Tiit", "last_name": "Tamm", "status": "Active",
         "base_salary": None},
    ]
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"data": rows, "meta": {"total": len(rows), "limit": 200, "offset": 0}})))
    monkeypatch.setitem(REGISTRY, "fasthr", replace(REGISTRY["fasthr"], factory=lambda credentials, config:
        FastHRProvider(base_url=credentials["base_url"], token=credentials["token"], client=client)))
    service = ImportService(db, integration=integration)

    sync = service.run_sync(ee_org["id"], "fasthr", "employees", actor="owner@example.test")
    staged = {r["external_id"]: r for r in service.get_staged(ee_org["id"], sync_run_id=sync["id"])["records"]}
    assert staged["4"]["review_note"] == FASTHR_NO_PAY_AMOUNT
    assert all(staged[key]["review_note"] is None for key in ("1", "2", "3"))

    result = service.apply_staged(ee_org["id"], "fasthr", sync["id"],
                                  {r["id"]: "apply" for r in staged.values()}, actor="owner@example.test")
    assert (result["applied"], result["failed"]) == (3, 1)
    skipped = next(o for o in result["outcomes"] if o["staged_id"] == staged["4"]["id"])
    assert skipped["reason"] == FASTHR_NO_PAY_AMOUNT

    employees = {e["name"]: e for e in PayrollService(db).employees(ee_org["id"])}
    assert set(employees) == {"Kadri Kask", "Liis Kuusk", "Rasmus Mets"}
    assert employees["Kadri Kask"]["gross_salary"] == "2500.00"
    assert employees["Kadri Kask"]["personal_id"] == "49403136526"
    assert employees["Liis Kuusk"]["gross_salary"] == "1135.00" and Decimal(employees["Liis Kuusk"]["fte"]) == Decimal("0.5")
    assert employees["Rasmus Mets"]["pay_basis"] == "hourly"
    assert Decimal(employees["Rasmus Mets"]["hourly_rate"]) == Decimal("8") and employees["Rasmus Mets"]["gross_salary"] is None

    # Once linked, an employee whose FastHR salary disappears keeps the local pay terms.
    rows[0] = dict(rows[0], base_salary=None, designation="Lead")
    again = service.run_sync(ee_org["id"], "fasthr", "employees", actor="owner@example.test")
    kadri = next(r for r in service.get_staged(ee_org["id"], sync_run_id=again["id"])["records"]
                 if r["external_id"] == "1")
    outcome = service.apply_staged(ee_org["id"], "fasthr", again["id"], {kadri["id"]: "apply"},
                                   actor="owner@example.test")
    assert outcome["failed"] == 0
    assert PayrollService(db).employees(ee_org["id"])[0]["gross_salary"] == "2500.00"
