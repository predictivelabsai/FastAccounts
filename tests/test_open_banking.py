"""Synthetic consent, adapter, import and API coverage. No live bank requests."""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from banking import BankingService
from connectors.providers import OpenBankingProvider, ProviderError
from connectors.registry import PROVIDERS, connector_for, provider_metadata
from database import reset_database_cache
from documents import DocumentService
from integration_service import IntegrationService
from integrations import CATALOGUE
from open_banking import OpenBankingService

ACTOR = "owner@example.test"


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Live HTTP is forbidden in bank feed tests")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)


class FakeProvider:
    def __init__(self):
        self.access_token = "synthetic-access-token"
        self.status = "LN"
        self.account_ids = ["gc-account"]
        self.calls = []
        self.booked = [
            {"transactionId": "out-1", "transactionAmount": {"amount": "-12.34", "currency": "EUR"},
             "bookingDate": "2026-10-10", "valueDate": "2026-10-09", "creditorName": "Synthetic supplier",
             "debtorName": "Our own business", "remittanceInformationUnstructuredArray": ["Invoice", "A-1"]},
            {"transactionId": "in-1", "transactionAmount": {"amount": "50.00"}, "currencyCode": "EUR",
             "bookingDate": "2026-10-10", "debtorName": "Synthetic customer", "creditorName": "Our own business",
             "remittanceInformationUnstructured": "Receipt B-1"},
        ]

    def fetch_token(self, secret_id, secret_key):
        self.calls.append(("token", secret_id, secret_key))
        return {"access": self.access_token}

    def create_requisition(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"id": "synthetic-requisition", "status": "CR", "link": "https://consent.example.test/link"}

    def get_requisition(self, requisition_id):
        assert requisition_id == "synthetic-requisition"
        return {"id": requisition_id, "status": self.status, "accounts": self.account_ids}

    def get_account(self, account_id):
        return {"id": account_id, "iban": "EE-SYNTHETIC", "status": "READY"}

    def balances(self, account_id):
        return {"balances": [{"balanceAmount": {"amount": "100.00", "currency": "EUR"}, "balanceType": "interimAvailable"}]}

    def institutions(self, country):
        self.calls.append(("institutions", country))
        return [{"id": "synthetic-bank", "name": "Synthetic Bank"}]

    def transactions(self, account_id, **kwargs):
        self.calls.append(("transactions", account_id, kwargs))
        return {"transactions": {"booked": self.booked, "pending": [{"transactionId": "pending"}]}}


@pytest.fixture
def feed(db, ee_org):
    fake = FakeProvider()
    service = OpenBankingService(db, fake)
    service.configure(ee_org["id"], "synthetic-id", "synthetic-key", ACTOR)
    return service, fake, ee_org["id"]


def complete(service, oid):
    service.start_link(oid, institution_id="synthetic-bank", redirect_url="https://app.example.test/#integrations", actor=ACTOR)
    return service.complete_link(oid, actor=ACTOR)


def mapped(feed, db):
    service, fake, oid = feed
    complete(service, oid)
    bank = DocumentService(db).create_bank_account(oid, name="Synthetic feed bank", currency="EUR")
    service.link_account(oid, gocardless_account_id="gc-account", bank_account_id=bank["id"], actor=ACTOR)
    return service, fake, oid, bank


def test_registry_is_ready_and_catalogue_unchanged():
    assert PROVIDERS == {item.key for item in CATALOGUE}
    metadata = provider_metadata("open_banking")
    assert metadata["registry_status"] == "Adapter ready"
    assert [(field["name"], field["input_type"]) for field in metadata["credential_fields"]] == [
        ("secret_id", "secret"), ("secret_key", "secret")]
    assert isinstance(connector_for("open_banking"), OpenBankingProvider)
    assert not connector_for("open_banking").check().live


