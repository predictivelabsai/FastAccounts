from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from cryptography.fernet import Fernet

from connectors.providers import (
    BambooHRProvider,
    EMTAExportProvider,
    FastHRProvider,
    HMRCProvider,
    MeritProvider,
    SmartAccountsProvider,
    OpenBankingProvider,
    PersonioProvider,
    ProviderError,
    QuickBooksProvider,
    XeroProvider,
)
from connectors.registry import connector_for
from integration_service import CredentialVault, IntegrationService


PERSONIO_AUTH_RESPONSE = {
    "success": True,
    "data": {"token": "synthetic-personio-token", "expires_in": 86400, "scope": "employees"},
}


def _personio_attribute(label, value, value_type="standard", universal_id=None):
    return {
        "label": label,
        "value": value,
        "type": value_type,
        "universal_id": universal_id,
    }


BAMBOO_DIRECTORY_RESPONSE = {
    "fields": [
        {"id": "firstName", "name": "First Name", "type": "text", "legacyName": "firstName"},
        {"id": "lastName", "name": "Last Name", "type": "text"},
        {"id": "workEmail", "name": "Work Email", "type": "text"},
        {"id": "homeEmail", "name": "Home Email", "type": "text"},
        {"id": "jobTitle", "name": "Job Title", "type": "text"},
        {"id": "location", "name": "Location", "type": "text"},
        {"id": "status", "name": "Status", "type": "text"},
        {"id": "customSalary", "name": "Monthly salary", "type": "currency"},
    ],
    "employees": [
        {
            "id": "b-1", "firstName": "  Ada ", "lastName": " Lovelace  ",
            "workEmail": "ada.work@example.test", "homeEmail": "ada.home@example.test",
            "jobTitle": "Engineer", "location": "Tallinn", "status": "Active",
            "customSalary": "2400.125",
        },
        {
            "id": "b-2", "firstName": "Grace", "lastName": "Hopper",
            "workEmail": "", "homeEmail": "grace.home@example.test",
            "jobTitle": "Admiral", "status": "Inactive", "customSalary": None,
        },
        {
            "id": "b-3", "firstName": "Linus", "lastName": "Torvalds",
            "workEmail": None, "homeEmail": None, "location": "Helsinki",
        },
        {"id": "b-4", "firstName": " ", "lastName": None, "workEmail": "skip@example.test"},
    ],
}


def test_credential_encryption_and_redacted_connection(db, uk_org):
    vault=CredentialVault(Fernet.generate_key().decode(),version=7)
    service=IntegrationService(db,vault)
    row=service.configure(uk_org["id"],"xero",credentials={"refresh_token":"secret"},config={"direction":"import"},actor="a",external_tenant_id="tenant")
    assert "credentials" not in row and row["encryption_key_version"]==7
    loaded=service.connection(row["id"],include_credentials=True)
    assert loaded["credentials"]=={"refresh_token":"secret"}
    raw=db.one("SELECT encrypted_credentials FROM integration_connections WHERE id=?",(row["id"],))["encrypted_credentials"]
    assert "secret" not in raw


def test_configure_validates_against_complete_registry(db, uk_org):
    service = IntegrationService(db, CredentialVault(Fernet.generate_key().decode()))
    connection = service.configure(
        uk_org["id"], "personio", credentials={"placeholder": "secret"},
        config={"direction": "import"}, actor="owner@example.test",
    )
    assert connection["provider"] == "personio"
    assert connection["status"] == "Configured"
    with pytest.raises(ValueError, match="Unknown integration provider"):
        service.configure(
            uk_org["id"], "made-up-provider", credentials={}, config={}, actor="owner@example.test",
        )


@pytest.mark.parametrize(
    ("provider", "credentials", "config", "provider_type"),
    [
        (
            "personio",
            {"client_id": "synthetic-client-id", "client_secret": "personio-vault-secret"},
            {"salary_attribute": "dynamic_12345"},
            PersonioProvider,
        ),
        (
            "bamboohr",
            {"subdomain": "synthetic-company", "api_key": "bamboo-vault-secret"},
            {"salary_field_id": "customSalary"},
            BambooHRProvider,
        ),
        (
            "smartaccounts",
            {"api_key": "synthetic-sa-public", "secret_key": "synthetic-sa-secret"},
            {},
            SmartAccountsProvider,
        ),
    ],
)
def test_documented_contract_credentials_round_trip_only_through_vault(
    db, uk_org, provider, credentials, config, provider_type,
):
    vault = CredentialVault(Fernet.generate_key().decode())
    service = IntegrationService(db, vault)
    public = service.configure(
        uk_org["id"], provider, credentials=credentials, config=config,
        actor="owner@example.test",
    )

    assert "credentials" not in public
    assert all(value not in str(public) for value in credentials.values())
    stored = service.connection(public["id"], include_credentials=True)
    assert stored["credentials"] == credentials
    connector = connector_for(provider, credentials=stored["credentials"], config=stored["config"])
    assert isinstance(connector, provider_type)
    encrypted = db.one(
        "SELECT encrypted_credentials FROM integration_connections WHERE id=?", (public["id"],),
    )["encrypted_credentials"]
    assert all(value not in encrypted for value in credentials.values())


def test_mapping_sync_conflict_and_outbox_are_explicit(db, uk_org):
    service=IntegrationService(db,CredentialVault(Fernet.generate_key().decode()))
    mapping=service.map_record(uk_org["id"],provider="xero",object_type="invoice",local_id="l1",external_id="e1",ownership="fastaccounts",direction="export")
    assert mapping["ownership"]=="fastaccounts"
    run=service.start_sync(uk_org["id"],provider="xero",direction="import",object_type="invoices")
    service.conflict(run["id"],provider="xero",object_type="invoice",conflict_type="both_changed",local_id="l1",external_id="e1")
    assert db.one("SELECT status FROM sync_runs WHERE id=?",(run["id"],))["status"]=="Review Required"
    first=service.enqueue(uk_org["id"],topic="invoice.export",payload={"id":"l1"},idempotency_key="one")
    assert service.enqueue(uk_org["id"],topic="invoice.export",payload={"id":"l1"},idempotency_key="one")["id"]==first["id"]


def test_merit_hmac_signature_exact_body_and_retry():
    seen=[]
    def handler(request):
        seen.append(request)
        if len(seen)==1:return httpx.Response(429,headers={"Retry-After":"0"})
        return httpx.Response(200,json={"InvoiceId":"x"})
    provider=MeritProvider("api-id","api-key",clock=lambda:datetime(2026,8,10,12,30,0,tzinfo=timezone.utc),client=httpx.Client(transport=httpx.MockTransport(handler)),sleep=lambda _x:None)
    result=provider.create_invoice({"InvoiceNo":"INV-1"})
    assert result["InvoiceId"]=="x" and len(seen)==2
    assert seen[-1].url.params["timestamp"]=="20260810123000"
    assert base64.b64decode(seen[-1].url.params["signature"])


