"""HTTP adapters for supported provider APIs with safe submission gates."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable
from urllib.parse import urlencode

import httpx

from core_utils import four_dp, money

from .base import ConnectorResult


# Review notes on staged FastHR employees; the exact strings are i18n keys
# in web/locales/*.json (workspace catalogue).
FASTHR_NO_PAY_AMOUNT = "FastHR has no salary or hourly rate for this employee; skipped until one is added in FastHR"
FASTHR_INVALID_WORK_TIME_RATIO = "FastHR work-time ratio must be above 0 and at most 1; check it in FastHR"


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


class FastHRProvider(HTTPProvider):
    """Pull-only employee master-data adapter for FastHR."""

    key = "fasthr"
    default_base_url = "https://fasthr.eu"

    def __init__(self, base_url: str = default_base_url, *, token: str, **kwargs):
        super().__init__(**kwargs)
        self.base_url = str(base_url or self.default_base_url).strip().rstrip("/")
        token = str(token or "").strip()
        if len(token) < 8:
            raise ValueError("FastHR API token must be at least 8 characters")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    @staticmethod
    def _status_code(error: ProviderError) -> int | None:
        cause = error.__cause__
        if isinstance(cause, httpx.HTTPStatusError):
            return cause.response.status_code
        return None

    def _employee_page(self, *, limit: int, offset: int | None = None) -> tuple[list[dict], int]:
        params = {"limit": limit}
        if offset is not None:
            params["offset"] = offset
        response = self.request(
            "GET",
            f"{self.base_url}/api/v1/employees",
            params=params,
            headers=self.headers,
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderError("FastHR returned an invalid JSON response") from error
        rows = payload.get("data") if isinstance(payload, dict) else None
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not isinstance(meta, dict):
            raise ProviderError("FastHR returned an invalid employee response")
        try:
            total = int(meta["total"])
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderError("FastHR returned invalid employee pagination metadata") from error
        if total < 0 or any(not isinstance(row, dict) for row in rows):
            raise ProviderError("FastHR returned invalid employee data")
        return rows, total

    def check(self) -> ConnectorResult:
        try:
            _rows, total = self._employee_page(limit=1)
        except httpx.RequestError:
            return ConnectorResult(
                self.key,
                "check",
                False,
                False,
                "FastHR API could not be reached due to a connection error or timeout",
            )
        except ProviderError as error:
            status = self._status_code(error)
            if status in {401, 403}:
                message = f"FastHR API authentication failed (HTTP {status})"
            elif status is not None:
                message = f"FastHR API returned unexpected HTTP {status}"
            else:
                message = str(error)
            return ConnectorResult(self.key, "check", False, True, message)
        return ConnectorResult(
            self.key,
            "check",
            True,
            True,
            f"FastHR API reachable; {total} employees visible",
        )

    @staticmethod
    def _employee_record(row: dict) -> dict | None:
        first_name = str(row.get("first_name") or "").strip()
        last_name = str(row.get("last_name") or "").strip()
        name = " ".join(part for part in (first_name, last_name) if part)
        if not name:
            return None
        record = {
            "external_id": str(row.get("id")),
            "name": name,
            "email": row.get("email"),
            "active": row.get("status") == "Active",
            "fasthr_code": row.get("code"),
            "fasthr_designation": row.get("designation"),
            "fasthr_date_of_joining": row.get("date_of_joining"),
            "fasthr_status": row.get("status"),
            "fasthr_gender": row.get("gender"),
            "fasthr_branch": row.get("branch"),
        }
        personal_code = str(row.get("personal_code") or "").strip()
        if personal_code:
            record["personal_id"] = personal_code
        warnings: list[str] = []
        fte = FastHRProvider._positive_decimal(row.get("working_time_ratio"))
        if row.get("working_time_ratio") in (None, ""):
            record["fte"] = Decimal("1")
        elif fte is not None and fte <= 1:
            record["fte"] = four_dp(fte)
        else:
            warnings.append(FASTHR_INVALID_WORK_TIME_RATIO)
        # FastHR stores base_salary as an annual amount (its UI shows it "/aastas" and its
        # own payroll divides by 12); FastAccounts keeps a monthly gross salary.
        annual = FastHRProvider._positive_decimal(row.get("base_salary"))
        hourly = FastHRProvider._positive_decimal(row.get("hourly_rate"))
        if hourly is not None and (annual is None or row.get("pay_basis") == "hourly"):
            record["pay_basis"] = "hourly"
            record["hourly_rate"] = four_dp(hourly)
        elif annual is not None:
            record["gross_salary"] = money(annual / 12)
        else:
            warnings.insert(0, FASTHR_NO_PAY_AMOUNT)
        if warnings:
            record["import_warning"] = warnings[0]
        return record

    @staticmethod
    def _positive_decimal(value) -> Decimal | None:
        if value in (None, "") or isinstance(value, bool):
            return None
        try:
            number = Decimal(str(value))
        except (ArithmeticError, ValueError):
            return None
        return number if number.is_finite() and number > 0 else None

    def pull(self, object_type: str, *, cursor: str | None = None) -> ConnectorResult:
        if object_type not in {"employee", "employees"}:
            raise ValueError("FastHR supports employee imports only")
        del cursor  # FastHR currently exposes offset pagination, not incremental cursors.
        records: list[dict] = []
        offset = 0
        total = 0
        while True:
            rows, total = self._employee_page(limit=200, offset=offset)
            for row in rows:
                record = self._employee_record(row)
                if record is not None:
                    records.append(record)
            offset += len(rows)
            if offset >= total:
                break
            if not rows:
                raise ProviderError("FastHR employee pagination stopped before the reported total")
        return ConnectorResult(
            self.key,
            f"pull:{object_type}",
            True,
            True,
            f"Pulled {len(records)} FastHR employee records",
            tuple(records),
            str(total),
        )

    def push(self, object_type: str, records: list[dict]) -> ConnectorResult:
        del records
        return ConnectorResult(
            self.key,
            f"push:{object_type}",
            False,
            True,
            "FastHR is a pull-only employee data source; no records were sent",
        )


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