def test_configure_and_link_encrypt_secrets_and_token(feed, db):
    service, fake, oid = feed
    result = service.start_link(oid, institution_id="synthetic-bank", redirect_url="https://app.example.test/", actor=ACTOR)
    assert result == {"link": "https://consent.example.test/link", "requisition_id": "synthetic-requisition"}
    assert fake.calls == [("token", "synthetic-id", "synthetic-key"),
                          ("create", {"redirect": "https://app.example.test/", "institution_id": "synthetic-bank", "reference": oid})]
    private = service.integrations.connection_for_provider(oid, "open_banking")
    assert private["config"]["requisition_id"] == result["requisition_id"]
    assert private["status"] == "Configured"
    encrypted = private["config"]["access_token_encrypted"]
    assert service.integrations.vault.decrypt(encrypted) == {"access_token": fake.access_token}
    storage = db.one("SELECT * FROM integration_connections WHERE organisation_id=?", (oid,))
    assert "synthetic-key" not in json.dumps(storage)
    assert fake.access_token not in json.dumps(storage)
    public = service.integrations.connections(oid)
    assert encrypted not in json.dumps(public)
    assert fake.access_token not in json.dumps(public)
    assert "synthetic-key" not in json.dumps(public)
    assert "synthetic-key" not in str(db.rows("SELECT * FROM audit_events WHERE organisation_id=?", (oid,)))


@pytest.mark.parametrize("status,accounts,expected", [("LN", ["gc-account"], "Connected"),
    ("LN", [], "Configured"), ("GA", ["gc-account"], "Configured"), ("EX", [], "Reauth Required"), ("RJ", [], "Reauth Required")])
def test_complete_requires_accepted_requisition_and_accounts(feed, status, accounts, expected):
    service, fake, oid = feed
    fake.status, fake.account_ids = status, accounts
    result = complete(service, oid)
    assert result["status"] == expected
    assert result["config"]["account_ids"] == accounts
    assert result["config"]["requisition_status"] == status


def test_link_account_tenancy_and_requisition_membership(feed, db, uk_org):
    service, fake, oid = feed
    bank = DocumentService(db).create_bank_account(uk_org["id"], name="Other tenant", currency="GBP")
    complete(service, oid)
    with pytest.raises(ValueError, match="not in this organisation"):
        service.link_account(oid, gocardless_account_id="gc-account", bank_account_id=bank["id"], actor=ACTOR)
    with pytest.raises(ValueError, match="completed requisition"):
        service.link_account(oid, gocardless_account_id="unknown-account", bank_account_id=bank["id"], actor=ACTOR)
    with pytest.raises(KeyError):
        service.pull(uk_org["id"], gocardless_account_id="gc-account", actor=ACTOR)
    with pytest.raises(ValueError, match="Link this GoCardless"):
        service.pull(oid, gocardless_account_id="gc-account", actor=ACTOR)


def test_pull_maps_signed_amounts_booked_fields_and_is_idempotent(feed, db, monkeypatch):
    service, fake, oid, bank = mapped(feed, db)
    captured = []
    original = BankingService._import
    def capture(self, *args):
        captured.append(args)
        return original(self, *args)
    monkeypatch.setattr(BankingService, "_import", capture)
    first = service.pull(oid, gocardless_account_id="gc-account", actor=ACTOR)
    second = service.pull(oid, gocardless_account_id="gc-account", actor=ACTOR)
    assert first["imported"] == 2 and first["skipped"] == 0
    assert second["imported"] == 0 and second["skipped"] == 2 and second["duplicate"]
    assert captured[0][0:2] == (oid, bank["id"])
    assert captured[0][3] == "open_banking"
    assert isinstance(captured[0][4][0]["amount"], Decimal)
    assert fake.calls[-1] == ("transactions", "gc-account", {"date_from": (date.today() - timedelta(days=90)).isoformat()})
    rows = {row["external_id"]: row for row in db.rows("SELECT * FROM bank_transactions WHERE organisation_id=?", (oid,))}
    outgoing, incoming = rows["out-1"], rows["in-1"]
    assert Decimal(str(outgoing["amount"])) == Decimal("-12.34")  # bank credit (C)
    assert Decimal(str(incoming["amount"])) == Decimal("50.00")  # bank debit (D)
    assert outgoing["counterparty"] == "Synthetic supplier" and incoming["counterparty"] == "Synthetic customer"
    assert outgoing["reference"] == "Invoice A-1" and incoming["reference"] == "Receipt B-1"
    assert outgoing["value_date"] == "2026-10-09" and outgoing["currency"] == "EUR"
    assert json.loads(outgoing["raw_payload"]) == fake.booked[0]
    assert db.scalar("SELECT format FROM bank_imports WHERE id=?", (first["id"],)) == "open_banking"
    fake.booked.append({**fake.booked[1], "transactionId": "in-2"})
    third = service.pull(oid, gocardless_account_id="gc-account", actor=ACTOR)
    assert third["imported"] == 1 and third["skipped"] == 2 and not third["duplicate"]