def test_quickbooks_xero_and_open_banking_request_shapes():
    requests=[]
    def handler(request):
        requests.append(request)
        if "institutions" in str(request.url): return httpx.Response(200,json=[])
        return httpx.Response(200,json={"ok":True})
    client=httpx.Client(transport=httpx.MockTransport(handler))
    QuickBooksProvider("token","realm",client=client).create_invoice({"Line":[]},idempotency_key="same")
    XeroProvider("token","tenant",client=client).create_invoice({"Type":"ACCREC"},idempotency_key="same")
    OpenBankingProvider("token",client=client).institutions("GB")
    assert requests[0].headers["request-id"]=="same" and "/v3/company/realm/invoice" in str(requests[0].url)
    assert requests[1].headers["idempotency-key"]=="same" and requests[1].headers["xero-tenant-id"]=="tenant"
    assert requests[2].url.params["country"]=="GB"


@pytest.mark.parametrize(
    ("provider_factory", "expected_path"),
    [
        (
            lambda client: QuickBooksProvider(
                "synthetic-qbo-token", "synthetic-realm", client=client,
            ),
            "/v3/company/synthetic-realm/query",
        ),
        (
            lambda client: XeroProvider(
                "synthetic-xero-token", "synthetic-tenant", client=client,
            ),
            "/api.xro/2.0/Organisation",
        ),
        (
            lambda client: MeritProvider(
                "synthetic-api-id",
                "synthetic-api-key",
                clock=lambda: datetime(2026, 10, 9, 12, 30, 0, tzinfo=timezone.utc),
                client=client,
            ),
            "/api/v2/getpayments",
        ),
    ],
)
def test_finance_provider_checks_succeed_with_expected_request(provider_factory, expected_path):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    provider = provider_factory(httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.check()

    assert result.ok and result.live
    assert result.provider == provider.key and result.operation == "check"
    assert seen[0].method == "GET"
    assert seen[0].url.path == expected_path
    assert all(secret not in result.message for secret in (
        "synthetic-qbo-token",
        "synthetic-xero-token",
        "synthetic-tenant",
        "synthetic-api-id",
        "synthetic-api-key",
    ))

    if provider.key == "quickbooks":
        assert seen[0].url.host == "sandbox-quickbooks.api.intuit.com"
        assert seen[0].url.params["query"] == "select * from Account maxresults 1"
        assert seen[0].headers["authorization"] == "Bearer synthetic-qbo-token"
    elif provider.key == "xero":
        assert seen[0].headers["authorization"] == "Bearer synthetic-xero-token"
        assert seen[0].headers["xero-tenant-id"] == "synthetic-tenant"
    else:
        assert seen[0].url.host == "aktiva.merit.ee"
        assert seen[0].url.params["apiId"] == "synthetic-api-id"
        assert seen[0].url.params["timestamp"] == "20261009123000"
        expected_signature = base64.b64encode(hmac.new(
            b"synthetic-api-key",
            b"synthetic-api-id20261009123000",
            hashlib.sha256,
        ).digest()).decode()
        assert seen[0].url.params["signature"] == expected_signature


@pytest.mark.parametrize(
    "provider_factory",
    [
        lambda client: QuickBooksProvider(
            "do-not-leak-qbo-token", "do-not-leak-realm", client=client,
        ),
        lambda client: XeroProvider(
            "do-not-leak-xero-token", "do-not-leak-tenant", client=client,
        ),
        lambda client: MeritProvider(
            "do-not-leak-api-id", "do-not-leak-api-key", client=client,
        ),
    ],
)
def test_finance_provider_checks_report_401_without_credentials(provider_factory):
    client = httpx.Client(transport=httpx.MockTransport(
        lambda _request: httpx.Response(401),
    ))
    result = provider_factory(client).check()

    assert not result.ok and result.live
    assert "HTTP 401" in result.message
    assert "do-not-leak" not in result.message


@pytest.mark.parametrize(
    "provider_factory",
    [
        lambda client: QuickBooksProvider(
            "do-not-leak-qbo-token", "do-not-leak-realm", client=client,
        ),
        lambda client: XeroProvider(
            "do-not-leak-xero-token", "do-not-leak-tenant", client=client,
        ),
        lambda client: MeritProvider(
            "do-not-leak-api-id", "do-not-leak-api-key", client=client,
        ),
    ],
)
def test_finance_provider_checks_report_timeout_without_credentials(provider_factory):
    def timeout(request):
        raise httpx.ReadTimeout("synthetic timeout with no credentials", request=request)

    client = httpx.Client(transport=httpx.MockTransport(timeout))
    result = provider_factory(client).check()

    assert not result.ok and not result.live
    assert "connection error or timeout" in result.message
    assert "do-not-leak" not in result.message


def test_direct_tax_submission_gates_have_no_network_calls():
    provider=HMRCProvider("token",client=httpx.Client(transport=httpx.MockTransport(lambda _r: (_ for _ in ()).throw(AssertionError("network")))))
    with pytest.raises(PermissionError,match="disabled"):
        provider.submit_return("123",{"finalised":True},declaration_confirmed=True)
    with pytest.raises(PermissionError,match="not enabled"):
        EMTAExportProvider().submit({})


def test_fasthr_check_success_and_authorization_header():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"data": [], "meta": {"total": 17, "limit": 1, "offset": 0}})

    provider = FastHRProvider(
        token="synthetic-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = provider.check()

    assert result.ok and result.live
    assert result.message == "FastHR API reachable; 17 employees visible"
    assert seen[0].headers["authorization"] == "Bearer synthetic-token"
    assert dict(seen[0].url.params) == {"limit": "1"}


def test_fasthr_check_reports_authentication_and_connection_failures():
    unauthorized = FastHRProvider(
        token="synthetic-token",
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(401))),
    ).check()
    assert not unauthorized.ok and unauthorized.live
    assert "HTTP 401" in unauthorized.message

    def disconnected(request):
        raise httpx.ConnectError("synthetic connection failure", request=request)

    unavailable = FastHRProvider(
        token="synthetic-token",
        client=httpx.Client(transport=httpx.MockTransport(disconnected)),
    ).check()
    assert not unavailable.ok and not unavailable.live
    assert "connection error or timeout" in unavailable.message


