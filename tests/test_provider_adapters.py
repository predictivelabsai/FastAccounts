from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
from cryptography.fernet import Fernet

from connectors.providers import (
    EMTAExportProvider,
    FastHRProvider,
    HMRCProvider,
    MeritProvider,
    OpenBankingProvider,
    ProviderError,
    QuickBooksProvider,
    XeroProvider,
)
from integration_service import CredentialVault, IntegrationService


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
            "base_salary": 2400.125 if index == 1 else 0,
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