def test_accounts_balances_mapping_and_country(feed, db):
    service, fake, oid, bank = mapped(feed, db)
    accounts = service.accounts(oid)
    assert accounts[0]["bank_account_id"] == bank["id"]
    assert accounts[0]["gocardless_account_id"] == "gc-account"
    assert accounts[0]["balances"][0]["balanceAmount"]["amount"] == "100.00"
    assert service.institutions("UK", organisation_id=oid)[0]["id"] == "synthetic-bank"
    assert fake.calls[-1] == ("institutions", "GB")
    with pytest.raises(ValueError):
        service.institutions("invalid", organisation_id=oid)


def test_config_cannot_forge_consent_and_disconnected_feed_cannot_pull(feed, db):
    service, fake, oid, bank = mapped(feed, db)
    service.integrations.disconnect(oid, "open_banking", actor=ACTOR)
    with pytest.raises(ValueError, match="disconnected"):
        service.pull(oid, gocardless_account_id="gc-account", actor=ACTOR)
    configured = service.integrations.configure(oid, "open_banking", actor=ACTOR,
        credentials={"secret_id": "synthetic-id", "secret_key": "synthetic-key"},
        config={"requisition_status": "LN", "account_ids": ["gc-account"]})
    assert configured["config"] == {} and configured["status"] == "Configured"


def test_token_contract_lazy_bearer_and_all_endpoint_shapes():
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path.endswith("/token/new/"):
            assert json.loads(request.content) == {"secret_id": "synthetic-id", "secret_key": "synthetic-key"}
            assert request.headers["content-type"] == "application/json"
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"access": "synthetic-access"})
        assert request.headers["authorization"] == "Bearer synthetic-access"
        return httpx.Response(200, json=[] if "institutions" in request.url.path else {})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenBankingProvider(secret_id="synthetic-id", secret_key="synthetic-key", client=client)
        provider.institutions("EE")
        provider.create_requisition(redirect="https://app.example.test/", institution_id="bank", reference="org")
        provider.get_requisition("req")
        provider.get_account("acc")
        provider.balances("acc")
        provider.transactions("acc", date_from="2026-07-13")
    assert len(seen) == 7
    assert seen[1].url.params["country"] == "EE"
    assert json.loads(seen[2].content) == {"redirect": "https://app.example.test/", "institution_id": "bank", "reference": "org", "user_language": "EN"}
    assert [request.url.path for request in seen[3:]] == ["/api/v2/requisitions/req/", "/api/v2/accounts/acc/",
        "/api/v2/accounts/acc/balances/", "/api/v2/accounts/acc/transactions/"]
    assert seen[-1].url.params["date_from"] == "2026-07-13"


def test_token_new_refresh_only_response():
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path.endswith("/new/"):
            return httpx.Response(200, json={"refresh": "synthetic-refresh"})
        assert json.loads(request.content) == {"refresh": "synthetic-refresh"}
        return httpx.Response(200, json={"access": "synthetic-refreshed-access"})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenBankingProvider(client=client)
        provider.fetch_token("synthetic-id", "synthetic-key")
        assert provider.access_token == "synthetic-refreshed-access"
    assert seen[-1].url.path == "/api/v2/token/refresh/"