def test_fasthr_pull_paginates_and_normalizes_employee_records():
    requests = []
    first_page = [
        {
            "id": index,
            "code": f"EMP-{index}",
            "first_name": "  Ada  " if index == 1 else f"Employee {index}",
            "last_name": "  Lovelace " if index == 1 else "Test",
            "email": "ada@example.test" if index == 1 else None,
            "designation": "Engineer",
            "date_of_joining": "2026-01-02",
            "status": "Active" if index == 1 else "Inactive",
            "gender": "Female" if index == 1 else None,
            "branch": "Tallinn",
            "base_salary": 28801.5 if index == 1 else 0,  # FastHR stores an annual salary
            "password_hash": "must-not-survive",
        }
        for index in range(1, 201)
    ]
    second_page = [
        {
            "id": 201,
            "code": "EMP-201",
            "first_name": " ",
            "last_name": "  Tamm  ",
            "email": "tamm@example.test",
            "designation": None,
            "date_of_joining": None,
            "status": "Leave",
            "gender": None,
            "branch": "Tartu",
            "base_salary": None,
        },
        {
            "id": 202,
            "first_name": " ",
            "last_name": None,
            "status": "Active",
            "base_salary": 1000,
        },
    ]

    def handler(request):
        requests.append(request)
        offset = int(request.url.params["offset"])
        rows = first_page if offset == 0 else second_page
        return httpx.Response(200, json={
            "data": rows,
            "meta": {"total": 202, "limit": 200, "offset": offset},
        })

    result = FastHRProvider(
        token="synthetic-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).pull("employee")

    assert result.ok and result.live and result.cursor == "202"
    assert [int(request.url.params["offset"]) for request in requests] == [0, 200]
    assert all(request.url.params["limit"] == "200" for request in requests)
    first = result.records[0]
    assert first == {
        "external_id": "1",
        "name": "Ada Lovelace",
        "email": "ada@example.test",
        "gross_salary": Decimal("2400.13"),
        "fte": Decimal("1"),
        "active": True,
        "fasthr_code": "EMP-1",
        "fasthr_designation": "Engineer",
        "fasthr_date_of_joining": "2026-01-02",
        "fasthr_status": "Active",
        "fasthr_gender": "Female",
        "fasthr_branch": "Tallinn",
    }
    assert result.records[-1]["name"] == "Tamm"
    assert result.records[-1]["active"] is False
    assert "gross_salary" not in result.records[-1]
    assert len(result.records) == 201
    assert "password_hash" not in result.records[0]


def test_fasthr_pull_empty_list_and_authentication_error():
    empty = FastHRProvider(
        token="synthetic-token",
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(
            200, json={"data": [], "meta": {"total": 0, "limit": 200, "offset": 0}},
        ))),
    ).pull("employees")
    assert empty.records == () and empty.cursor == "0"

    unauthorized = FastHRProvider(
        token="synthetic-token",
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(401))),
    )
    with pytest.raises(ProviderError, match="HTTP 401"):
        unauthorized.pull("employee")


