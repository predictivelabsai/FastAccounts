from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
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