@pytest.mark.parametrize("retry_status", [200, 401])
def test_401_refresh_retries_exactly_once(retry_status):
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path.endswith("/token/new/"):
            return httpx.Response(200, json={"access": "refreshed-synthetic-token"})
        if len(seen) == 1:
            assert request.headers["authorization"] == "Bearer old-synthetic-token"
            return httpx.Response(401)
        assert request.headers["authorization"] == "Bearer refreshed-synthetic-token"
        return httpx.Response(retry_status, json=[])
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenBankingProvider("old-synthetic-token", secret_id="id", secret_key="key", client=client)
        if retry_status == 401:
            with pytest.raises(ProviderError, match="HTTP 401"):
                provider.institutions("EE")
        else:
            assert provider.institutions("EE") == []
    assert len(seen) == 3


def test_non_401_never_refreshes_and_missing_credentials_never_send_requests():
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(403)
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="required"):
            OpenBankingProvider(client=client).institutions("EE")
        with pytest.raises(ProviderError, match="HTTP 403"):
            OpenBankingProvider("token", secret_id="id", secret_key="key", client=client).institutions("EE")
    assert len(seen) == 1


@pytest.fixture
def route_client(feed, db, monkeypatch):
    import api_app
    service, fake, oid = feed
    monkeypatch.setenv("FASTACCOUNTS_DB", db.path)
    monkeypatch.setenv("DB_URL", "")
    reset_database_cache()
    monkeypatch.setattr(api_app, "OpenBankingService", lambda: service)
    try:
        with TestClient(SessionMiddleware(api_app.api, secret_key="synthetic-session-key"),
                        headers={"X-Test-User": ACTOR}) as client:
            yield client, service, fake, f"/organisations/{oid}/integrations/open_banking"
    finally:
        reset_database_cache()


def test_routes_consent_mapping_pull_and_tenancy(route_client, db, uk_org):
    client, service, fake, base = route_client
    oid = base.split('/')[2]
    bank = DocumentService(db).create_bank_account(oid, name="Route bank", currency="EUR")
    response = client.post(base + "/link", json={"institution_id": "bank", "redirect_url": "https://app.example.test/"})
    assert response.status_code == 200 and set(response.json()) == {"link", "requisition_id"}
    response = client.post(base + "/complete-link")
    assert response.status_code == 200 and response.json()["status"] == "Connected"
    assert fake.access_token not in response.text and "access_token_encrypted" not in response.text
    assert client.get(base + "/institutions?country=EE").json()[0]["id"] == "synthetic-bank"
    assert client.get(base + "/accounts").json()[0]["bank_account_id"] is None
    mapping = {"gocardless_account_id": "gc-account", "bank_account_id": bank["id"]}
    assert client.post(base + "/link-account", json=mapping).json() == mapping
    assert client.post(base + "/pull", json={"gocardless_account_id": "gc-account"}).json()["imported"] == 2
    assert client.post(base + "/pull", json={"gocardless_account_id": "gc-account"}).json()["skipped"] == 2
    other = f"/organisations/{uk_org['id']}/integrations/open_banking"
    assert client.post(other + "/pull", json={"gocardless_account_id": "gc-account"}).status_code == 404
    assert client.post(base + "/link-account", json={**mapping, "gocardless_account_id": "unknown"}).status_code == 422
    assert client.post(base + "/link", json={}).status_code == 422
    client.headers["X-Test-User"] = "outsider@example.test"
    assert client.get(base + "/accounts").status_code == 403
    assert client.post(base + "/pull", json={"gocardless_account_id": "gc-account"}).status_code == 403