def test_personio_check_exchanges_credentials_in_json_body_and_honours_auth_cooldown():
    seen = []
    sleeps = []

    def handler(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(429)
        return httpx.Response(200, json=PERSONIO_AUTH_RESPONSE)

    result = PersonioProvider(
        "synthetic-client-id",
        "synthetic-client-secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=sleeps.append,
    ).check()

    assert result.ok and result.live
    assert result.message == "Personio API reachable; token exchange succeeded"
    assert sleeps == [60]
    assert len(seen) == 2 and all(request.url.path == "/v1/auth" for request in seen)
    assert all(not request.url.query for request in seen)
    assert seen[-1].headers["content-type"] == "application/json"
    assert seen[-1].headers["accept"] == "application/json"
    assert json.loads(seen[-1].read().decode()) == {
        "client_id": "synthetic-client-id",
        "client_secret": "synthetic-client-secret",
    }
    assert "synthetic-client-secret" not in result.message


def test_personio_token_exchange_failure_names_http_status_without_credentials():
    provider = PersonioProvider(
        "do-not-leak-client-id",
        "do-not-leak-client-secret",
        client=httpx.Client(transport=httpx.MockTransport(
            lambda _request: httpx.Response(403, json={"success": False}),
        )),
    )

    check = provider.check()
    assert not check.ok and check.live
    assert check.message == "Personio API authentication failed (HTTP 403)"
    assert "do-not-leak" not in check.message
    with pytest.raises(ProviderError, match=r"Personio token exchange failed \(HTTP 403\)"):
        provider.pull("employee")


def test_personio_check_reports_timeout_without_credentials():
    def timeout(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    result = PersonioProvider(
        "do-not-leak-client-id",
        "do-not-leak-client-secret",
        client=httpx.Client(transport=httpx.MockTransport(timeout)),
    ).check()

    assert not result.ok and not result.live
    assert "connection error or timeout" in result.message
    assert "do-not-leak" not in result.message


def test_personio_pull_paginates_maps_status_termination_and_salary_alias():
    requests = []
    employees = [
        (1, "Ada", "Active", "active", None, "2400.125", "Platform"),
        (2, "Ona", "Onboarding", "onboarding", None, None, "Sales"),
        (3, "Ina", "Inactive", "inactive", None, None, "Finance"),
        (4, "Teri", "Terminated", "active", "2020-01-01", None, "Operations"),
    ]

    def employee_row(employee):
        employee_id, first, last, status, termination, salary, department = employee
        attributes = {
            "first_name": _personio_attribute("First name", first, universal_id="first_name"),
            "last_name": _personio_attribute("Last name", last, universal_id="last_name"),
            "email": _personio_attribute("Email", f"{first.lower()}@example.test"),
            "status": _personio_attribute("Status", status),
            "department": _personio_attribute("Department", department),
            "dynamic_12345": _personio_attribute("Monthly salary", salary, "decimal"),
        }
        if termination is not None:
            attributes["termination_date"] = _personio_attribute("Termination date", termination, "date")
        return {"id": employee_id, "attributes": attributes}

    def handler(request):
        requests.append(request)
        if request.url.path == "/v1/auth":
            return httpx.Response(200, json=PERSONIO_AUTH_RESPONSE)
        offset = int(request.url.params["offset"])
        rows = [employee_row(item) for item in employees[offset:offset + 2]]
        return httpx.Response(200, json={
            "success": True,
            "data": rows,
            "metadata": {"total_elements": 4, "current_page": offset // 2 + 1, "total_pages": 2},
            "offset": offset,
            "limit": 100,
        })

    result = PersonioProvider(
        "synthetic-client-id",
        "synthetic-client-secret",
        salary_attribute="dynamic_12345",
        attributes=("first_name", "last_name"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).pull("employees", cursor="2026-10-01T00:00:00Z")

    employee_requests = [request for request in requests if request.url.path.endswith("/employees")]
    assert [request.url.params["offset"] for request in employee_requests] == ["0", "2"]
    assert all(request.url.params["limit"] == "100" for request in employee_requests)
    assert all(request.url.params["updated_since"] == "2026-10-01T00:00:00Z" for request in employee_requests)
    assert all(
        request.url.params.get_list("attributes[]") == ["first_name", "last_name"]
        for request in employee_requests
    )
    assert all(request.headers["authorization"] == "Bearer synthetic-personio-token" for request in employee_requests)
    assert all(request.headers["content-type"] == "application/json" for request in employee_requests)
    assert result.cursor == "2026-10-01T00:00:00Z"
    assert [record["active"] for record in result.records] == [True, False, False, False]
    assert [record["personio_status"] for record in result.records] == [
        "active", "onboarding", "inactive", "active",
    ]
    assert result.records[0]["gross_salary"] == Decimal("2400.13")
    assert result.records[0]["personio_department"] == "Platform"
    assert "personio_dynamic_12345" not in result.records[0]
    assert result.records[-1]["personio_termination_date"] == "2020-01-01"
    assert "gross_salary" not in result.records[1]


def test_personio_without_salary_alias_omits_salary_and_rejects_stalled_pagination():
    calls = 0

    def handler(request):
        nonlocal calls
        if request.url.path == "/v1/auth":
            return httpx.Response(200, json=PERSONIO_AUTH_RESPONSE)
        calls += 1
        return httpx.Response(200, json={
            "success": True,
            "data": [{
                "id": calls,
                "attributes": {
                    "first_name": _personio_attribute("First name", "Ada"),
                    "last_name": _personio_attribute("Last name", "Lovelace"),
                    "status": _personio_attribute("Status", "active"),
                    "dynamic_12345": _personio_attribute("Salary", "2400"),
                },
            }],
            "metadata": {"total_elements": 3, "current_page": 1, "total_pages": 3},
            "offset": 0,
            "limit": 100,
        })

    provider = PersonioProvider(
        "synthetic-client-id", "synthetic-client-secret",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(ProviderError, match="pagination made no progress"):
        provider.pull("employee")


def test_bamboohr_check_uses_basic_auth_and_documented_directory_request():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=BAMBOO_DIRECTORY_RESPONSE)

    result = BambooHRProvider(
        "synthetic-company",
        "synthetic-api-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    ).check()

    assert result.ok and result.live
    assert result.message == "BambooHR API reachable; employee directory succeeded"
    assert str(seen[0].url) == (
        "https://synthetic-company.bamboohr.com/api/gateway.php/"
        "synthetic-company/v1/employees/directory"
    )
    assert seen[0].headers["accept"] == "application/json"
    assert seen[0].headers["x-bamboohr-format"] == "JSON"
    expected_basic = base64.b64encode(b"synthetic-api-key:x").decode()
    assert seen[0].headers["authorization"] == f"Basic {expected_basic}"
    assert "synthetic-api-key" not in result.message


def test_bamboohr_check_reports_authentication_and_timeout_without_api_key_echo():
    unauthorized = BambooHRProvider(
        "synthetic-company",
        "do-not-leak-api-key",
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: httpx.Response(401))),
    ).check()
    assert not unauthorized.ok and unauthorized.live
    assert unauthorized.message == "BambooHR API authentication failed (HTTP 401)"
    assert "do-not-leak" not in unauthorized.message

    def timeout(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    unavailable = BambooHRProvider(
        "synthetic-company",
        "do-not-leak-api-key",
        client=httpx.Client(transport=httpx.MockTransport(timeout)),
    ).check()
    assert not unavailable.ok and not unavailable.live
    assert "connection error or timeout" in unavailable.message
    assert "do-not-leak" not in unavailable.message


def test_bamboohr_pull_maps_directory_dynamic_fields_email_fallback_and_optional_status():
    provider = BambooHRProvider(
        "synthetic-company",
        "synthetic-api-key",
        salary_field_id="customSalary",
        client=httpx.Client(transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=BAMBOO_DIRECTORY_RESPONSE),
        )),
    )

    result = provider.pull("employee")

    assert len(result.records) == 3
    assert result.records[0] == {
        "external_id": "b-1",
        "name": "Ada Lovelace",
        "email": "ada.work@example.test",
        "active": True,
        "gross_salary": Decimal("2400.13"),
        "bamboo_jobTitle": "Engineer",
        "bamboo_location": "Tallinn",
    }
    assert result.records[1]["email"] == "grace.home@example.test"
    assert result.records[1]["active"] is False
    assert "gross_salary" not in result.records[1]
    assert "active" not in result.records[2]
    assert result.records[2]["bamboo_location"] == "Helsinki"


def test_bamboohr_without_salary_alias_keeps_custom_salary_as_prefixed_source_field():
    result = BambooHRProvider(
        "synthetic-company",
        "synthetic-api-key",
        client=httpx.Client(transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=BAMBOO_DIRECTORY_RESPONSE),
        )),
    ).pull("employees")

    assert "gross_salary" not in result.records[0]
    assert result.records[0]["bamboo_customSalary"] == "2400.125"


def test_fasthr_maps_annual_salary_work_time_ratio_personal_code_and_hourly():
    from connectors.providers import FASTHR_INVALID_WORK_TIME_RATIO, FASTHR_NO_PAY_AMOUNT

    base = {"first_name": "Mari", "last_name": "Maasik", "status": "Active"}
    record = FastHRProvider._employee_record

    yearly = record(dict(base, id=1, base_salary=30000, working_time_ratio=None,
                         personal_code=" 49403136526 "))
    assert yearly["gross_salary"] == Decimal("2500.00")
    assert yearly["fte"] == Decimal("1")
    assert yearly["personal_id"] == "49403136526"
    assert "pay_basis" not in yearly and "import_warning" not in yearly
    # Annual / 12 is rounded half-up to cents like every other amount in the app.
    assert record(dict(base, id=2, base_salary="20000.06"))["gross_salary"] == Decimal("1666.67")

    part_time = record(dict(base, id=3, base_salary=13620, working_time_ratio=0.5))
    assert part_time["gross_salary"] == Decimal("1135.00")
    assert part_time["fte"] == Decimal("0.5000")

    hourly = record(dict(base, id=4, base_salary=0, hourly_rate=8, working_time_ratio=1.0))
    assert hourly["pay_basis"] == "hourly" and hourly["hourly_rate"] == Decimal("8.0000")
    assert "gross_salary" not in hourly and "import_warning" not in hourly
    explicit = record(dict(base, id=5, base_salary=24000, hourly_rate="9.5", pay_basis="hourly"))
    assert explicit["pay_basis"] == "hourly" and "gross_salary" not in explicit

    unpaid = record(dict(base, id=6, base_salary=None))
    assert unpaid["import_warning"] == FASTHR_NO_PAY_AMOUNT
    assert not {"gross_salary", "hourly_rate", "pay_basis"} & set(unpaid)

    bad_ratio = record(dict(base, id=7, base_salary=12000, working_time_ratio=1.5))
    assert bad_ratio["import_warning"] == FASTHR_INVALID_WORK_TIME_RATIO and "fte" not in bad_ratio


