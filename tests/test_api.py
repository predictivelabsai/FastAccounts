from __future__ import annotations

import os
import json
import socket
from dataclasses import replace
from datetime import date, timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import automation
from api_app import api, current_user, require_csrf
from connectors.base import ConnectorResult
from connectors.registry import REGISTRY
from database import reset_database_cache
from documents import DocumentService
from organisations import OrganisationService


@pytest.fixture
def automation_api(db, uk_org, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Live network is forbidden")
    monkeypatch.delenv("POSTMARK_API_TOKEN", raising=False)
    monkeypatch.delenv("FROM_EMAIL", raising=False)
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "true")
    reset_database_cache()
    docs = DocumentService(db)
    contact = docs.create_contact(uk_org["id"], name="Synthetic API customer", country_code="GB",
                                  email="customer@example.invalid")
    account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (uk_org["id"],))
    invoice = docs.create_invoice(uk_org["id"], contact_id=contact["id"], issue_date=date.today().isoformat(),
        due_date=(date.today() - timedelta(days=20)).isoformat(), actor="owner@example.test",
        lines=[dict(description="API retainer", quantity="1", unit_price="100", account_id=account)])
    invoice = docs.issue_invoice(invoice["id"], actor="owner@example.test")
    with TestClient(api, headers={"X-Test-User": "owner@example.test"}) as client:
        # Windows creates the event loop's socket pair while entering TestClient.
        with monkeypatch.context() as network:
            network.setattr(socket.socket, "connect", blocked)
            yield client, f"/organisations/{uk_org['id']}", invoice
    reset_database_cache()


@pytest.fixture
def integration_api(db, uk_org, monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Live network is forbidden")

    encryption_key = Fernet.generate_key().decode()
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "true")
    monkeypatch.setenv("FASTACCOUNTS_ENCRYPTION_KEY", encryption_key)
    reset_database_cache()
    with TestClient(api, headers={"X-Test-User": "owner@example.test"}) as client:
        with monkeypatch.context() as network:
            network.setattr(socket.socket, "connect", blocked)
            yield client, f"/organisations/{uk_org['id']}"
    reset_database_cache()


class FakeCheckConnector:
    def __init__(self, provider: str, *, ok: bool, live: bool, message: str):
        self.key = provider
        self.result = ConnectorResult(
            provider=provider, operation="check", ok=ok, live=live, message=message,
        )

    def check(self):
        return self.result

    def pull(self, object_type, *, cursor=None):
        raise AssertionError((object_type, cursor))

    def push(self, object_type, records):
        raise AssertionError((object_type, records))


def test_integration_catalogue_exposes_registry_fields(integration_api):
    client, _ = integration_api
    response = client.get("/integrations")
    assert response.status_code == 200
    catalogue = {item["key"]: item for item in response.json()}
    assert [field["name"] for field in catalogue["quickbooks"]["credential_fields"]] == [
        "access_token", "realm_id", "sandbox",
    ]
    assert catalogue["quickbooks"]["registry_status"] == "Adapter ready"
    assert catalogue["hmrc"]["registry_status"] == "Planning stub"
    assert catalogue["personio"]["registry_status"] == "Roadmap · adapter not built"
    assert "Adapter not yet built" in catalogue["personio"]["credential_note"]


