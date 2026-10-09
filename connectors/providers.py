"""HTTP adapters for supported provider APIs with safe submission gates."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Callable
from urllib.parse import urlencode

import httpx

from core_utils import money

from .base import ConnectorResult


class ProviderError(RuntimeError):
    pass


class HTTPProvider:
    def __init__(self, *, client: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, retries: int = 2):
        self.client = client or httpx.Client(timeout=20)
        self.sleep = sleep
        self.retries = retries

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        rate_limit_cooldown = kwargs.pop("_rate_limit_cooldown", None)
        for attempt in range(self.retries + 1):
            response = self.client.request(method, url, **kwargs)
            if response.status_code not in {429, 500, 502, 503, 504} or attempt == self.retries:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as error:
                    request_id = response.headers.get("x-request-id", "")
                    raise ProviderError(f"Provider returned HTTP {response.status_code}; request {request_id}") from error
                return response
            if response.status_code == 429 and rate_limit_cooldown is not None:
                delay = float(rate_limit_cooldown)
            else:
                delay = float(response.headers.get("Retry-After", min(2 ** attempt, 5)))
                delay = min(delay, 10)
            self.sleep(delay)
        raise ProviderError("Provider request exhausted retries")

    @staticmethod
    def _status_code(error: ProviderError) -> int | None:
        cause = error.__cause__
        while cause is not None:
            if isinstance(cause, httpx.HTTPStatusError):
                return cause.response.status_code
            cause = cause.__cause__
        return None


class QuickBooksProvider(HTTPProvider):
    key = "quickbooks"
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

    def check(self) -> ConnectorResult:
        try:
            self.query("select * from Account maxresults 1")
        except httpx.RequestError:
            return ConnectorResult(
                self.key,
                "check",
                False,
                False,
                "QuickBooks API could not be reached due to a connection error or timeout",
            )
        except ProviderError as error:
            status = self._status_code(error)
            if status == 401:
                message = "QuickBooks API authentication failed (HTTP 401)"
            elif status is not None:
                message = f"QuickBooks API returned unexpected HTTP {status}"
            else:
                message = "QuickBooks API check failed"
            return ConnectorResult(self.key, "check", False, True, message)
        return ConnectorResult(
            self.key,
            "check",
            True,
            True,
            "QuickBooks API reachable; company context valid",
        )


class XeroProvider(HTTPProvider):
    key = "xero"
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

    def check(self) -> ConnectorResult:
        try:
            # Xero's tenant-authorized identity resource is singular: GET /Organisation.
            self.request("GET", f"{self.base_url}/Organisation", headers=self.headers)
        except httpx.RequestError:
            return ConnectorResult(
                self.key,
                "check",
                False,
                False,
                "Xero API could not be reached due to a connection error or timeout",
            )
        except ProviderError as error:
            status = self._status_code(error)
            if status in {401, 403}:
                message = f"Xero API authentication failed (HTTP {status})"
            elif status is not None:
                message = f"Xero API returned unexpected HTTP {status}"
            else:
                message = "Xero API check failed"
            return ConnectorResult(self.key, "check", False, True, message)
        return ConnectorResult(
            self.key,
            "check",
            True,
            True,
            "Xero API reachable; tenant context valid",
        )


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
        salary = row.get("base_salary")
        if salary is not None:
            decimal_salary = Decimal(str(salary))
            if decimal_salary > 0:
                record["gross_salary"] = money(decimal_salary)
        return record

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


class PersonioProvider(HTTPProvider):
    """Documented-contract employee adapter; salary needs an explicit attribute alias.

    Personio's generally available employee payload does not provide a canonical
    gross-salary field. Records therefore omit ``gross_salary`` unless the
    connection config supplies a reviewed ``salary_attribute`` API name. The
    employee pipeline deliberately rejects unsalaried rows at apply time so an
    accountant must enter salary locally or approve a later mapping.
    """

    key = "personio"
    default_base_url = "https://api.personio.de"

    def __init__(self, client_id: str, client_secret: str, *,
                 base_url: str = default_base_url, salary_attribute: str = "",
                 attributes: list[str] | tuple[str, ...] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.client_id = str(client_id or "").strip()
        self.client_secret = str(client_secret or "").strip()
        self.base_url = str(base_url or self.default_base_url).strip().rstrip("/")
        self.salary_attribute = str(salary_attribute or "").strip()
        self.attributes = tuple(
            value for item in (attributes or ()) if (value := str(item).strip())
        )

    def _token(self) -> str:
        try:
            response = self.request(
                "POST",
                f"{self.base_url}/v1/auth",
                json={"client_id": self.client_id, "client_secret": self.client_secret},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                _rate_limit_cooldown=60,
            )
        except ProviderError as error:
            status = self._status_code(error)
            if status is not None:
                raise ProviderError(f"Personio token exchange failed (HTTP {status})") from error
            raise
        try:
            payload = response.json(parse_float=Decimal)
        except ValueError as error:
            raise ProviderError("Personio token exchange returned invalid JSON") from error
        data = payload.get("data") if isinstance(payload, dict) else None
        token = (
            data.get("token")
            if isinstance(payload, dict) and payload.get("success") is True and isinstance(data, dict)
            else None
        )
        if not isinstance(token, str) or not token.strip():
            raise ProviderError("Personio token exchange returned an invalid response")
        return token.strip()

    def check(self) -> ConnectorResult:
        try:
            self._token()
        except httpx.RequestError:
            return ConnectorResult(
                self.key, "check", False, False,
                "Personio API could not be reached due to a connection error or timeout",
            )
        except ProviderError as error:
            status = self._status_code(error)
            if status in {401, 403}:
                message = f"Personio API authentication failed (HTTP {status})"
            elif status is not None:
                message = f"Personio API returned unexpected HTTP {status} during token exchange"
            else:
                message = str(error)
            return ConnectorResult(self.key, "check", False, True, message)
        return ConnectorResult(
            self.key, "check", True, True,
            "Personio API reachable; token exchange succeeded",
        )

    def _employee_page(self, token: str, *, offset: int, updated_since: str = "") -> dict:
        params: dict[str, object] = {"limit": 100, "offset": offset}
        if updated_since:
            params["updated_since"] = updated_since
        if self.attributes:
            params["attributes[]"] = self.attributes
        response = self.request(
            "GET",
            f"{self.base_url}/v1/company/employees",
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            payload = response.json(parse_float=Decimal)
        except ValueError as error:
            raise ProviderError("Personio returned an invalid JSON response") from error
        data = payload.get("data") if isinstance(payload, dict) else None
        metadata = payload.get("metadata") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or payload.get("success") is not True
            or not isinstance(data, list)
            or not isinstance(metadata, dict)
        ):
            raise ProviderError("Personio returned an invalid employee response")
        try:
            total = int(metadata["total_elements"])
            page_offset = int(payload["offset"])
            page_limit = int(payload["limit"])
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderError("Personio returned invalid employee pagination metadata") from error
        if total < 0 or page_offset < 0 or page_limit < 1 or any(not isinstance(row, dict) for row in data):
            raise ProviderError("Personio returned invalid employee data")
        return {"rows": data, "total": total, "offset": page_offset}

    @staticmethod
    def _attribute_values(row: dict) -> dict[str, object]:
        attributes = row.get("attributes")
        if not isinstance(attributes, dict):
            raise ProviderError("Personio returned invalid employee attributes")
        values: dict[str, object] = {}
        for api_name, attribute in attributes.items():
            if isinstance(api_name, str) and isinstance(attribute, dict) and "value" in attribute:
                values[api_name] = attribute["value"]
        return values

    def _employee_record(self, row: dict) -> dict | None:
        values = self._attribute_values(row)
        first_name = str(values.get("first_name") or "").strip()
        last_name = str(values.get("last_name") or "").strip()
        name = " ".join(part for part in (first_name, last_name) if part)
        if not name:
            return None
        status = values.get("status")
        record: dict[str, object] = {
            "external_id": str(row.get("id")),
            "name": name,
            "email": values.get("email"),
            "active": status == "active",
            "personio_status": status,
        }
        termination = values.get("termination_date")
        if termination not in (None, ""):
            record["personio_termination_date"] = termination
            try:
                termination_date = date.fromisoformat(str(termination)[:10])
            except ValueError:
                termination_date = None
            if termination_date is not None and termination_date <= date.today():
                record["active"] = False
        excluded = {"first_name", "last_name", "email", "status", "termination_date"}
        if self.salary_attribute:
            excluded.add(self.salary_attribute)
            salary = values.get(self.salary_attribute)
            if salary not in (None, ""):
                try:
                    record["gross_salary"] = money(Decimal(str(salary)))
                except InvalidOperation as error:
                    raise ProviderError(
                        f"Personio salary attribute {self.salary_attribute!r} is not numeric"
                    ) from error
        for api_name, value in values.items():
            if api_name not in excluded:
                record[f"personio_{api_name}"] = value
        return record

    def pull(self, object_type: str, *, cursor: str | None = None) -> ConnectorResult:
        if object_type not in {"employee", "employees"}:
            raise ValueError("Personio supports employee imports only")
        token = self._token()
        records: list[dict] = []
        offset = 0
        total = 0
        while True:
            page = self._employee_page(token, offset=offset, updated_since=cursor or "")
            rows = page["rows"]
            total = page["total"]
            for row in rows:
                record = self._employee_record(row)
                if record is not None:
                    records.append(record)
            if not rows:
                break
            next_offset = page["offset"] + len(rows)
            if next_offset <= offset:
                raise ProviderError("Personio employee pagination made no progress")
            offset = next_offset
            if offset >= total:
                break
        return ConnectorResult(
            self.key, f"pull:{object_type}", True, True,
            f"Pulled {len(records)} Personio employee records",
            tuple(records), cursor,
        )

    def push(self, object_type: str, records: list[dict]) -> ConnectorResult:
        del records
        return ConnectorResult(
            self.key, f"push:{object_type}", False, True,
            "Personio is a pull-only employee data source; no records were sent",
        )


class BambooHRProvider(HTTPProvider):
    """Documented-contract directory adapter; salary needs an explicit field alias.

    Directory records normally contain no gross salary. Without a reviewed
    ``salary_field_id`` mapping the canonical record omits ``gross_salary`` and
    the employee pipeline correctly requires local accountant input on apply.
    """

    key = "bamboohr"
    _SUBDOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

    def __init__(self, subdomain: str, api_key: str, *, salary_field_id: str = "", **kwargs):
        super().__init__(**kwargs)
        self.subdomain = str(subdomain or "").strip().lower()
        if not self._SUBDOMAIN.fullmatch(self.subdomain):
            raise ValueError("BambooHR subdomain is invalid")
        self.api_key = str(api_key or "").strip()
        if not self.api_key:
            raise ValueError("BambooHR API key is required")
        self.salary_field_id = str(salary_field_id or "").strip()
        self.base_url = (
            f"https://{self.subdomain}.bamboohr.com/api/gateway.php/{self.subdomain}"
        )

    def _directory(self) -> tuple[list[str], list[dict]]:
        response = self.request(
            "GET",
            f"{self.base_url}/v1/employees/directory",
            headers={"Accept": "application/json", "X-BambooHR-Format": "JSON"},
            auth=(self.api_key, "x"),
        )
        try:
            payload = response.json(parse_float=Decimal)
        except ValueError as error:
            raise ProviderError("BambooHR returned an invalid JSON response") from error
        fields = payload.get("fields") if isinstance(payload, dict) else None
        employees = payload.get("employees") if isinstance(payload, dict) else None
        if not isinstance(fields, list) or not isinstance(employees, list):
            raise ProviderError("BambooHR returned an invalid employee directory response")
        field_ids: list[str] = []
        for field in fields:
            field_id = field.get("id") if isinstance(field, dict) else None
            if not isinstance(field_id, str) or not field_id:
                raise ProviderError("BambooHR returned invalid directory field metadata")
            field_ids.append(field_id)
        if any(not isinstance(employee, dict) for employee in employees):
            raise ProviderError("BambooHR returned invalid employee data")
        return field_ids, employees

    def check(self) -> ConnectorResult:
        try:
            self._directory()
        except httpx.RequestError:
            return ConnectorResult(
                self.key, "check", False, False,
                "BambooHR API could not be reached due to a connection error or timeout",
            )
        except ProviderError as error:
            status = self._status_code(error)
            if status in {401, 403}:
                message = f"BambooHR API authentication failed (HTTP {status})"
            elif status is not None:
                message = f"BambooHR API returned unexpected HTTP {status}"
            else:
                message = str(error)
            return ConnectorResult(self.key, "check", False, True, message)
        return ConnectorResult(
            self.key, "check", True, True,
            "BambooHR API reachable; employee directory succeeded",
        )

    def _employee_record(self, row: dict, field_ids: list[str]) -> dict | None:
        first_name = str(row.get("firstName") or "").strip()
        last_name = str(row.get("lastName") or "").strip()
        name = " ".join(part for part in (first_name, last_name) if part)
        if not name:
            return None
        record: dict[str, object] = {
            "external_id": str(row.get("id")),
            "name": name,
            "email": row.get("workEmail") or row.get("homeEmail"),
        }
        if "status" in row:
            record["active"] = row.get("status") == "Active"
        excluded = {"id", "firstName", "lastName", "workEmail", "homeEmail", "status"}
        if self.salary_field_id:
            excluded.add(self.salary_field_id)
            salary = row.get(self.salary_field_id)
            if salary not in (None, ""):
                try:
                    record["gross_salary"] = money(Decimal(str(salary)))
                except InvalidOperation as error:
                    raise ProviderError(
                        f"BambooHR salary field {self.salary_field_id!r} is not numeric"
                    ) from error
        for field_id in field_ids:
            if field_id not in excluded and field_id in row:
                record[f"bamboo_{field_id}"] = row[field_id]
        return record

    def pull(self, object_type: str, *, cursor: str | None = None) -> ConnectorResult:
        if object_type not in {"employee", "employees"}:
            raise ValueError("BambooHR supports employee imports only")
        del cursor  # The directory contract returns the whole company without a cursor.
        field_ids, rows = self._directory()
        records = tuple(
            record for row in rows
            if (record := self._employee_record(row, field_ids)) is not None
        )
        return ConnectorResult(
            self.key, f"pull:{object_type}", True, True,
            f"Pulled {len(records)} BambooHR employee records", records,
        )

    def push(self, object_type: str, records: list[dict]) -> ConnectorResult:
        del records
        return ConnectorResult(
            self.key, f"push:{object_type}", False, True,
            "BambooHR is a pull-only employee data source; no records were sent",
        )


class MeritProvider(HTTPProvider):
    key = "merit"
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

    def check(self) -> ConnectorResult:
        try:
            # Reuse the existing V2 getpayments resource with an empty signed probe body.
            self.request(
                "GET",
                f"{self.base_url}/getpayments",
                params=self.signed_params(b""),
                headers={"Accept": "application/json"},
            )
        except httpx.RequestError:
            return ConnectorResult(
                self.key,
                "check",
                False,
                False,
                "Merit API could not be reached due to a connection error or timeout",
            )
        except ProviderError as error:
            status = self._status_code(error)
            if status in {401, 403}:
                message = f"Merit API authentication failed (HTTP {status})"
            elif status is not None:
                message = f"Merit API returned unexpected HTTP {status}"
            else:
                message = "Merit API check failed"
            return ConnectorResult(self.key, "check", False, True, message)
        return ConnectorResult(
            self.key,
            "check",
            True,
            True,
            "Merit API reachable; company context valid",
        )


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