@pytest.fixture
def merit_client():
    """Synthetic contract responses; no provider network access."""
    seen = []
    fixtures = {
        "accounts": [{"AccountID": "account-1", "Code": "1000", "Name": "Cash"}],
        "getcustomers": [{"CustomerId": "customer-1", "Name": "Test buyer", "RegNo": "123",
                          "VatRegNo": "EE123", "Email": "buyer@example.test", "Address": "Test street",
                          "City": "Tallinn", "PostalCode": "10000", "CountryName": "Estonia",
                          "CountryCode": "EE", "ChangedDate": "20260101"}],
        "getvendors": [{"VendorId": "vendor-1", "Name": "Test supplier", "RegNo": "456",
                        "ChangedDate": "20260102"}],
        "getinvoices": [{"SIHId": "invoice-1", "InvoiceNo": "INV-1", "CustomerId": "customer-1",
                         "CustomerName": "Test buyer", "CustomerRegNo": "123", "DocumentDate": "20260102",
                         "DueDate": "20260116", "CurrencyCode": "EUR", "TaxAmount": "24.12",
                         "TotalAmount": "100.50", "TotalSum": "124.62", "PaidAmount": "0",
                         "Paid": False, "PriceInclVat": False, "ChangedDate": "20260103"}],
        "getpurchorders": [{"PIHId": "bill-1", "BillNo": "BILL-1", "VendorId": "vendor-1",
                            "VendorName": "Test supplier", "VendorRegNo": "456", "DocumentDate": "20260102",
                            "DueDate": "20260116", "TaxAmount": "24.12", "TotalAmount": "100.50",
                            "TotalSum": "124.62", "Paid": True}],
        "getpayments": [{"PIHId": f"payment-{direction}", "DocumentNo": f"PAY-{direction}",
                         "DocumentDate": "20260103", "Amount": "124.620000000000000001",
                         "Direction": direction, "CounterPartType": 2 if direction == 1 else 3,
                         "CounterPartName": "Test counterparty", "CounterPartId": "contact-1",
                         "PaymAPIDetails": {"PaymId": "allocation-1", "DocId": "invoice-1",
                                            "DocNo": "INV-1", "PaidAmount": "124.62"}}
                        for direction in (1, 2, 3, 4)],
        "GetGLBatchesFull": [{"GLBId": "batch-1", "BatchCode": "GL-1", "BatchDate": "20260104",
                              "Document": "Test document", "Entries": [
                                  {"AccountCode": "1000", "DebitAmount": "10.1234567890123456789",
                                   "CreditAmount": 0, "Memo": "Test debit", "TaxId": "tax-1"},
                                  {"LineNo": 7, "AccountCode": "2000", "DebitAmount": 0,
                                   "CreditAmount": "10.1234567890123456789"}]}],
    }

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=fixtures.get(request.url.path.rsplit("/", 1)[-1], {"ok": True}))

    provider = MeritProvider("synthetic-id", "synthetic-key",
                             clock=lambda: datetime(2026, 10, 11, 12, 13, 14, tzinfo=timezone.utc),
                             client=httpx.Client(transport=httpx.MockTransport(handler)), retries=0)
    return provider, seen


def assert_merit_signature(request):
    params = request.url.params
    assert params["apiId"] == "synthetic-id"
    assert params["timestamp"] == "20261011121314"
    expected = base64.b64encode(hmac.new(
        b"synthetic-key", b"synthetic-id20261011121314" + request.content, hashlib.sha256,
    ).digest()).decode()
    assert params["signature"] == expected
    if request.method == "POST":
        assert set(params) == {"apiId", "timestamp", "signature"}
        assert request.content == json.dumps(json.loads(request.content), ensure_ascii=False,
                                             separators=(",", ":")).encode()


@pytest.mark.parametrize("object_type,endpoint,days", [
    ("sales_invoice", "getinvoices", 90), ("purchase_invoice", "getpurchorders", 90),
    ("payment", "getpayments", 90), ("gl_entry", "GetGLBatchesFull", 31),
])
def test_merit_pull_windows_advance_and_sign(merit_client, object_type, endpoint, days):
    provider, seen = merit_client
    start = date(2026, 1, 1)
    first = provider.pull(object_type, cursor=json.dumps({"from": start.isoformat()}))
    second = provider.pull(object_type, cursor=first.cursor)
    for index, request in enumerate(seen):
        window_start = start + timedelta(days=index * days)
        body = json.loads(request.content)
        assert body["PeriodStart"] == window_start.strftime("%Y%m%d")
        assert body["PeriodEnd"] == (window_start + timedelta(days=days - 1)).strftime("%Y%m%d")
        assert request.url.path == f"/api/v{1 if object_type == 'gl_entry' else 2}/{endpoint}"
        assert_merit_signature(request)
        if object_type != "sales_invoice":
            assert body["DateType"] == 0
        if object_type == "purchase_invoice":
            assert body["UnPaid"] is False
        if object_type == "gl_entry":
            assert body["WithLines"] == 1
    assert json.loads(second.cursor) == {"from": (start + timedelta(days=2 * days)).isoformat()}
    terminal = provider.pull(object_type, cursor="2026-10-10")
    assert terminal.cursor is None
    assert json.loads(seen[-1].content)["PeriodEnd"] == "20261011"


def test_merit_pull_normalisers_match_apply_aliases(merit_client):
    from import_service import ImportService

    provider, seen = merit_client
    account = provider.pull("account").records[0]
    assert account == {"external_id": "account-1", "code": "1000", "name": "Cash"}
    contacts = provider.pull("contact", cursor='{"from":"2026-01-01"}')
    assert contacts.cursor is None
    service = object.__new__(ImportService)
    buyer = service._contact_payload(contacts.records[0])
    assert buyer["external_id"] == "customer-1" and buyer["registration_no"] == "123"
    assert buyer["contact_type"] == "customer" and buyer["vat_no"] == "EE123"
    assert buyer["address"] == "Test street, Tallinn, 10000, Estonia"
    assert contacts.records[0]["external_version"] == "20260101"
    assert contacts.records[1]["contact_type"] == "supplier"
    for request in seen:
        assert_merit_signature(request)
    assert seen[0].url.params["UsageFilter"] == "0"
    assert all(request.url.params["ChangedDate"] == "20260101" for request in seen[1:])
    for object_type, role, name_key, date_key in (
        ("sales_invoice", "customer", "buyer_name", "issue_date"),
        ("purchase_invoice", "supplier", "supplier_name", "bill_date"),
    ):
        invoice = provider.pull(object_type).records[0]
        contact = service._contact_payload(invoice, role)
        assert contact["name"] == invoice[name_key] and contact["external_id"] == f"{'customer' if role == 'customer' else 'vendor'}-1"
        assert invoice[date_key] == "2026-01-02" and invoice["due_date"] == "2026-01-16"
        assert invoice["total"] == Decimal("124.62") and invoice["tax_total"] == Decimal("24.12")
        assert invoice["total_exvat"] == Decimal("100.50")
        assert isinstance(invoice["total"], Decimal) and invoice["external_id"]
        with pytest.raises(ValueError, match="At least one document line"):
            service._document_lines(None, "org-1", "merit", invoice)
    sales = provider.pull("sales_invoice").records[0]
    assert sales["payload_hash"] == hashlib.sha256(b"20260103").hexdigest()
    payments = provider.pull("payment").records
    assert [item.get("payment_type") for item in payments] == ["customer_receipt", "supplier_payment", None, None]
    assert all(item["document_external_id"] == "invoice-1" for item in payments)
    assert all(item["amount"] == Decimal("124.620000000000000001") for item in payments)
    assert all(item["external_id"] and item["payment_date"] == "2026-01-03" for item in payments)
    assert all(item["import_warning"] == item["merit_payment_note"] for item in payments[2:])
    gl = provider.pull("gl_entry").records
    assert [item["external_id"] for item in gl] == ["batch-1:1", "batch-1:7"]
    assert gl[0]["debit"] == gl[1]["credit"] == Decimal("10.1234567890123456789")
    assert gl[0]["external_batch_ref"] == "GL-1" and gl[0]["document"] == "Test document"
    assert gl[0]["external_account_code"] == "1000" and gl[0]["entry_date"] == "2026-01-04"