def test_integration_test_success_failure_disconnect_and_redaction(
    integration_api, db, monkeypatch,
):
    client, base = integration_api
    configured_secret = "configured-secret-value"
    configured = client.post(base + "/integrations/xero", json={
        "credentials": {"access_token": configured_secret, "tenant_id": "tenant-a"},
        "config": {"direction": "import"}, "external_tenant_id": "tenant-a",
    })
    assert configured.status_code == 200, configured.text
    assert configured_secret not in configured.text
    assert set(configured.json()) == {
        "id", "provider", "status", "external_tenant_id", "config", "updated_at",
        "registry_status",
    }

    captured = {}

    def successful_factory(credentials, config):
        captured["credentials"] = credentials
        captured["config"] = config
        return FakeCheckConnector("xero", ok=True, live=True, message="Synthetic check passed")

    monkeypatch.setitem(
        REGISTRY, "xero", replace(REGISTRY["xero"], factory=successful_factory),
    )
    ephemeral_secret = "ephemeral-test-secret"
    checked = client.post(base + "/integrations/xero/test", json={
        "credentials": {"access_token": ephemeral_secret, "tenant_id": "tenant-b"},
        "config": {"sandbox": True},
    })
    assert checked.status_code == 200, checked.text
    assert checked.json() == {
        "provider": "xero", "operation": "check", "ok": True, "live": True,
        "message": "Synthetic check passed",
    }
    assert captured == {
        "credentials": {"access_token": ephemeral_secret, "tenant_id": "tenant-b"},
        "config": {"sandbox": True},
    }
    assert ephemeral_secret not in checked.text

    listed = client.get(base + "/integrations")
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "Connected"
    assert configured_secret not in listed.text and ephemeral_secret not in listed.text
    raw = db.one("SELECT encrypted_credentials FROM integration_connections WHERE provider='xero'")
    assert configured_secret not in raw["encrypted_credentials"]
    assert ephemeral_secret not in raw["encrypted_credentials"]

    monkeypatch.setitem(
        REGISTRY, "xero",
        replace(REGISTRY["xero"], factory=lambda _credentials, _config: FakeCheckConnector(
            "xero", ok=False, live=True, message="Synthetic check failed",
        )),
    )
    failed = client.post(base + "/integrations/xero/test", json={"credentials": {}})
    assert failed.status_code == 200
    assert failed.json()["ok"] is False
    assert client.get(base + "/integrations").json()[0]["status"] == "Error"

    disconnected = client.post(base + "/integrations/xero/disconnect")
    assert disconnected.status_code == 200
    assert disconnected.json()["status"] == "Disconnected"
    actions = db.rows(
        "SELECT action,details_json FROM audit_events WHERE object_id=? ORDER BY created_at",
        (configured.json()["id"],),
    )
    assert [item["action"] for item in actions].count("integration.status_changed") == 3


def test_roadmap_test_is_non_live_and_does_not_persist_test_credentials(
    integration_api, db,
):
    client, base = integration_api
    response = client.post(base + "/integrations/personio", json={
        "credentials": {"placeholder": "saved-placeholder"}, "config": {},
    })
    assert response.status_code == 200
    checked = client.post(base + "/integrations/personio/test", json={
        "credentials": {"placeholder": "ephemeral-placeholder"},
    })
    assert checked.status_code == 200
    assert checked.json()["ok"] is False and checked.json()["live"] is False
    assert "Adapter not yet built for this provider" in checked.json()["message"]
    listed = client.get(base + "/integrations").json()
    assert listed[0]["status"] == "Error"
    assert all(item["status"] != "Connected" for item in listed)
    raw = db.one("SELECT encrypted_credentials FROM integration_connections WHERE provider='personio'")
    assert "saved-placeholder" not in raw["encrypted_credentials"]
    assert "ephemeral-placeholder" not in raw["encrypted_credentials"]

    before = db.scalar("SELECT COUNT(*) FROM integration_connections")
    unconfigured = client.post(base + "/integrations/deel/test", json={
        "credentials": {"placeholder": "never-persisted"},
    })
    assert unconfigured.status_code == 200 and unconfigured.json()["live"] is False
    assert db.scalar("SELECT COUNT(*) FROM integration_connections") == before