def test_viewer_reads_but_cannot_write_and_csrf_is_required(route_client, db, monkeypatch):
    import api_app
    client, service, fake, base = route_client
    oid = base.split('/')[2]
    complete(service, oid)
    with db.transaction() as tx:
        tx.execute("UPDATE memberships SET role='viewer' WHERE organisation_id=?", (oid,))
    assert client.get(base + "/accounts").status_code == 200
    assert client.get(base + "/institutions?country=EE").status_code == 200
    for suffix, payload in [("link", {"institution_id": "bank", "redirect_url": "https://app.example.test/"}),
            ("complete-link", None), ("link-account", {"gocardless_account_id": "gc-account", "bank_account_id": "bank"}),
            ("pull", {"gocardless_account_id": "gc-account"})]:
        assert client.post(base + "/" + suffix, json=payload).status_code == 403
    with db.transaction() as tx:
        tx.execute("UPDATE memberships SET role='owner' WHERE organisation_id=?", (oid,))
    api_app.api.dependency_overrides[api_app.current_user] = lambda: api_app.User(email=ACTOR)
    monkeypatch.setenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "false")
    try:
        assert client.post(base + "/complete-link").status_code == 403
        token = client.get("/csrf").json()["csrf_token"]
        assert client.post(base + "/complete-link", headers={"X-CSRF-Token": token}).status_code == 200
    finally:
        api_app.api.dependency_overrides.clear()

@pytest.mark.parametrize("http_status,expected", [(401, "Reauth Required"), (403, "Reauth Required"), (500, "Error")])
def test_failed_pull_sets_safe_connection_status_without_importing(feed, db, monkeypatch, http_status, expected):
    service, fake, oid, bank = mapped(feed, db)
    request = httpx.Request("GET", "https://bank.example.test/transactions")
    response = httpx.Response(http_status, request=request)
    def fail(*args, **kwargs):
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as cause:
            raise ProviderError("Synthetic provider failure") from cause
    monkeypatch.setattr(fake, "transactions", fail)
    with pytest.raises(ValueError, match="GoCardless request failed"):
        service.pull(oid, gocardless_account_id="gc-account", actor=ACTOR)
    assert service.integrations.connections(oid)[0]["status"] == expected
    assert db.scalar("SELECT COUNT(*) FROM bank_imports WHERE organisation_id=?", (oid,)) == 0