def test_merit_contact_server_error_falls_back_but_auth_does_not():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[]) if "ChangedDate" in request.url.params else httpx.Response(500)

    provider = MeritProvider("synthetic-id", "synthetic-key", retries=0,
                             clock=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc),
                             client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.pull("contact").records == ()
    assert len(seen) == 4
    assert all(request.url.params["ChangedDate"] == "20251011" for request in seen[1::2])
    provider.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401)))
    with pytest.raises(ProviderError, match="HTTP 401"):
        provider.pull("contact")
    provider.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    with pytest.raises(ProviderError, match="HTTP 500"):
        provider.pull("contact", cursor="2026-01-01")


@pytest.mark.parametrize("days", [31, 90])
def test_merit_period_caps_and_invalid_cursors(merit_client, days):
    provider, seen = merit_client
    start = date(2026, 1, 1)
    with pytest.raises(ValueError, match="period"):
        provider._period(start, start + timedelta(days=days), max_days=days)
    with pytest.raises(ValueError, match="period"):
        provider._period(start, start - timedelta(days=1), max_days=days)
    for cursor in ('{"from":"bad"}', '{}', '{broken', "2027-01-01"):
        with pytest.raises(ValueError):
            provider.pull("gl_entry", cursor=cursor)
    assert seen == []


def test_merit_gl_push_numeric_payload_chunking_and_delegation(merit_client, monkeypatch):
    provider, seen = merit_client
    batch = {"doc_no": "G" * 35, "posting_date": "2026-01-04", "currency": "EUR",
             "lines": [{"account_code": "1000", "debit": Decimal("12.34"), "credit": Decimal("0"),
                        "description": "Tõend"}] * 1001}
    result = provider.push("gl_batch", [batch])
    assert result.ok and len(result.records) == 3
    bodies = [json.loads(request.content) for request in seen]
    assert [len(body["EntryRow"]) for body in bodies] == [500, 500, 1]
    assert [body["DocNo"] for body in bodies] == ["G" * 35, "G" * 33 + "-2", "G" * 33 + "-3"]
    assert all(len(body["DocNo"]) <= 35 and body["BatchDate"] == "20260104" for body in bodies)
    assert bodies[0]["EntryRow"][0] == {"AccountCode": "1000", "Debit": 12.34, "Credit": 0, "Memo": "Tõend"}
    for request in seen:
        assert request.url.path == "/api/v1/sendglbatch"
        assert_merit_signature(request)
    delegated = []
    monkeypatch.setattr(provider, "create_invoice", lambda payload: delegated.append(payload) or {"SIHId": "new-1"})
    invoice = {"DocNo": "INV-2"}
    assert provider.push("sales_invoice", [invoice]).records == ({"SIHId": "new-1"},)
    assert delegated == [invoice]
    monkeypatch.undo()
    provider.push("sales_invoice", [invoice])
    assert seen[-1].url.path == "/api/v2/sendinvoice"
    assert_merit_signature(seen[-1])


@pytest.mark.parametrize("field,value", [("doc_no", "x" * 36), ("posting_date", "bad"),
                                          ("currency", "GBP"), ("lines", []),
                                          ("lines", [{"account_code": "x" * 9}]),
                                          ("lines", [{"account_code": "1000", "memo": "x" * 151}]),
                                          ("lines", [{"account_code": "1000", "debit": "NaN"}]),
                                          ("lines", [{"account_code": "1000", "debit": "1e9999"}])])
def test_merit_gl_push_validates_before_any_request(merit_client, field, value):
    provider, seen = merit_client
    valid = {"doc_no": "GL-1", "posting_date": "2026-01-01", "lines": [{"account_code": "1000"}]}
    with pytest.raises(ValueError):
        provider.push("gl_batch", [valid, dict(valid, **{field: value})])
    assert seen == []


def test_merit_unsupported_types_and_invalid_responses(merit_client):
    provider, seen = merit_client
    assert provider.PULL_OBJECT_TYPES == ("account", "contact", "sales_invoice", "purchase_invoice", "payment", "gl_entry")
    assert provider.PUSH_OBJECT_TYPES == ("gl_batch", "sales_invoice")
    with pytest.raises(ValueError, match="Unsupported"):
        provider.pull("contacts")
    with pytest.raises(ValueError, match="Unsupported"):
        provider.push("payment", [])
    assert seen == []
    for response in (httpx.Response(200, content=b"invalid"), httpx.Response(200, json={"error": "bad"}),
                     httpx.Response(200, json=[{"Code": "1000"}])):
        provider.client = httpx.Client(transport=httpx.MockTransport(lambda request: response))
        with pytest.raises(ProviderError):
            provider.pull("account")

    def timeout(request):
        raise httpx.ReadTimeout("synthetic timeout", request=request)

    provider.client = httpx.Client(transport=httpx.MockTransport(timeout))
    with pytest.raises(ProviderError, match="connection error"):
        provider.pull("account")


def test_merit_json_numeric_amounts_preserve_decimal_precision():
    provider = MeritProvider("synthetic-id", "synthetic-key", client=httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b'[{"PIHId":"p-1","DocumentDate":"20260101",'
                                     b'"Direction":1,"Amount":123.1234567890123456789}]'),
    )))
    record = provider.pull("payment").records[0]
    assert record["amount"] == Decimal("123.1234567890123456789")