def test_integration_routes_are_tenant_scoped(integration_api, db):
    client, base = integration_api
    configured = client.post(base + "/integrations/xero", json={
        "credentials": {"access_token": "one", "tenant_id": "one"}, "config": {},
    })
    assert configured.status_code == 200
    other_org = OrganisationService(db).create(
        name="Other tenant", country_code="UK", entity_type="UK_COMPANY",
        owner_email="other@example.test",
    )
    other_base = f"/organisations/{other_org['id']}"
    other_headers = {"X-Test-User": "other@example.test"}
    assert client.get(other_base + "/integrations", headers=other_headers).json() == []
    assert client.post(other_base + "/integrations/merit", headers=other_headers, json={
        "credentials": {"api_id": "other", "api_key": "other-secret"}, "config": {},
    }).status_code == 200
    assert [item["provider"] for item in client.get(base + "/integrations").json()] == ["xero"]
    assert [item["provider"] for item in client.get(
        other_base + "/integrations", headers=other_headers,
    ).json()] == ["merit"]

    for method, path, payload in (
        ("GET", "/integrations", None),
        ("POST", "/integrations/xero/test", {"credentials": {}}),
        ("POST", "/integrations/xero/disconnect", None),
    ):
        assert client.request(
            method, base + path, headers=other_headers, json=payload,
        ).status_code == 403


def test_unknown_integration_provider_is_rejected(integration_api):
    client, base = integration_api
    assert client.post(base + "/integrations/fasthr", json={
        "credentials": {}, "config": {},
    }).status_code == 422
    assert client.post(base + "/integrations/fasthrm/test", json={
        "credentials": {},
    }).status_code == 422


