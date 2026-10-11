"""HTTP adapters for supported provider APIs with safe submission gates."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
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
    """Documented accounting contracts for one implicit Merit company.

    Unfiltered customer/vendor lists can fail server-side. With no cursor we
    attempt them once, then retry server errors with ChangedDate=today-365 days.
    Date-window pulls also start there by default; JSON cursors carry the next
    window's ``from`` date. Invoice lists have no lines, so applying their staged
    headers requires reviewed line/account enrichment.
    """

    key = "merit"
    base_url = "https://aktiva.merit.ee/api/v2"
    PULL_OBJECT_TYPES = ("account", "contact", "sales_invoice", "purchase_invoice", "payment", "gl_entry")
    PUSH_OBJECT_TYPES = ("gl_batch", "sales_invoice")

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

    def _accounting_request(self, method: str, endpoint: str, *, version: int = 2,
                            payload: dict | None = None, params: dict | None = None):
        body = (json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
                if method == "POST" else b"")
        query = dict(self.signed_params(body), **(params or {}))
        kwargs = {"params": query, "headers": {"Accept": "application/json"}}
        if method == "POST":
            kwargs.update(content=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            response = self.request(method, f"{self.base_url.rsplit('/', 1)[0]}/v{version}/{endpoint}", **kwargs)
        except httpx.RequestError as error:
            raise ProviderError("Merit accounting API connection error or timeout") from error
        try:
            return json.loads(response.content, parse_float=Decimal)
        except (ValueError, UnicodeError) as error:
            raise ProviderError("Merit returned invalid JSON") from error

    @staticmethod
    def _rows(payload, key: str) -> list[dict]:
        rows = payload.get(key, payload.get("data")) if isinstance(payload, dict) else payload
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ProviderError("Merit returned an invalid accounting list")
        return rows

    @staticmethod
    def _date(value) -> date:
        try:
            text = str(value)
            return date.fromisoformat(text[:10]) if "-" in text else datetime.strptime(text, "%Y%m%d").date()
        except (TypeError, ValueError) as error:
            raise ValueError("Merit requires an ISO or yyyymmdd date") from error

    @staticmethod
    def _decimal(value) -> Decimal:
        try:
            number = Decimal(str(value))
        except (ArithmeticError, ValueError) as error:
            raise ValueError("Merit amount must be a finite decimal") from error
        if not number.is_finite():
            raise ValueError("Merit amount must be a finite decimal")
        return number

    @staticmethod
    def _external_id(row: dict, key: str) -> str:
        if row.get(key) in (None, ""):
            raise ProviderError(f"Merit record is missing {key}")
        return str(row[key])

    def _wire_amount(self, value) -> float:
        number = float(self._decimal(value))
        if not Decimal(str(number)).is_finite():
            raise ValueError("Merit amount exceeds the numeric wire range")
        return number

    def _cursor_start(self, cursor: str | None) -> date:
        if cursor is None:
            return self.clock().date() - timedelta(days=365)
        try:
            state = json.loads(cursor) if cursor.lstrip().startswith("{") else {"from": cursor}
            return self._date(state["from"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Invalid Merit cursor; expected an ISO date or JSON with from") from error

    def _period(self, start: date, end: date, *, max_days: int) -> dict:
        if end < start or (end - start).days + 1 > max_days:
            raise ValueError(f"Merit period must be between 1 and {max_days} days")
        return {"PeriodStart": start.strftime("%Y%m%d"), "PeriodEnd": end.strftime("%Y%m%d")}

    def _contact_record(self, row: dict, role: str) -> dict:
        return {
            "external_id": self._external_id(row, "CustomerId" if role == "customer" else "VendorId"),
            "contact_type": role, "name": row.get("Name", ""),
            "registration_no": row.get("RegNo", ""), "vat_no": row.get("VatRegNo", ""),
            "email": row.get("Email", ""), "country_code": row.get("CountryCode", ""),
            "address": ", ".join(str(row[key]) for key in ("Address", "City", "PostalCode", "CountryName") if row.get(key)),
            "external_version": row.get("ChangedDate"),
        }

    def _invoice_record(self, row: dict, *, purchase: bool) -> dict:
        role = "supplier" if purchase else "customer"
        record = {
            "external_id": self._external_id(row, "PIHId" if purchase else "SIHId"),
            "external_number": row.get("BillNo" if purchase else "InvoiceNo", ""),
            "supplier_name" if purchase else "buyer_name": row.get("VendorName" if purchase else "CustomerName", ""),
            "bill_date" if purchase else "issue_date": self._date(row.get("DocumentDate")).isoformat(),
            "due_date": self._date(row["DueDate"]).isoformat() if row.get("DueDate") else "",
            "currency": row.get("CurrencyCode", "EUR"), "paid": row.get("Paid", False),
            role: {"name": row.get("VendorName" if purchase else "CustomerName", ""),
                   "external_id": row.get("VendorId" if purchase else "CustomerId", ""),
                   "registration_no": row.get("VendorRegNo" if purchase else "CustomerRegNo", "")},
        }
        for source, target in (("TaxAmount", "tax_total"), ("TotalSum", "total"),
                               ("TotalAmount", "total_exvat"), ("PaidAmount", "paid_amount")):
            if row.get(source) is not None:
                record[target] = self._decimal(row[source])
        if purchase:
            record["invoice_date"] = record["bill_date"]
        else:
            record["customer_name"] = record["buyer_name"]
            record["amount_type"] = "inclusive" if row.get("PriceInclVat") else "exclusive"
        if row.get("ChangedDate") is not None:
            record["payload_hash"] = hashlib.sha256(str(row["ChangedDate"]).encode()).hexdigest()
            record["external_version"] = row["ChangedDate"]
        return record

    def _payment_record(self, row: dict) -> dict:
        record = {
            "external_id": self._external_id(row, "PIHId"), "amount": self._decimal(row.get("Amount")),
            "payment_date": self._date(row.get("DocumentDate")).isoformat(),
            "reference": row.get("DocumentNo", ""), "currency": row.get("CurrencyCode", "EUR"),
            "CounterPartType": row.get("CounterPartType"), "CounterPartName": row.get("CounterPartName"),
            "CounterPartId": row.get("CounterPartId"), "Direction": row.get("Direction"),
        }
        direction = str(row.get("Direction"))
        if direction in {"1", "2"}:
            record["payment_type"] = "customer_receipt" if direction == "1" else "supplier_payment"
        else:
            record["merit_payment_note"] = "Other income/expense direction; needs manual handling"
            # The reviewed pipeline displays import_warning as its review note.
            record["import_warning"] = record["merit_payment_note"]
        details = row.get("PaymAPIDetails")
        if details is not None:
            if not isinstance(details, dict):
                raise ProviderError("Merit returned invalid payment allocation details")
            record["document_external_id"] = details.get("DocId", "")
            record["PaymAPIDetails"] = dict(details)
            if details.get("PaidAmount") is not None:
                record["PaymAPIDetails"]["PaidAmount"] = self._decimal(details["PaidAmount"])
        return record

    def pull(self, object_type: str, *, cursor: str | None = None) -> ConnectorResult:
        if object_type not in self.PULL_OBJECT_TYPES:
            raise ValueError(f"Unsupported Merit pull object type: {object_type}")
        records: list[dict] = []
        next_cursor = None
        if object_type == "account":
            rows = self._rows(self._accounting_request("GET", "accounts", params={"UsageFilter": 0}), "Accounts")
            records = [{"external_id": self._external_id(row, "AccountID"), "code": row.get("Code", ""),
                        "name": row.get("Name") or row.get("NameET") or row.get("NameEN") or ""} for row in rows]
        elif object_type == "contact":
            for endpoint, key, role in (("getcustomers", "Customers", "customer"), ("getvendors", "Vendors", "supplier")):
                params = {"ChangedDate": self._cursor_start(cursor).strftime("%Y%m%d")} if cursor else {}
                try:
                    payload = self._accounting_request("GET", endpoint, version=1, params=params)
                except ProviderError as error:
                    if cursor or self._status_code(error) not in {500, 502, 503, 504}:
                        raise
                    payload = self._accounting_request("GET", endpoint, version=1, params={
                        "ChangedDate": self._cursor_start(None).strftime("%Y%m%d")})
                records.extend(self._contact_record(row, role) for row in self._rows(payload, key))
        else:
            days = 31 if object_type == "gl_entry" else 90
            start = self._cursor_start(cursor)
            today = self.clock().date()
            end = min(start + timedelta(days=days - 1), today)
            payload = self._period(start, end, max_days=days)
            endpoint, key, version = {
                "sales_invoice": ("getinvoices", "Invoices", 2),
                "purchase_invoice": ("getpurchorders", "PurchOrders", 2),
                "payment": ("getpayments", "Payments", 2),
                "gl_entry": ("GetGLBatchesFull", "GLBatches", 1),
            }[object_type]
            if object_type != "sales_invoice":
                payload["DateType"] = 0
            if object_type == "purchase_invoice":
                payload["UnPaid"] = False
            if object_type == "gl_entry":
                payload["WithLines"] = 1
            rows = self._rows(self._accounting_request("POST", endpoint, version=version, payload=payload), key)
            if object_type in {"sales_invoice", "purchase_invoice"}:
                records = [self._invoice_record(row, purchase=object_type == "purchase_invoice") for row in rows]
            elif object_type == "payment":
                records = [self._payment_record(row) for row in rows]
            else:
                for batch in rows:
                    batch_id = self._external_id(batch, "GLBId")
                    for index, line in enumerate(self._rows(batch.get("Entries"), "Entries"), start=1):
                        records.append({
                            "external_id": f"{batch_id}:{line.get('LineNo') or line.get('line_no') or index}",
                            "external_batch_ref": batch.get("BatchCode", ""),
                            "entry_date": self._date(batch.get("BatchDate")).isoformat(),
                            "currency": batch.get("CurrencyCode", "EUR"),
                            "external_account_code": line.get("AccountCode", ""),
                            "description": line.get("Memo", ""), "document": line.get("Document", batch.get("Document", "")),
                            "debit": self._decimal(line.get("DebitAmount", 0)),
                            "credit": self._decimal(line.get("CreditAmount", 0)),
                            "dims": line.get("CostAllocLines", []), "merit_tax_id": line.get("TaxId"),
                        })
            if end < today:
                next_cursor = json.dumps({"from": (end + timedelta(days=1)).isoformat()}, separators=(",", ":"))
        return ConnectorResult(self.key, f"pull:{object_type}", True, True,
                               f"Pulled {len(records)} Merit {object_type} records", tuple(records), next_cursor)

    def push(self, object_type: str, records: list[dict]) -> ConnectorResult:
        if object_type not in self.PUSH_OBJECT_TYPES:
            raise ValueError(f"Unsupported Merit push object type: {object_type}")
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("Merit push records must be objects")
        responses = []
        if object_type == "sales_invoice":
            for record in records:
                try:
                    response = self.create_invoice(record)
                except httpx.RequestError as error:
                    raise ProviderError("Merit invoice API connection error or timeout") from error
                if not isinstance(response, dict):
                    raise ProviderError("Merit returned an invalid invoice response")
                responses.append(response)
        else:
            payloads = []
            for record in records:
                doc_no = str(record.get("doc_no") or "")
                if not doc_no or len(doc_no) > 35:
                    raise ValueError("Merit DocNo must contain 1 to 35 characters")
                lines = record.get("lines")
                if not isinstance(lines, list) or not lines:
                    raise ValueError("Merit GL batch requires lines")
                currency = record.get("currency") or "EUR"
                if currency != "EUR":
                    raise ValueError("Merit GL batch push supports EUR only")
                entries = []
                for line in lines:
                    if not isinstance(line, dict):
                        raise ValueError("Merit GL lines must be objects")
                    account = str(line.get("account_code") or line.get("external_account_code") or "")
                    memo = str(line.get("memo") or line.get("description") or "")
                    if not account or len(account) > 8 or len(memo) > 150:
                        raise ValueError("Merit AccountCode must contain 1 to 8 characters; Memo at most 150")
                    # Numeric floats are confined to the Merit wire format, never accounting arithmetic.
                    entries.append({"AccountCode": account, "Debit": self._wire_amount(line.get("debit", 0)),
                                    "Credit": self._wire_amount(line.get("credit", 0)), "Memo": memo})
                for offset in range(0, len(entries), 500):
                    suffix = f"-{offset // 500 + 1}" if offset else ""
                    payloads.append({"DocNo": doc_no[:35 - len(suffix)] + suffix,
                                     "BatchDate": self._date(record.get("posting_date")).strftime("%Y%m%d"),
                                     "CurrencyCode": currency, "EntryRow": entries[offset:offset + 500]})
            for payload in payloads:
                response = self._accounting_request("POST", "sendglbatch", version=1, payload=payload)
                if not isinstance(response, dict):
                    raise ProviderError("Merit returned an invalid GL batch response")
                responses.append(response)
        return ConnectorResult(self.key, f"push:{object_type}", True, True,
                               f"Sent {len(responses)} Merit {object_type} requests", tuple(responses))

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


class SmartAccountsProvider(HTTPProvider):
    """Official documented contract; each pull reads one page of a frozen window."""

    key = "smartaccounts"
    default_base_url = "https://sa.smartaccounts.eu"
    PULL_OBJECT_TYPES = ("account", "contact", "sales_invoice", "purchase_invoice", "payment", "gl_entry")
    PUSH_OBJECT_TYPES = ("gl_batch",)
    _ENDPOINTS = {
        "account": ("settings/accounts", "accounts"),
        "contact": ("purchasesales/clients", "clients"),
        "sales_invoice": ("purchasesales/clientinvoices", "clientInvoices"),
        "purchase_invoice": ("purchasesales/vendorinvoices", "vendorInvoices"),
        "payment": ("purchasesales/payments", "payments"),
        "gl_entry": ("general/entries", "entries"),
    }

    def __init__(self, api_key: str, secret_key: str, *, lang: str = "et",
                 clock: Callable[[], datetime] | None = None, **kwargs):
        super().__init__(**kwargs)
        if lang not in {"en", "et"}:
            raise ValueError("SmartAccounts language must be en or et")
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            self.tallinn = ZoneInfo("Europe/Tallinn")
        except ZoneInfoNotFoundError as error:
            raise ValueError("SmartAccounts needs Europe/Tallinn timezone data; pip install tzdata") from error
        self.api_key, self.secret_key, self.lang = api_key, secret_key, lang
        self.base_url = f"{self.default_base_url}/{lang}/api"
        self.clock = clock or (lambda: datetime.now(self.tallinn))

    def _now(self) -> datetime:
        instant = self.clock()
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("SmartAccounts clock must be timezone-aware")
        return instant.astimezone(self.tallinn)

    def _signature(self, query_string: str, body: str = "") -> str:
        return hmac.new(self.secret_key.encode(), (query_string + body).encode("utf-8"),
                        hashlib.sha256).hexdigest()

    def _accounting_request(self, method: str, endpoint: str, *, params: dict | None = None,
                            payload: dict | None = None):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) if payload is not None else ""
        # Endpoint parameters precede auth, matching the official encoded codes example.
        query = urlencode([*(params or {}).items(), ("timestamp", self._now().strftime("%d%m%Y%H%M%S")),
                           ("apikey", self.api_key)])
        url = f"{self.base_url}/{endpoint}?{query}&{urlencode({'signature': self._signature(query, body)})}"
        try:
            response = self.request(method, url, content=body.encode("utf-8") if payload is not None else None,
                                    headers={"Accept": "application/json", "Content-Type": "application/json"})
        except httpx.RequestError as error:
            raise ProviderError("SmartAccounts API connection error or timeout") from error
        try:
            return response.json(parse_float=Decimal)
        except ValueError as error:
            raise ProviderError("SmartAccounts returned invalid JSON") from error

    @staticmethod
    def _decimal(value) -> Decimal:
        try:
            if isinstance(value, bool):
                raise ValueError
            amount = Decimal(str(value))
            if not amount.is_finite():
                raise ValueError
            return amount
        except (ArithmeticError, ValueError) as error:
            raise ValueError("SmartAccounts amount must be a finite decimal") from error

    def _wire_amount(self, value) -> float:
        amount = self._decimal(value)
        # Floats are confined to JSON numbers, safe for two-decimal EUR amounts.
        number = float(amount)
        if not Decimal(str(number)).is_finite() or Decimal(str(number)) != amount:
            raise ValueError("SmartAccounts amount exceeds the safe numeric wire range")
        return number

    @staticmethod
    def _date(value) -> date:
        if isinstance(value, date):
            return value.date() if isinstance(value, datetime) else value
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(str(value), fmt).date()
            except ValueError:
                pass
        raise ValueError("SmartAccounts date must be ISO or dd.MM.yyyy")

    @staticmethod
    def _id(row: dict) -> str:
        if row.get("id") in (None, ""):
            raise ProviderError("SmartAccounts record is missing id")
        return str(row["id"])

    @staticmethod
    def _rows(payload, key: str) -> list[dict]:
        if isinstance(payload, dict) and ("error" in payload or "errors" in payload):
            raise ProviderError("SmartAccounts returned an error response")
        rows = payload if isinstance(payload, list) else payload.get(key) if isinstance(payload, dict) else None
        # The document defines fields but not every list envelope name. Accept
        # one unambiguous collection, excluding the documented deletion list.
        if rows is None and isinstance(payload, dict):
            collections = [value for name, value in payload.items() if name != "deleted" and isinstance(value, list)]
            if len(collections) == 1:
                rows = collections[0]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ProviderError(f"SmartAccounts returned invalid {key} data")
        return rows

    def _contact_record(self, row: dict) -> dict:
        address = row.get("address") or {}
        record = {
            "external_id": self._id(row), "contact_type": "customer", "name": row.get("name", ""),
            "registration_no": row.get("regCode", ""), "vat_no": row.get("vatNumber", ""),
            "email": next((item.get("value", "") for item in row.get("contacts", []) if item.get("type") == "EMAIL"), ""),
            "country_code": address.get("country", ""),
            "address": ", ".join(str(address[key]) for key in ("address1", "address2", "city", "postalCode", "county") if address.get(key)),
        }
        for key in ("bankAccount", "referenceNumber", "invoiceDueDate", "ignoreOnVatDeclaration"):
            if key in row:
                record[key] = row[key]
        if row.get("dateUpdated") or row.get("dateCreated"):
            record["external_version"] = row.get("dateUpdated") or row["dateCreated"]
        return record

    def _invoice_record(self, row: dict, *, purchase: bool) -> dict:
        partner = row.get("vendor" if purchase else "client") or {}
        role = "supplier" if purchase else "customer"
        record = {
            "external_id": self._id(row), "external_number": row.get("invoiceNumber", ""),
            "supplier_name" if purchase else "buyer_name": partner.get("name", ""),
            "bill_date" if purchase else "issue_date": self._date(row.get("date")).isoformat(),
            "due_date": self._date(row["dueDate"]).isoformat() if row.get("dueDate") else "",
            "currency": row.get("currency") or "EUR", "amount_type": "exclusive",
            role: {"name": partner.get("name", ""),
                   "external_id": row.get("vendorId" if purchase else "clientId") or partner.get("id", ""),
                   "registration_no": partner.get("regCode", ""), "vat_no": partner.get("vatNumber", "")},
        }
        for source, target in (("amount", "total_exvat"), ("vatAmount", "tax_total"), ("totalAmount", "total"),
                               ("outstandingAmount", "outstanding_amount"), ("roundAmount", "round_amount")):
            if row.get(source) is not None:
                record[target] = self._decimal(row[source])
        record["paid"] = record.get("outstanding_amount") == Decimal("0")
        if "total" in record and "outstanding_amount" in record:
            record["paid_amount"] = record["total"] - record["outstanding_amount"]
        if row.get("dateUpdated") or row.get("dateCreated"):
            record["external_version"] = row.get("dateUpdated") or row["dateCreated"]
        # Retain remote rows for review. Tax percentages require explicit local tax mappings.
        record["smartaccounts_rows"] = self._rows(row.get("rows", []), "rows")
        return record

    def _payment_records(self, row: dict) -> list[dict]:
        base = {"external_id": self._id(row), "amount": self._decimal(row.get("amount", 0)),
                "payment_date": self._date(row.get("date")).isoformat(),
                "reference": row.get("document") or row.get("number", ""), "currency": row.get("currency") or "EUR",
                "smartaccounts_account_name": row.get("accountName"), "smartaccounts_account_type": row.get("accountType")}
        records = []
        for index, allocation in enumerate(self._rows(row.get("rows", []), "rows"), start=1):
            record = dict(base, external_id=f"{base['external_id']}:{index}", amount=self._decimal(allocation.get("amount", 0)))
            if allocation.get("type") in {"CLIENT_INVOICE", "VENDOR_INVOICE"} and allocation.get("id") not in (None, ""):
                record["document_external_id"] = str(allocation["id"])
                record["payment_type"] = "customer_receipt" if allocation["type"] == "CLIENT_INVOICE" else "supplier_payment"
            else:
                record["import_warning"] = "Payment allocation requires manual handling"
            records.append(record)
        return records or [dict(base, import_warning="Payment has no invoice allocations; requires manual handling")]

    def pull(self, object_type: str, *, cursor: str | None = None) -> ConnectorResult:
        if object_type not in self.PULL_OBJECT_TYPES:
            raise ValueError(f"Unsupported SmartAccounts pull object type: {object_type}")
        endpoint, key = self._ENDPOINTS[object_type]
        params, state = {}, {}
        if object_type != "account":
            try:
                state = json.loads(cursor) if cursor else {}
                page = state.get("page", 1)
                if not isinstance(page, int) or isinstance(page, bool) or page < 1:
                    raise ValueError
                params["pageNumber"] = page
                if object_type == "contact":
                    params.update(fetchContacts="true", fetchAddresses="true")
                else:
                    today = self._now().date()
                    start = self._date(state.get("from", (today - timedelta(days=365)).isoformat()))
                    end = self._date(state.get("to", min(start + timedelta(days=89), today).isoformat()))
                    if end < start or end > today or (end - start).days >= 90:
                        raise ValueError
                    state = {"from": start.isoformat(), "to": end.isoformat()}
                    params.update(dateFrom=start.strftime("%d.%m.%Y"), dateTo=end.strftime("%d.%m.%Y"), dateType="date", fetchRows="true")
                    if object_type == "gl_entry":
                        params["docType"] = "LEDGER_ENTRY"
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError("Invalid SmartAccounts cursor") from error
        payload = self._accounting_request("GET", endpoint + ":get", params=params)
        rows = self._rows(payload, key)
        next_cursor = None
        if object_type != "account":
            if not isinstance(payload, dict) or not isinstance(payload.get("hasMoreEntries"), bool):
                raise ProviderError("SmartAccounts returned invalid pagination metadata")
            if payload["hasMoreEntries"]:
                state["page"] = page + 1
                next_cursor = json.dumps(state, separators=(",", ":"))
            elif object_type != "contact" and end < today:
                next_cursor = json.dumps({"from": (end + timedelta(days=1)).isoformat()}, separators=(",", ":"))
        records = []
        for row in rows:
            if object_type == "account":
                records.append({"external_id": self._id(row), "code": row.get("code", ""),
                                "name": row.get("descriptionEn" if self.lang == "en" else "descriptionEt") or row.get("descriptionEt") or row.get("descriptionEn", ""),
                                "type": row.get("type")})
            elif object_type == "contact":
                records.append(self._contact_record(row))
            elif object_type in {"sales_invoice", "purchase_invoice"}:
                records.append(self._invoice_record(row, purchase=object_type == "purchase_invoice"))
            elif object_type == "payment":
                records.extend(self._payment_records(row))
            else:
                for index, line in enumerate(self._rows(row.get("rows"), "rows"), start=1):
                    records.append({"external_id": f"{self._id(row)}:{index}", "external_batch_ref": row.get("document", ""),
                                    "entry_date": self._date(row.get("date")).isoformat(), "document": row.get("document", ""),
                                    "external_account_code": line.get("account", ""), "description": line.get("description", ""),
                                    "debit": self._decimal(line.get("debitAmount", 0)), "credit": self._decimal(line.get("creditAmount", 0)),
                                    "currency": row.get("currency") or "EUR", "dims": {"objectId": line.get("objectId")}})
        return ConnectorResult(self.key, f"pull:{object_type}", True, True,
                               f"Pulled {len(records)} SmartAccounts {object_type} records", tuple(records), next_cursor)

    def push(self, object_type: str, records: list[dict]) -> ConnectorResult:
        if object_type not in self.PUSH_OBJECT_TYPES:
            raise ValueError(f"Unsupported SmartAccounts push object type: {object_type}")
        payloads = []
        # Validate every batch before any irreversible provider request.
        for record in records:
            if not isinstance(record, dict) or not str(record.get("doc_no") or "").strip():
                raise ValueError("SmartAccounts GL batch requires a document number")
            if (record.get("currency") or "EUR") != "EUR":
                raise ValueError("SmartAccounts GL batch push supports EUR only")
            lines = record.get("lines")
            if not isinstance(lines, list) or not lines:
                raise ValueError("SmartAccounts GL batch requires lines")
            rows, debit_total, credit_total = [], Decimal(0), Decimal(0)
            for line in lines:
                if not isinstance(line, dict):
                    raise ValueError("SmartAccounts GL lines must be objects")
                account = str(line.get("external_account_code") or line.get("account_code") or "").strip()
                debit, credit = self._decimal(line.get("debit", 0)), self._decimal(line.get("credit", 0))
                if not account or debit < 0 or credit < 0 or (debit and credit):
                    raise ValueError("SmartAccounts GL line requires an account and one non-negative side")
                try:
                    if debit != money(debit) or credit != money(credit):
                        raise ValueError("SmartAccounts EUR amounts require at most two decimal places")
                except ArithmeticError as error:
                    raise ValueError("SmartAccounts amount exceeds the numeric wire range") from error
                debit_total += debit
                credit_total += credit
                rows.append({"account": account, "description": line.get("memo") or line.get("description") or "",
                             "debitAmount": self._wire_amount(debit), "creditAmount": self._wire_amount(credit)})
            if debit_total != credit_total or debit_total <= 0:
                raise ValueError("SmartAccounts GL batch must be balanced with a positive total")
            payloads.append({"docType": "LEDGER_ENTRY", "date": self._date(record.get("posting_date")).isoformat(),
                             "document": str(record["doc_no"]), "currency": "EUR", "rows": rows,
                             "comment": str(record.get("comment") or "")})
        responses = []
        for payload in payloads:
            response = self._accounting_request("POST", "general/entries:add", payload=payload)
            if not isinstance(response, dict):
                raise ProviderError("SmartAccounts returned invalid GL batch response")
            responses.append(dict(response, external_id=self._id(response)))
        return ConnectorResult(self.key, f"push:{object_type}", True, True,
                               f"Sent {len(responses)} SmartAccounts GL batches", tuple(responses))

    def check(self) -> ConnectorResult:
        try:
            self._rows(self._accounting_request("GET", "settings/accounts:get"), "accounts")
        except ProviderError as error:
            if isinstance(error.__cause__, httpx.RequestError):
                return ConnectorResult(self.key, "check", False, False, "SmartAccounts API connection error or timeout")
            status = self._status_code(error)
            message = f"SmartAccounts API authentication failed (HTTP {status})" if status in {401, 403} else "SmartAccounts API check failed"
            return ConnectorResult(self.key, "check", False, True, message)
        return ConnectorResult(self.key, "check", True, True, "SmartAccounts API reachable; company context valid")


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