@pytest.fixture
def smartaccounts_client():
    seen = []
    def handler(request):
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"id": "new-gl", "docType": "LEDGER_ENTRY", "amount": 12.34, "number": "1"})
        endpoint = request.url.path.split("/")[-1].split(":")[0]
        invoice = {"id": "i-1", "invoiceNumber": "INV-1", "date": "02.01.2026", "dueDate": "16.01.2026",
                   "clientId": "c-1", "vendorId": "v-1", "currency": "EUR", "amount": 100.5,
                   "vatAmount": 24.12, "totalAmount": 124.62, "outstandingAmount": 0,
                   "client": {"name": "Synthetic buyer", "regCode": "123"},
                   "vendor": {"name": "Synthetic vendor", "regCode": "456"}, "rows": [{"price": 100.5, "quantity": 1, "vatPc": "24"}]}
        data = {
            "accounts": [{"id": "a-1", "code": "1000", "descriptionEn": "Cash", "descriptionEt": "Raha", "type": "ASSET"}],
            "clients": [{"id": "c-1", "name": "Synthetic buyer", "regCode": "123", "vatNumber": "EE123",
                         "dateUpdated": "03.01.2026", "contacts": [{"type": "EMAIL", "value": "buyer@example.test"}]}],
            "clientinvoices": [invoice], "vendorinvoices": [invoice],
            "payments": [{"id": "p-1", "date": "03.01.2026", "amount": 124.62, "partnerType": "CLIENT",
                          "rows": [{"type": "CLIENT_INVOICE", "id": "i-1", "amount": 124.62}]}],
            "entries": [{"id": "g-1", "date": "04.01.2026", "document": "GL-1", "docType": "LEDGER_ENTRY",
                         "rows": [{"account": "1000", "description": "Test", "debitAmount": 12.34, "objectId": "object-1"}]}],
        }
        key = {"clientinvoices": "clientInvoices", "vendorinvoices": "vendorInvoices"}.get(endpoint, endpoint)
        return httpx.Response(200, json={key: data[endpoint], "hasMoreEntries": False})
    provider = SmartAccountsProvider("synthetic-public", "synthetic-secret", lang="en",
        clock=lambda: datetime(2026, 10, 11, 12, tzinfo=timezone.utc),
        client=httpx.Client(transport=httpx.MockTransport(handler)))
    return provider, seen


def assert_smartaccounts_signature(request):
    query, signature = request.url.query.decode().rsplit("&signature=", 1)
    assert signature == hmac.new(b"synthetic-secret", query.encode() + request.content, hashlib.sha256).hexdigest()


def test_smartaccounts_pinned_signature_vectors(smartaccounts_client):
    provider, seen = smartaccounts_client
    # Reference calculation performed once with hmac.new(secret, query+body,
    # hashlib.sha256).hexdigest(); literals guard algorithm and separator drift.
    # Input is the officially documented example query (SmartAccounts API doc);
    # the sample api key is joined at runtime because it is a public
    # documentation value, not a credential.
    query = "codes=kood1%2Ckood2%2Ckood3&timestamp=14022013133802&apikey=" \
        "a066f7de6042458da916"
    assert provider._signature(query) == "3216ae3aa3731097203ec5541e70abf0dcd0edb34e2dacaf34dbfa1d6bc90808"
    assert provider._signature("timestamp=03032021090000&apikey=synthetic-public", '{"document":"GL-1"}') == "4a09674e57962587f40d73c90e289dac1ffe041e3b84cfa14fefb8395ae4ed05"
    provider.api_key = query.rsplit("apikey=", 1)[1]
    provider.clock = lambda: datetime(2013, 2, 14, 13, 38, 2, tzinfo=provider.tallinn)
    provider._accounting_request("GET", "settings/accounts:get", params={"codes": "kood1,kood2,kood3"})
    assert seen[0].url.query.decode() == query + "&signature=3216ae3aa3731097203ec5541e70abf0dcd0edb34e2dacaf34dbfa1d6bc90808"


@pytest.mark.parametrize("instant,expected", [
    (datetime(2026, 3, 29, 0, 30, tzinfo=timezone.utc), "29032026023000"),
    (datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc), "29032026043000"),
])
def test_smartaccounts_tallinn_dst_timestamp(smartaccounts_client, instant, expected):
    provider, seen = smartaccounts_client
    provider.clock = lambda: instant
    assert provider.check().ok
    assert seen[-1].url.params["timestamp"] == expected
    assert_smartaccounts_signature(seen[-1])


@pytest.mark.parametrize("object_type,endpoint", [
    ("account", "settings/accounts"), ("contact", "purchasesales/clients"),
    ("sales_invoice", "purchasesales/clientinvoices"), ("purchase_invoice", "purchasesales/vendorinvoices"),
    ("payment", "purchasesales/payments"), ("gl_entry", "general/entries"),
])
def test_smartaccounts_pull_dispatch(smartaccounts_client, object_type, endpoint):
    provider, seen = smartaccounts_client
    result = provider.pull(object_type)
    assert result.ok and result.records[0]["external_id"]
    assert seen[-1].url.path == f"/en/api/{endpoint}:get"
    assert_smartaccounts_signature(seen[-1])
    if object_type not in {"account", "contact"}:
        assert seen[-1].url.params["fetchRows"] == "true"
        assert seen[-1].url.params["dateType"] == "date"
    if object_type == "gl_entry":
        assert seen[-1].url.params["docType"] == "LEDGER_ENTRY"


@pytest.mark.parametrize("object_type,key", [("contact", "clients"), ("sales_invoice", "invoices")])
def test_smartaccounts_pagination_uses_metadata_not_page_size(smartaccounts_client, object_type, key):
    provider, seen = smartaccounts_client
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={key: [], "hasMoreEntries": request.url.params["pageNumber"] == "1"})
    provider.client = httpx.Client(transport=httpx.MockTransport(handler))
    first = provider.pull(object_type, cursor='{"from":"2026-10-01"}' if object_type != "contact" else None)
    assert json.loads(first.cursor)["page"] == 2
    second = provider.pull(object_type, cursor=first.cursor)
    assert second.cursor is None
    assert [r.url.params["pageNumber"] for r in seen] == ["1", "2"]
    if object_type != "contact":
        assert seen[0].url.params["dateFrom"] == seen[1].url.params["dateFrom"] == "01.10.2026"
        assert seen[0].url.params["dateTo"] == seen[1].url.params["dateTo"] == "11.10.2026"
    third = provider.pull("payment", cursor='{"from":"2026-01-01"}')
    # First page has more entries; the frozen 90-day end survives its cursor.
    assert json.loads(third.cursor)["to"] == "2026-03-31"


def smartaccounts_batch():
    return {"doc_no": "GL-1", "posting_date": "2026-01-04", "currency": "EUR",
            "lines": [{"external_account_code": "1000", "debit": Decimal("12.34"), "memo": "Tõend"},
                      {"external_account_code": "2000", "credit": Decimal("12.34")} ]}