def create_api_schedule(client, base, invoice, **changes):
    response = client.post(base + "/invoice-schedules", json={
        "template_invoice_id": invoice["id"], "interval_kind": "monthly",
        "next_run_date": date.today().isoformat(), **changes,
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_api_schedule_create_list_patch_and_read_only_gets(automation_api, db):
    client, base, invoice = automation_api
    schedule = create_api_schedule(client, base, invoice)
    assert schedule["lines"][0]["description"] == "API retainer"
    assert schedule["runs"] == []
    url = base + "/invoice-schedules/" + schedule["id"]
    next_date = (date.today() + timedelta(days=5)).isoformat()
    response = client.patch(url, json={"next_run_date": next_date, "auto_email": True})
    assert response.status_code == 200, response.text
    assert response.json()["next_run_date"] == next_date
    assert response.json()["auto_email"] == 1
    assert response.json()["interval_kind"] == "monthly"
    tables = ("invoice_schedules", "invoice_schedule_lines", "schedule_runs", "invoices",
              "invoice_reminder_events", "invoice_deliveries", "audit_events")
    before = {table: db.rows(f"SELECT * FROM {table} ORDER BY id") for table in tables}
    listed = client.get(base + "/invoice-schedules").json()
    assert listed[0]["id"] == schedule["id"]
    assert listed[0]["contact_name"] == "Synthetic API customer"
    assert listed[0]["interval_kind"] == "monthly"
    assert listed[0]["last_run_date"] is None and listed[0]["last_invoice_number"] is None
    assert client.get(url).json() == response.json()
    assert client.get(base + "/reminders/due").status_code == 200
    assert client.get("/email-status").status_code == 200
    assert before == {table: db.rows(f"SELECT * FROM {table} ORDER BY id") for table in tables}


def test_api_schedule_run_now_sequence_and_duplicate_period(automation_api, db):
    client, base, invoice = automation_api
    schedule = create_api_schedule(client, base, invoice)
    url = base + "/invoice-schedules/" + schedule["id"]
    response = client.post(url + "/run-now")
    assert response.status_code == 200, response.text
    run = response.json()["runs"][0]
    assert run["status"] == "Issued"
    assert int(run["invoice"]["number"][-6:]) == int(invoice["number"][-6:]) + 1
    history = client.get(url).json()["runs"]
    assert history[0]["status"] == "Issued"
    assert history[0]["invoice_number"] == run["invoice"]["number"]
    listed = client.get(base + "/invoice-schedules").json()[0]
    assert listed["last_run_date"] == run["run_date"]
    assert listed["last_invoice_number"] == run["invoice"]["number"]
    # run_now advances the cursor and allows early runs; retry the original period explicitly.
    assert client.patch(url, json={"next_run_date": schedule["next_run_date"]}).status_code == 200
    before = db.scalar("SELECT COUNT(*) FROM invoices")
    retry = client.post(url + "/run-now")
    assert retry.status_code == 200 and retry.json()["runs"][0]["status"] == "Skipped"
    assert db.scalar("SELECT COUNT(*) FROM invoices") == before
    assert db.scalar("SELECT COUNT(*) FROM schedule_runs") == 1


def test_api_schedule_history_order(automation_api, monkeypatch):
    client, base, invoice = automation_api
    today = date.today()
    schedule = create_api_schedule(client, base, invoice, interval_kind="custom_days", interval_days=1,
                                   next_run_date=(today - timedelta(days=1)).isoformat())
    url = base + "/invoice-schedules/" + schedule["id"]
    original_date = automation._date
    monkeypatch.setattr(automation, "_date", lambda value=None: original_date(
        value if value is not None else (today - timedelta(days=1)).isoformat()))
    assert client.post(url + "/run-now").json()["runs"][0]["status"] == "Issued"
    monkeypatch.setattr(automation, "_date", original_date)
    assert client.post(url + "/run-now").json()["runs"][0]["status"] == "Issued"
    runs = client.get(url).json()["runs"]
    assert [r["run_date"] for r in runs] == [today.isoformat(), (today - timedelta(days=1)).isoformat()]


def test_api_reminders_due_and_opt_out(automation_api, db):
    client, base, invoice = automation_api
    due = client.get(base + "/reminders/due")
    assert due.status_code == 200
    assert due.json()["email_connected"] is False
    assert [(r["invoice_id"], r["stage"]) for r in due.json()["items"]] == [(invoice["id"], s) for s in (0, 1, 2)]
    url = base + f"/invoices/{invoice['id']}/reminders/opt-out"
    for disabled in (True, False):
        response = client.post(url, json={"reminders_disabled": disabled})
        assert response.status_code == 200
        assert response.json() == {"invoice_id": invoice["id"], "reminders_disabled": disabled}
        assert client.get(base + "/reminders/due").json()["items"] == ([] if disabled else due.json()["items"])
        action = "reminder.opt_out" if disabled else "reminder.opt_in"
        event = db.one("SELECT * FROM audit_events WHERE action=? AND object_id=?", (action, invoice["id"]))
        assert event["organisation_id"] == invoice["organisation_id"] and event["actor"] == "owner@example.test"


def test_api_reminder_not_connected(automation_api, db):
    client, base, invoice = automation_api
    response = client.post(base + f"/invoices/{invoice['id']}/reminders/0/send")
    assert response.status_code == 422
    assert response.json()["detail"] == "Email delivery is not connected. Set POSTMARK_API_TOKEN and FROM_EMAIL to send reminders."
    assert db.scalar("SELECT COUNT(*) FROM invoice_deliveries") == 0
    assert db.scalar("SELECT COUNT(*) FROM invoice_reminder_events") == 0


def test_api_reminder_mock_transport_delivery_and_duplicate(automation_api, db, monkeypatch):
    client, base, invoice = automation_api
    monkeypatch.setenv("POSTMARK_API_TOKEN", "synthetic-token")
    monkeypatch.setenv("FROM_EMAIL", "sender@example.invalid")
    requests, clients = [], []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"MessageID": "synthetic-message"})
    def factory():
        http = httpx.Client(transport=httpx.MockTransport(respond))
        clients.append(http)
        return http
    monkeypatch.setattr(automation, "HTTP_CLIENT_FACTORY", factory)
    url = base + f"/invoices/{invoice['id']}/reminders/0/send"
    response = client.post(url)
    assert response.status_code == 200, response.text
    event = response.json()
    assert event["status"] == event["delivery"]["status"] == "Sent"
    delivery = db.one("SELECT * FROM invoice_deliveries WHERE id=?", (event["delivery_id"],))
    assert delivery["status"] == "Sent" and delivery["provider_message_id"] == "synthetic-message"
    assert delivery["created_by"] == "owner@example.test"
    assert requests[0]["Subject"] == f"Payment reminder: invoice {invoice['number']}"
    assert invoice["due_date"] in requests[0]["TextBody"]
    assert requests[0]["Attachments"][0]["ContentType"] == "application/pdf"
    assert clients[0].is_closed
    repeat = client.post(url)
    assert repeat.status_code == 422 and "already sent" in repeat.json()["detail"]
    assert len(requests) == 1 and db.scalar("SELECT COUNT(*) FROM invoice_deliveries") == 1
    assert client.get(base + "/reminders/due").json()["email_connected"] is True