def test_real_factory_restores_encrypted_token_across_service_instances(feed, db, monkeypatch):
    from dataclasses import replace
    from connectors.registry import REGISTRY
    service, fake, oid = feed
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path.endswith("/token/new/"):
            return httpx.Response(200, json={"access": "synthetic-stored-token"})
        assert request.headers["authorization"] == "Bearer synthetic-stored-token"
        if request.url.path.endswith("/requisitions/"):
            return httpx.Response(201, json={"id": "synthetic-requisition", "link": "https://consent.example.test/link"})
        if "/requisitions/" in request.url.path:
            return httpx.Response(200, json={"status": "LN", "accounts": ["gc-account"]})
        return httpx.Response(200, json={"transactions": {"booked": fake.booked}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        def factory(credentials, config):
            return OpenBankingProvider(secret_id=credentials["secret_id"], secret_key=credentials["secret_key"], client=client)
        monkeypatch.setitem(REGISTRY, "open_banking", replace(REGISTRY["open_banking"], factory=factory))
        service = OpenBankingService(db)
        service.start_link(oid, institution_id="bank", redirect_url="https://app.example.test/", actor=ACTOR)
        service = OpenBankingService(db)
        service.complete_link(oid, actor=ACTOR)
        bank = DocumentService(db).create_bank_account(oid, name="Factory bank", currency="EUR")
        service.link_account(oid, gocardless_account_id="gc-account", bank_account_id=bank["id"], actor=ACTOR)
        assert OpenBankingService(db).pull(oid, gocardless_account_id="gc-account", actor=ACTOR)["imported"] == 2
    assert sum(request.url.path.endswith("/token/new/") for request in seen) == 1


def test_credentials_check_does_not_connect_without_consent(feed, monkeypatch):
    from dataclasses import replace
    from connectors.base import ConnectorResult
    from connectors.registry import REGISTRY
    service, fake, oid = feed
    fake.check = lambda: ConnectorResult("open_banking", "check", True, True, "Synthetic credential check")
    monkeypatch.setitem(REGISTRY, "open_banking", replace(REGISTRY["open_banking"], factory=lambda credentials, config: fake))
    result = service.integrations.test_connection(oid, "open_banking", credentials={}, config={}, actor=ACTOR)
    assert result.ok
    assert service.integrations.connections(oid)[0]["status"] == "Configured"


def test_new_card_copy_exists_in_all_four_locales():
    from web import i18n
    keys = {"Connect bank", "I've approved at the bank", "Linked bank accounts", "Pull transactions",
            "Bank transactions imported: {imported}; skipped: {skipped}", "Secret ID", "Secret key"}
    for lang in ("en", "et", "lt", "lv"):
        assert keys <= i18n.catalog(lang)["workspace"].keys()
    assert i18n.catalog("et")["workspace"]["Pull transactions"] == "Impordi tehingud"


def worker_for(service, db, monkeypatch):
    import automation
    monkeypatch.setattr(automation, "OpenBankingService", lambda database: service)
    return automation.AutomationService(db)


def test_daily_worker_due_today_and_overdue_catchup(feed, db, monkeypatch):
    service, fake, oid, bank = mapped(feed, db)
    worker = worker_for(service, db, monkeypatch)
    day = date.today()
    result = worker.worker_tick(today=day)
    assert result["bank_feeds"][0]["status"] == "Success"
    assert result["bank_feeds"][0]["summary"]["imported"] == 2
    assert worker.worker_tick(today=day)["bank_feeds"] == []
    # One import covers several missed days; no daily network replay is needed.
    late = day + timedelta(days=4)
    result = worker.worker_tick(today=late)
    assert len(result["bank_feeds"]) == 1
    assert result["bank_feeds"][0]["summary"]["skipped"] == 2
    row = service.pull_status(oid)["schedules"][0]
    assert row["next_run_date"] == (late + timedelta(days=1)).isoformat()
    assert row["last_run_date"] == late.isoformat()
    assert row["last_result"] == "Success" and row["last_error_message"] is None
    assert row["last_pull_at"]
    assert len([c for c in fake.calls if c[0] == "transactions"]) == 2
    assert db.scalar("SELECT COUNT(*) FROM bank_transactions WHERE organisation_id=?", (oid,)) == 2
    assert db.scalar("SELECT imported_by FROM bank_imports WHERE organisation_id=? LIMIT 1", (oid,)) == "system"


def test_future_and_already_successful_feed_are_not_pulled(feed, db):
    service, fake, oid, bank = mapped(feed, db)
    day = date.today()
    assert service.pull_due(oid, today=day - timedelta(days=1)) == []
    service.pull_due(oid, today=day)
    with db.transaction() as tx:
        tx.execute("UPDATE bank_feed_schedules SET next_run_date=? WHERE organisation_id=?", (day.isoformat(), oid))
    assert service.pull_due(oid, today=day) == []
    assert len([c for c in fake.calls if c[0] == "transactions"]) == 1


def test_worker_discovers_existing_mappings_and_respects_tenants(feed, db, uk_org):
    service, fake, oid, bank = mapped(feed, db)
    with db.transaction() as tx:
        tx.execute("DELETE FROM bank_feed_schedules WHERE organisation_id=?", (oid,))
    assert service.pull_due(uk_org["id"]) == []
    assert service.pull_status(uk_org["id"])["schedules"] == []
    assert service.pull_due(oid)[0]["status"] == "Success"
    # A mapping into another tenant cannot create an active schedule or import.
    other_bank = DocumentService(db).create_bank_account(uk_org["id"], name="Other tenant", currency="GBP")
    connection = service.integrations.connection_for_provider(oid, "open_banking")
    config = dict(connection["config"])
    config["account_mappings"] = {"gc-account": other_bank["id"]}
    service._save(connection, config, ACTOR)
    assert service.pull_due(oid, today=date.today() + timedelta(days=1)) == []
    assert service.pull_status(oid)["schedules"][0]["active"] == 0
    assert db.scalar("SELECT COUNT(*) FROM bank_transactions WHERE organisation_id=?", (uk_org["id"],)) == 0


@pytest.mark.parametrize("http_status,expected", [(500, "Error"), (401, "Reauth Required"), (403, "Reauth Required")])
def test_worker_captures_provider_error_and_surfaces_reauth(feed, db, monkeypatch, http_status, expected):
    service, fake, oid, bank = mapped(feed, db)
    original = fake.transactions
    def fail(*args, **kwargs):
        request = httpx.Request("GET", "https://bank.example.test/transactions")
        try:
            httpx.Response(http_status, request=request).raise_for_status()
        except httpx.HTTPStatusError as cause:
            raise ProviderError("synthetic-secret") from cause
    monkeypatch.setattr(fake, "transactions", fail)
    worker = worker_for(service, db, monkeypatch)
    day = date.today()
    result = worker.worker_tick(today=day)
    assert result["bank_feeds"][0]["status"] == expected
    status = service.pull_status(oid)
    assert status["connection_status"] == expected
    assert status["schedules"][0]["last_result"] == expected
    assert "synthetic-secret" not in json.dumps(status)
    assert db.scalar("SELECT COUNT(*) FROM bank_transactions WHERE organisation_id=?", (oid,)) == 0
    assert worker.worker_tick(today=day)["bank_feeds"] == []
    monkeypatch.setattr(fake, "transactions", original)
    next_result = worker.worker_tick(today=day + timedelta(days=1))["bank_feeds"][0]
    if expected == "Error":
        assert next_result["status"] == "Success"
    else:
        assert next_result["status"] == "Reauth Required"
        assert not [c for c in fake.calls if c[0] == "transactions"]
        complete(service, oid)
        service.link_account(oid, gocardless_account_id="gc-account", bank_account_id=bank["id"], actor=ACTOR)
        assert worker.worker_tick(today=day + timedelta(days=2))["bank_feeds"][0]["status"] == "Success"


def test_account_failure_does_not_break_other_accounts(feed, db, monkeypatch):
    service, fake, oid, bank = mapped(feed, db)
    fake.account_ids.append("gc-second")
    service.complete_link(oid, actor=ACTOR)
    service.link_account(oid, gocardless_account_id="gc-second", bank_account_id=bank["id"], actor=ACTOR)
    original = fake.transactions
    def transactions(account_id, **kwargs):
        if account_id == "gc-account":
            raise RuntimeError("Synthetic unexpected error with private payload")
        return original(account_id, **kwargs)
    monkeypatch.setattr(fake, "transactions", transactions)
    results = worker_for(service, db, monkeypatch).worker_tick()["bank_feeds"]
    assert [r["status"] for r in results] == ["Error", "Success"]
    assert [r["last_result"] for r in service.pull_status(oid)["schedules"]] == ["Error", "Success"]
    assert "private payload" not in json.dumps(results)


def test_feed_failure_does_not_break_other_organisations(feed, db, uk_org, monkeypatch):
    service, fake, oid, bank = mapped(feed, db)
    other = OpenBankingService(db, FakeProvider())
    other.configure(uk_org["id"], "other-id", "other-key", ACTOR)
    complete(other, uk_org["id"])
    other_bank = DocumentService(db).create_bank_account(uk_org["id"], name="Other bank", currency="EUR")
    other.link_account(uk_org["id"], gocardless_account_id="gc-account", bank_account_id=other_bank["id"], actor=ACTOR)
    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic failure")
    monkeypatch.setattr(fake, "transactions", fail)
    import automation
    class Feeds:
        def pull_due(self, org_id, **kwargs):
            return (service if org_id == oid else other).pull_due(org_id, **kwargs)
    monkeypatch.setattr(automation, "OpenBankingService", lambda database: Feeds())
    results = automation.AutomationService(db).worker_tick()["bank_feeds"]
    assert {r["organisation_id"]: r["status"] for r in results} == {oid: "Error", uk_org["id"]: "Success"}


def test_concurrent_bank_feed_claim_pulls_once(feed, db):
    from concurrent.futures import ThreadPoolExecutor
    service, fake, oid, bank = mapped(feed, db)
    schedule = db.one("SELECT * FROM bank_feed_schedules WHERE organisation_id=?", (oid,))
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: service._pull_scheduled(schedule, date.today()), range(2)))
    assert sorted(r["status"] for r in results) == ["Skipped", "Success"]
    assert len([c for c in fake.calls if c[0] == "transactions"]) == 1