def test_smartaccounts_gl_push_one_request_and_response_id(smartaccounts_client):
    provider, seen = smartaccounts_client
    batch = smartaccounts_batch()
    batch["lines"] *= 501
    result = provider.push("gl_batch", [batch])
    assert result.records[0]["external_id"] == "new-gl"
    assert isinstance(result.records[0]["amount"], Decimal)
    assert len(seen) == 1 and seen[0].url.path == "/en/api/general/entries:add"
    payload = json.loads(seen[0].content)
    assert payload["docType"] == "LEDGER_ENTRY" and payload["currency"] == "EUR"
    assert payload["date"] == "2026-01-04" and payload["document"] == "GL-1"
    assert len(payload["rows"]) == 1002
    assert payload["rows"][0] == {"account": "1000", "description": "Tõend", "debitAmount": 12.34, "creditAmount": 0}
    assert_smartaccounts_signature(seen[0])


@pytest.mark.parametrize("field,value", [("doc_no", ""), ("posting_date", "bad"), ("currency", "GBP"),
    ("lines", []), ("lines", [None]), ("lines", [{"account_code": "1000", "debit": "NaN"}]),
    ("lines", [{"account_code": "1000", "debit": "1e9999"}]),
    ("lines", [{"account_code": "1000", "debit": "1.001"}]),
    ("lines", [{"account_code": "1000", "debit": "1"}]),
    ("lines", [{"account_code": "1000", "debit": "-1"}]), ("lines", [{"debit": "1"}])])
def test_smartaccounts_validates_all_batches_before_network(smartaccounts_client, field, value):
    provider, seen = smartaccounts_client
    with pytest.raises(ValueError):
        provider.push("gl_batch", [smartaccounts_batch(), dict(smartaccounts_batch(), **{field: value})])
    assert seen == []


def test_smartaccounts_checks_and_invalid_contracts(smartaccounts_client):
    provider, seen = smartaccounts_client
    assert provider.check().ok and seen[-1].url.path == "/en/api/settings/accounts:get"
    provider.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(401)))
    result = provider.check()
    assert not result.ok and result.live and "authentication failed (HTTP 401)" in result.message
    assert "synthetic" not in result.message
    def timeout(request):
        raise httpx.ConnectError("offline", request=request)
    provider.client = httpx.Client(transport=httpx.MockTransport(timeout))
    assert not provider.check().live
    with pytest.raises(ValueError, match="Unsupported"):
        provider.pull("employees")
    with pytest.raises(ValueError, match="Unsupported"):
        provider.push("sales_invoice", [])
    for payload in ({"accounts": [{}]}, {"unexpected": "bad"}):
        provider.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
        with pytest.raises(ProviderError):
            provider.pull("account")
    provider.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"clients": []})))
    with pytest.raises(ProviderError, match="pagination"):
        provider.pull("contact")


def test_smartaccounts_normalisers_match_apply_aliases(smartaccounts_client):
    from import_service import ImportService
    provider, _ = smartaccounts_client
    service = object.__new__(ImportService)
    contact = provider.pull("contact").records[0]
    values = service._contact_payload(contact)
    assert values["contact_type"] == "customer" and values["email"] == "buyer@example.test"
    assert values["registration_no"] == "123" and values["vat_no"] == "EE123"
    assert contact["external_version"] == "03.01.2026"
    for kind, role in (("sales_invoice", "customer"), ("purchase_invoice", "supplier")):
        invoice = provider.pull(kind).records[0]
        assert service._contact_payload(invoice, role)["name"].startswith("Synthetic")
        assert invoice["tax_total"] == Decimal("24.12") and invoice["total"] == Decimal("124.62")
        assert invoice["total_exvat"] == Decimal("100.5") and invoice["paid"]
        assert invoice["due_date"] == "2026-01-16"
        with pytest.raises(ValueError, match="At least one document line"):
            service._document_lines(None, "org", "smartaccounts", invoice)
    payment = provider.pull("payment").records[0]
    assert service._text(payment, "document_external_id", "invoice_external_id") == "i-1"
    assert payment["payment_type"] == "customer_receipt" and payment["amount"] == Decimal("124.62")
    gl = provider.pull("gl_entry").records[0]
    assert gl["external_id"] == "g-1:1" and gl["debit"] == Decimal("12.34")
    assert service._text(gl, "entry_date", "date") == "2026-01-04"
    assert gl["dims"] == {"objectId": "object-1"}


def test_smartaccounts_decimal_json_and_registry(smartaccounts_client):
    provider, _ = smartaccounts_client
    provider.client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200,
        content=b'{"payments":[{"id":"p","date":"01.01.2026","amount":123.1234567890123456789}],"hasMoreEntries":false}')))
    assert provider.pull("payment").records[0]["amount"] == Decimal("123.1234567890123456789")
    registered = connector_for("smartaccounts", credentials={"api_key": "public", "secret_key": "secret"})
    assert isinstance(registered, SmartAccountsProvider) and registered.lang == "et"
    assert registered.base_url == "https://sa.smartaccounts.eu/et/api"
    with pytest.raises(ValueError, match="language"):
        SmartAccountsProvider("public", "secret", lang="de")
    for cursor in ('{"page":0}', '[]', '{bad', '{"from":"2027-01-01"}'):
        with pytest.raises(ValueError, match="cursor"):
            provider.pull("sales_invoice", cursor=cursor)


def test_smartaccounts_503_retry_and_timezone_errors(smartaccounts_client, monkeypatch):
    provider, seen = smartaccounts_client
    delays = []
    def handler(request):
        seen.append(request)
        return httpx.Response(503, headers={"Retry-After": "2"}) if len(seen) == 1 else httpx.Response(200, json={"accounts": []})
    provider.client = httpx.Client(transport=httpx.MockTransport(handler))
    provider.sleep = delays.append
    assert provider.check().ok and delays == [2]
    assert seen[0].url == seen[1].url
    for request in seen:
        assert_smartaccounts_signature(request)
    provider.clock = lambda: datetime(2026, 1, 1)
    with pytest.raises(ValueError, match="timezone-aware"):
        provider.pull("account")
    from zoneinfo import ZoneInfoNotFoundError
    def missing_zone(name):
        raise ZoneInfoNotFoundError(name)
    monkeypatch.setattr("zoneinfo.ZoneInfo", missing_zone)
    with pytest.raises(ValueError, match="pip install tzdata"):
        SmartAccountsProvider("public", "secret")


def test_smartaccounts_registry_metadata():
    from connectors.registry import provider_metadata
    metadata = provider_metadata("smartaccounts")
    assert metadata["registry_status"] == "Documented contract · not live-verified"
    fields = metadata["credential_fields"]
    assert [field["name"] for field in fields] == ["api_key", "secret_key", "lang"]
    assert fields[0]["input_type"] == fields[1]["input_type"] == "secret"
    assert fields[2]["default"] == "et"
