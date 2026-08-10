"""HTTP adapters for supported provider APIs with safe submission gates."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlencode

import httpx


class ProviderError(RuntimeError):
    pass


class HTTPProvider:
    def __init__(self, *, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, retries: int = 2):
        self.client = client or httpx.Client(timeout=20)
        self.sleep = sleep
        self.retries = retries

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        for attempt in range(self.retries + 1):
            response = self.client.request(method, url, **kwargs)
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == self.retries:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    request_id = response.headers.get("x-request-id", "")
                    raise ProviderError(f"Provider returned HTTP {response.status_code}; request {request_id}") from error
                return response
            delay = float(response.headers.get("Retry-After", min(2 ** attempt, 5)))
            self.sleep(min(delay, 10))
        raise ProviderError("Provider request exhausted retries")


class QuickBooksProvider(HTTPProvider):
    auth_url = "https://appcenter.intuit.com/connect/oauth2"
    token_url = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

    def __init__(self, access_token: str, realm_id: str, *, sandbox: bool = True, **kwargs):
        super().__init__(**kwargs)
        self.access_token, self.realm_id = access_token, realm_id
        host = "sandbox-quickbooks.api.intuit.com" if sandbox else "quickbooks.api.intuit.com"
        self.base_url = f"https://{host}/v3/company/{realm_id}"

    @staticmethod
    def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
        return QuickBooksProvider.auth_url + "?" + urlencode({
            "client_id": client_id, "response_type": "code", "scope": "com.intuit.quickbooks.accounting",
            "redirect_uri": redirect_uri, "state": state,
        })

    def query(self, query: str) -> dict:
        return self.request("GET", f"{self.base_url}/query", params={"query": query, "minorversion": "75"},
                            headers={"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}).json()

    def create_invoice(self, payload: dict, *, idempotency_key: str) -> dict:
        return self.request("POST", f"{self.base_url}/invoice", params={"minorversion": "75"}, json=payload,
                            headers={"Authorization": f"Bearer {self.access_token}", "Accept": "application/json",
                                     "Request-Id": idempotency_key}).json()


class XeroProvider(HTTPProvider):
    auth_url = "https://login.xero.com/identity/connect/authorize"
    token_url = "https://identity.xero.com/connect/token"
    base_url = "https://api.xero.com/api.xro/2.0"

    def __init__(self, access_token: str, tenant_id: str, **kwargs):
        super().__init__(**kwargs)
        self.headers = {"Authorization": f"Bearer {access_token}", "Xero-tenant-id": tenant_id,
                        "Accept": "application/json"}

    @staticmethod
    def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
        return XeroProvider.auth_url + "?" + urlencode({
            "response_type": "code", "client_id": client_id,
            "redirect_uri": redirect_uri, "scope": "openid profile email offline_access accounting.transactions accounting.contacts",
            "state": state,
        })

    def invoices(self, *, modified_after: str = "", page: int = 1) -> dict:
        headers = dict(self.headers)
        if modified_after:
            headers["If-Modified-Since"] = modified_after
        return self.request("GET", f"{self.base_url}/Invoices", params={"page": page, "summaryOnly": "false"}, headers=headers).json()

    def create_invoice(self, payload: dict, *, idempotency_key: str) -> dict:
        headers = dict(self.headers, **{"Idempotency-Key": idempotency_key})
        return self.request("POST", f"{self.base_url}/Invoices", json={"Invoices": [payload]}, headers=headers).json()


class MeritProvider(HTTPProvider):
    base_url = "https://aktiva.merit.ee/api/v2"

    def __init__(self, api_id: str, api_key: str, *, clock=None, **kwargs):
        super().__init__(**kwargs)
        self.api_id, self.api_key = api_id, api_key
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def signed_params(self, body: bytes) -> dict:
        timestamp = self.clock().strftime("%Y%m%d%H%M%S")
        signed = self.api_id.encode() + timestamp.encode() + body
        signature = base64.b64encode(hmac.new(self.api_key.encode("ascii"), signed, hashlib.sha256).digest()).decode()
        return {"apiId": self.api_id, "timestamp": timestamp, "signature": signature}

    def post(self, endpoint: str, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        return self.request("POST", f"{self.base_url}/{endpoint.lstrip('/')}", params=self.signed_params(body),
                            content=body, headers={"Content-Type": "application/json"}).json()

    def create_invoice(self, payload: dict) -> dict:
        return self.post("sendinvoice", payload)

    def payments(self, period_start: str, period_end: str) -> dict:
        return self.post("getpayments", {"PeriodStart": period_start.replace("-", ""),
                                         "PeriodEnd": period_end.replace("-", ""), "DateType": 0})


class HMRCProvider(HTTPProvider):
    auth_url = "https://www.tax.service.gov.uk/oauth/authorize"
    sandbox_auth_url = "https://test-www.tax.service.gov.uk/oauth/authorize"
    token_url = "https://api.service.hmrc.gov.uk/oauth/token"
    sandbox_token_url = "https://test-api.service.hmrc.gov.uk/oauth/token"

    def __init__(self, access_token: str, *, sandbox: bool = True, allow_submission: bool = False,
                 fraud_prevention_headers: dict[str, str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.base_url = "https://test-api.service.hmrc.gov.uk" if sandbox else "https://api.service.hmrc.gov.uk"
        self.allow_submission = allow_submission
        self.sandbox = sandbox
        self.fraud_prevention_headers = fraud_prevention_headers or {}
        self.headers = {"Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.hmrc.1.0+json"}

    @staticmethod
    def authorize_url(client_id: str, redirect_uri: str, state: str, *, sandbox: bool = True) -> str:
        base = HMRCProvider.sandbox_auth_url if sandbox else HMRCProvider.auth_url
        return base + "?" + urlencode({"response_type": "code", "client_id": client_id,
                                       "scope": "read:vat write:vat", "redirect_uri": redirect_uri,
                                       "state": state})

    def _request_headers(self) -> dict[str, str]:
        if not self.sandbox and not self.fraud_prevention_headers:
            raise PermissionError("HMRC production calls require validated fraud-prevention headers")
        return dict(self.headers, **self.fraud_prevention_headers)

    def obligations(self, vrn: str, start: str, end: str, status: str = "O") -> dict:
        return self.request("GET", f"{self.base_url}/organisations/vat/{vrn}/obligations",
                            params={"from": start, "to": end, "status": status}, headers=self._request_headers()).json()

    def submit_return(self, vrn: str, payload: dict, *, declaration_confirmed: bool) -> dict:
        if not self.allow_submission:
            raise PermissionError("HMRC direct submission is disabled by configuration")
        if not declaration_confirmed or payload.get("finalised") is not True:
            raise PermissionError("The legal declaration must be explicitly confirmed")
        return self.request("POST", f"{self.base_url}/organisations/vat/{vrn}/returns",
                            json=payload, headers=dict(self._request_headers(), **{"Content-Type": "application/json"})).json()


class OpenBankingProvider(HTTPProvider):
    """Read-only GoCardless Bank Account Data adapter; no payment initiation."""
    base_url = "https://bankaccountdata.gocardless.com/api/v2"

    def __init__(self, access_token: str, **kwargs):
        super().__init__(**kwargs)
        self.headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    def institutions(self, country: str) -> list[dict]:
        return self.request("GET", f"{self.base_url}/institutions/", params={"country": country}, headers=self.headers).json()

    def create_requisition(self, *, redirect: str, institution_id: str, reference: str) -> dict:
        payload = {"redirect": redirect, "institution_id": institution_id,
                   "reference": reference, "user_language": "EN"}
        return self.request("POST", f"{self.base_url}/requisitions/", json=payload, headers=self.headers).json()

    def transactions(self, account_id: str, *, date_from: str = "", date_to: str = "") -> dict:
        params = {key: value for key, value in (("date_from", date_from), ("date_to", date_to)) if value}
        return self.request("GET", f"{self.base_url}/accounts/{account_id}/transactions/",
                            params=params, headers=self.headers).json()


class EMTAExportProvider:
    """Explicit export-only boundary until an X-Road service agreement exists."""
    def submit(self, *_args, **_kwargs):
        raise PermissionError("e-MTA direct filing is not enabled; use reviewed KMD export")