def test_api_email_status_masking_and_auth(automation_api, monkeypatch):
    client, _, _ = automation_api
    assert client.get("/email-status").json() == {"connected": False, "provider": "postmark", "from_email": ""}
    monkeypatch.setenv("FROM_EMAIL", "accounts@example.com")
    assert client.get("/email-status").json()["from_email"] == ""
    monkeypatch.setenv("POSTMARK_API_TOKEN", "synthetic-token")
    response = client.get("/email-status")
    assert response.json() == {"connected": True, "provider": "postmark", "from_email": "a•••@example.com"}
    assert "accounts@example.com" not in response.text
    assert client.get("/email-status", headers={"X-Test-User": ""}).status_code == 401


@pytest.mark.parametrize("changes", [
    {"interval_kind": "yearly"}, {"interval_kind": "custom_days"}, {"interval_days": 0},
    {"next_run_date": "not-a-date"}, {"end_date": "1900-01-01"}, {"next_run_date": None},
    {"name": None}, {"active": None}, {"unsupported": True},
])
def test_api_schedule_invalid_patch(automation_api, changes):
    client, base, invoice = automation_api
    schedule = create_api_schedule(client, base, invoice)
    url = base + "/invoice-schedules/" + schedule["id"]
    assert client.patch(url, json=changes).status_code == 422
    assert client.get(url).json() == schedule


def test_api_automation_tenant_scoping_and_roles(automation_api, db, ee_org, monkeypatch):
    client, base, invoice = automation_api
    schedule = create_api_schedule(client, base, invoice)
    other = f"/organisations/{ee_org['id']}"
    monkeypatch.setenv("POSTMARK_API_TOKEN", "synthetic-token")
    monkeypatch.setenv("FROM_EMAIL", "sender@example.invalid")
    assert client.get(other + "/invoice-schedules").json() == []
    assert client.get(other + "/reminders/due").json()["items"] == []
    assert client.post(other + "/invoice-schedules", json={"template_invoice_id": invoice["id"],
        "interval_kind": "monthly", "next_run_date": date.today().isoformat()}).status_code == 404
    requests = [
        ("GET", "/invoice-schedules/" + schedule["id"], None),
        ("PATCH", "/invoice-schedules/" + schedule["id"], {"active": False}),
        ("POST", "/invoice-schedules/" + schedule["id"] + "/run-now", None),
        ("POST", f"/invoices/{invoice['id']}/reminders/opt-out", {"reminders_disabled": True}),
        ("POST", f"/invoices/{invoice['id']}/reminders/0/send", None),
    ]
    for method, path, payload in requests:
        assert client.request(method, other + path, json=payload).status_code == 404
        assert client.request(method, base + path, json=payload,
                              headers={"X-Test-User": "outsider@example.invalid"}).status_code == 403
    with db.transaction() as tx:
        tx.execute("UPDATE memberships SET role='viewer' WHERE organisation_id=?", (invoice["organisation_id"],))
    for path in ("/invoice-schedules", "/invoice-schedules/" + schedule["id"], "/reminders/due"):
        assert client.get(base + path).status_code == 200
    for method, path, payload in requests[1:]:
        assert client.request(method, base + path, json=payload).status_code == 403
    assert client.post(base + "/invoice-schedules", json={"template_invoice_id": invoice["id"],
        "interval_kind": "monthly", "next_run_date": date.today().isoformat()}).status_code == 403


