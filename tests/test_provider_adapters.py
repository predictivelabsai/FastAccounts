from __future__ import annotations

import base64
from datetime import datetime, timezone

import httpx
import pytest
from cryptography.fernet import Fernet

from connectors.providers import EMTAExportProvider, HMRCProvider, MeritProvider, OpenBankingProvider, QuickBooksProvider, XeroProvider
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


def test_direct_tax_submission_gates_have_no_network_calls():
    provider=HMRCProvider("token",client=httpx.Client(transport=httpx.MockTransport(lambda _r: (_ for _ in ()).throw(AssertionError("network")))))
    with pytest.raises(PermissionError,match="disabled"):
        provider.submit_return("123",{"finalised":True},declaration_confirmed=True)
    with pytest.raises(PermissionError,match="not enabled"):
        EMTAExportProvider().submit({})