@pytest.mark.parametrize("status", ["Disconnected", "Configured"])
def test_unconnected_feeds_never_pull(feed, db, status):
    service, fake, oid, bank = mapped(feed, db)
    with db.transaction() as tx:
        tx.execute("UPDATE integration_connections SET status=? WHERE organisation_id=?", (status, oid))
    assert all(r["status"] == "Skipped" for r in service.pull_due(oid))
    assert not [c for c in fake.calls if c[0] == "transactions"]


def test_pull_status_route_is_local_safe_and_authorised(route_client, db):
    client, service, fake, base = route_client
    oid = base.split('/')[2]
    complete(service, oid)
    bank = DocumentService(db).create_bank_account(oid, name="Local status bank", currency="EUR")
    service.link_account(oid, gocardless_account_id="gc-account", bank_account_id=bank["id"], actor=ACTOR)
    service.pull_due(oid)
    calls = list(fake.calls)
    response = client.get(base + "/pull-status")
    assert response.status_code == 200 and response.json()["schedules"][0]["last_result"] == "Success"
    assert fake.calls == calls
    assert "encrypted" not in response.text and "synthetic-access-token" not in response.text
    with db.transaction() as tx:
        tx.execute("UPDATE integration_connections SET status='Reauth Required' WHERE organisation_id=?", (oid,))
        tx.execute("UPDATE memberships SET role='viewer' WHERE organisation_id=?", (oid,))
    assert client.get(base + "/pull-status").json()["connection_status"] == "Reauth Required"
    client.headers["X-Test-User"] = "outsider@example.test"
    assert client.get(base + "/pull-status").status_code == 403