def test_api_automation_stage_validation_and_dependencies(automation_api, monkeypatch):
    client, base, invoice = automation_api
    monkeypatch.setenv("POSTMARK_API_TOKEN", "synthetic-token")
    monkeypatch.setenv("FROM_EMAIL", "sender@example.invalid")
    for stage in (-1, 3, "invalid"):
        assert client.post(base + f"/invoices/{invoice['id']}/reminders/{stage}/send").status_code == 422
    routes = [r for r in api.routes if "invoice-schedules" in r.path or "/reminders/" in r.path or r.path == "/email-status"]
    assert len(routes) == 9
    for route in routes:
        expected = current_user if route.methods == {"GET"} else require_csrf
        assert expected in [d.call for d in route.dependant.dependencies]


def test_api_auth_openapi_and_full_invoice_flow(tmp_path,monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_DB",str(tmp_path/"api.sqlite"))
    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH","true")
    reset_database_cache()
    from database import get_database
    get_database().migrate()
    client=TestClient(api)
    assert client.get("/organisations").status_code==401
    headers={"X-Test-User":"api@example.test"}
    response=client.post("/organisations",headers=headers,json={"name":"API Ltd","country_code":"UK","entity_type":"UK_COMPANY"})
    assert response.status_code==201,response.text
    org=response.json()
    accounts=client.get(f"/organisations/{org['id']}/accounts",headers=headers).json()
    taxes=client.get(f"/organisations/{org['id']}/tax-codes",headers=headers).json()
    contact=client.post(f"/organisations/{org['id']}/contacts",headers=headers,json={"name":"API Customer","country_code":"GB","contact_type":"customer"}).json()
    sale=next(x for x in accounts if x["system_role"]=="SALES")
    tax=next(x for x in taxes if x["code"]=="UK20")
    posting_date=get_database().scalar("SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1",(org["id"],))
    invoice=client.post(f"/organisations/{org['id']}/invoices",headers=headers,json={"contact_id":contact["id"],"issue_date":posting_date,"lines":[{"description":"API work","quantity":"1","unit_price":"100","account_id":sale["id"],"tax_code_id":tax["id"]}]}).json()
    issued=client.post(f"/organisations/{org['id']}/invoices/{invoice['id']}/issue",headers=headers).json()
    assert issued["number"]=="INV-000001"
    assert client.get(f"/organisations/{org['id']}/invoices/{invoice['id']}.pdf",headers=headers).content.startswith(b"%PDF")
    assert client.get("/openapi.json").json()["info"]["title"]=="FastAccounts API"


def test_api_cross_tenant_access_is_forbidden(tmp_path,monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_DB",str(tmp_path/"tenant-api.sqlite"));reset_database_cache()
    from database import get_database
    get_database().migrate();client=TestClient(api)
    owner={"X-Test-User":"owner@test.invalid"};other={"X-Test-User":"other@test.invalid"}
    org=client.post("/organisations",headers=owner,json={"name":"Private","country_code":"EE","entity_type":"EE_OU"}).json()
    assert client.get(f"/organisations/{org['id']}/accounts",headers=other).status_code==403


def test_tax_code_descriptions_follow_organisation_country(db, uk_org, ee_org, monkeypatch):
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    client = TestClient(api)
    headers = {"X-Test-User": "owner@example.test"}
    expected = {
        uk_org["id"]: {
            "UK20": "Standard rate 20%", "UK5": "Reduced rate 5%",
            "UK0": "Zero rated", "UKEX": "Exempt",
            "UKOS": "Outside scope", "UKRC": "Reverse charge",
        },
        ee_org["id"]: {
            "EE24": "Standardmäär 24%", "EE13": "Vähendatud määr 13%",
            "EE9": "Vähendatud määr 9%", "EE0": "Nullmääraga käive",
            "EEEX": "Maksuvaba käive", "EEOS": "Käibemaksu kohaldamisalast väljas",
            "EERC": "Pöördmaksustamine", "EEICS": "Ühendusesisene käive",
        },
    }
    for oid, descriptions in expected.items():
        response = client.get(f"/organisations/{oid}/tax-codes", headers=headers)
        assert response.status_code == 200
        assert {row["code"]: row["name"] for row in response.json()} == descriptions