def test_interrupted_bank_feed_attempt_is_retried_next_day(feed, db):
    service, fake, oid, bank = mapped(feed, db)
    day = date.today()
    with db.transaction() as tx:
        tx.execute("UPDATE bank_feed_schedules SET next_run_date=?,last_run_date=?,last_result='Running' WHERE organisation_id=?",
                   ((day + timedelta(days=1)).isoformat(), day.isoformat(), oid))
    assert service.pull_due(oid, today=day) == []
    assert service.pull_due(oid, today=day + timedelta(days=1))[0]['status'] == 'Success'
    assert len([c for c in fake.calls if c[0] == 'transactions']) == 1


def test_inactive_bank_feed_is_preserved_until_explicit_link(feed, db):
    service, fake, oid, bank = mapped(feed, db)
    with db.transaction() as tx:
        tx.execute('UPDATE bank_feed_schedules SET active=0 WHERE organisation_id=?', (oid,))
    assert service.pull_due(oid) == []
    assert service.pull_status(oid)['schedules'][0]['active'] == 0
    assert not [c for c in fake.calls if c[0] == 'transactions']
    service.link_account(oid, gocardless_account_id='gc-account', bank_account_id=bank['id'], actor=ACTOR)
    assert service.pull_due(oid)[0]['status'] == 'Success'
