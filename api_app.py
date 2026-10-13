"""Typed FastAPI surface for the FastAccounts bookkeeping workspace."""
from __future__ import annotations

import os
import secrets
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator, model_validator

import integrations
import version
from automation import AutomationService, email_configured, email_status
from open_banking import OpenBankingService
from banking import BankingService
from connectors.registry import provider_metadata
from database import get_database
from documents import DocumentService, EInvoiceAlreadyImported
from bulk_sending import BulkSendingService, MAX_BULK_INVOICES
from invoice_list import InvoiceListService, validate_list_dates
from csv_exports import CsvExportService
from copilot import CopilotDisabled, CopilotQuotaExceeded, CopilotService
from list_export_repository import ListExportRepository
from quotes import QuoteService
from periodisation import PeriodisationService
from payment_links import PaymentLinkService
from tax_replacement import TaxReplacementService
from exchange_rates import ExchangeRateService
from fx_revaluation import FxRevaluationService
from reminder_rules import ReminderRuleService, validate_rule
from document_settings import DocumentSettingsService, MAX_LOGO_BYTES
from objects import ObjectService
from statements import StatementService
from cash_flow import CashFlowService
from excel_export import (employees_workbook, general_ledger_workbook,
                          invoices_workbook, vat_returns_workbook)
from governance import GovernanceService
from import_service import OBJECT_TYPES, ImportService, MasterDataImportService
from master_data_maintenance import MasterDataMaintenanceService
from push_service import PushService
from integration_service import AccountMappingService, IntegrationService
from ledger import LedgerService, PostingLine
from organisations import APPROVE_ROLES, WRITE_ROLES, AccessDenied, OrganisationService
from payroll import PayrollConflict, PayrollService
from tax import TaxService
from tsd import TSDExportService
from payment_orders import PaymentOrderService
from prepayments import PrepaymentService
from fixed_assets import FixedAssetService
from opening_balances import OpeningBalanceService, parse_open_items_csv


class User(BaseModel):
    email: str
    name: str = ""


class OrganisationIn(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    country_code: Literal["UK", "EE"]
    entity_type: Literal["UK_COMPANY", "UK_SOLE_TRADER", "EE_OU", "EE_FIE"]
    registration_no: str = ""
    vat_no: str = ""
    fiscal_year_start: int = Field(default=1, ge=1, le=12)


class ContactIn(BaseModel):
    name: str
    country_code: str
    contact_type: Literal["customer", "supplier", "both"] = "both"
    email: str = ""
    vat_no: str = ""
    registration_no: str = ""
    address: str = ""
    iban: str = ""
    payment_terms_days: int = Field(default=14, ge=0, le=365)


class LineIn(BaseModel):
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    account_id: str
    tax_code_id: str | None = None


class DimensionIn(BaseModel):
    projects_project_id: str | None = None
    projects_location_id: str | None = None
    projects_person_id: str | None = None
    projects_object_id: str | None = None


class ObjectLineIn(LineIn, DimensionIn):
    pass


class ObjectIn(BaseModel):
    model_config = {'extra': 'forbid'}
    object_type: Literal['project', 'location', 'person', 'object']
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=180)
    active: bool = Field(default=True, strict=True)
    notes: str = Field(default='', max_length=2000)


class ObjectPatch(BaseModel):
    model_config = {'extra': 'forbid'}
    object_type: Literal['project', 'location', 'person', 'object'] | None = None
    code: str | None = Field(default=None, min_length=1, max_length=40)
    name: str | None = Field(default=None, min_length=1, max_length=180)
    active: bool | None = Field(default=None, strict=True)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator('object_type', 'code', 'name', 'active', 'notes')
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError('Object fields cannot be null')
        return value


class FxRevaluationIn(BaseModel):
    model_config = {'extra': 'forbid'}
    revaluation_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')

    @field_validator('revaluation_date')
    @classmethod
    def valid_date(cls, value):
        date.fromisoformat(value)
        return value


class ExchangeRateIn(BaseModel):
    model_config = {'extra': 'forbid'}
    rate_date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    from_currency: str = Field(pattern=r'^[A-Z]{3}$')
    to_currency: str = Field(pattern=r'^[A-Z]{3}$')
    rate: Decimal = Field(gt=0, max_digits=20, decimal_places=10)

    @field_validator('rate_date')
    @classmethod
    def valid_date(cls, value):
        date.fromisoformat(value)
        return value

    @model_validator(mode='after')
    def different_currencies(self):
        if self.from_currency == self.to_currency:
            raise ValueError('From and to currencies must differ')
        return self


class InvoiceIn(BaseModel):
    contact_id: str
    issue_date: str
    due_date: str | None = None
    currency: str | None = None
    exchange_rate: Decimal | None = Field(default=None, gt=0)
    amount_type: Literal["exclusive", "inclusive", "no_tax"] = "exclusive"
    reference: str = ""
    notes: str = ""
    document_type: Literal["invoice", "credit_note"] = "invoice"
    original_invoice_id: str | None = None
    lines: list[ObjectLineIn] = Field(min_length=1)


class BulkSendIn(BaseModel):
    model_config = {'extra': 'forbid'}
    invoice_ids: list[str] = Field(min_length=1, max_length=MAX_BULK_INVOICES)


class QuoteIn(BaseModel):
    contact_id: str
    quote_date: str
    valid_until: str
    currency: str | None = None
    amount_type: Literal["exclusive", "inclusive", "no_tax"] = "exclusive"
    notes: str = ""
    lines: list[LineIn] = Field(min_length=1)


class QuotePatch(BaseModel):
    contact_id: str | None = None
    quote_date: str | None = None
    valid_until: str | None = None
    currency: str | None = None
    amount_type: Literal["exclusive", "inclusive", "no_tax"] | None = None
    notes: str | None = None
    lines: list[LineIn] | None = Field(default=None, min_length=1)

    @field_validator('contact_id', 'quote_date', 'valid_until', 'amount_type', 'notes', 'lines')
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError('Quote fields cannot be null')
        return value


class PurchaseScheduleIn(BaseModel):
    model_config = {'extra': 'forbid'}
    bill_id: str
    expense_account_id: str
    start_period: str
    number_of_periods: int = Field(ge=1, le=120, strict=True)
    amount: Decimal | None = None
    split_rule: Literal['equal_first', 'equal_last'] = 'equal_first'
    status: Literal['Draft', 'Active'] = 'Active'
    notes: str = ''


class ReminderRuleIn(BaseModel):
    model_config = {'extra': 'forbid'}
    enabled: bool = Field(strict=True)
    stages: dict[str, int] = Field(strict=True)
    stop_stage: int | None = Field(default=None, strict=True)

    @field_validator('stages', mode='before')
    @classmethod
    def strict_days(cls, value):
        if not isinstance(value, dict) or any(type(day) is not int for day in value.values()):
            raise ValueError('Reminder offsets must increase strictly within 1 to 14 days after due')
        return value

    @model_validator(mode='after')
    def valid_rule(self):
        validate_rule(self.model_dump())
        return self


class DocumentSettingsIn(BaseModel):
    model_config = {'extra': 'forbid'}
    accent_colour: str | None = Field(default=None, pattern=r'^#[0-9a-fA-F]{6}$')
    footer_text: str | None = Field(default=None, max_length=500)


class PaymentMethodIn(BaseModel):
    model_config = {'extra': 'forbid'}
    provider: Literal['everypay', 'linkpay', 'custom']
    name: str = Field(min_length=1, max_length=120)
    url_template: str = Field(min_length=1, max_length=2000)
    enabled: bool = Field(default=False, strict=True)
    currency: str = Field(default='', max_length=3)


class PaymentMethodPatch(BaseModel):
    model_config = {'extra': 'forbid'}
    provider: Literal['everypay', 'linkpay', 'custom'] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    url_template: str | None = Field(default=None, min_length=1, max_length=2000)
    enabled: bool | None = Field(default=None, strict=True)
    currency: str | None = Field(default=None, max_length=3)

    @field_validator('provider', 'name', 'url_template', 'enabled', 'currency')
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError('Payment method fields cannot be null')
        return value


class PurchaseSchedulePatch(BaseModel):
    model_config = {'extra': 'forbid'}
    status: Literal['Active'] | None = None
    notes: str | None = None

    @field_validator('status', 'notes')
    @classmethod
    def reject_null(cls, value):
        if value is None:
            raise ValueError('Purchase schedule fields cannot be null')
        return value


class PurchasePeriodPostIn(BaseModel):
    model_config = {'extra': 'forbid'}
    as_at: str | None = None
    period_id: str | None = None


class BillIn(BaseModel):
    contact_id: str
    supplier_number: str
    bill_date: str
    due_date: str
    currency: str | None = None
    exchange_rate: Decimal | None = Field(default=None, gt=0)
    reference: str = ""
    notes: str = ""
    document_type: Literal["bill", "supplier_credit"] = "bill"
    lines: list[ObjectLineIn] = Field(min_length=1)


class InvoiceScheduleIn(BaseModel):
    template_invoice_id: str
    interval_kind: Literal["weekly", "monthly", "quarterly", "custom_days"]
    next_run_date: str
    interval_days: int | None = None
    end_date: str | None = None
    auto_email: bool = False
    name: str = ""


class InvoiceSchedulePatch(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(default=None)
    interval_kind: Literal["weekly", "monthly", "quarterly", "custom_days"] = Field(default=None)
    interval_days: int | None = None
    next_run_date: str = Field(default=None)
    end_date: str | None = None
    auto_email: bool = Field(default=None)
    active: bool = Field(default=None)


class ReminderOptOutIn(BaseModel):
    reminders_disabled: bool


class BankAccountIn(BaseModel):
    name: str
    currency: str
    iban: str = ""
    sort_code: str = ""


class PaymentOrderIn(BaseModel):
    bank_account_id: str
    execution_date: str
    due_before: str | None = None
    bill_ids: list[str] | None = None


class PrepaymentIn(BaseModel):
    side: Literal["customer", "supplier"]
    contact_id: str
    bank_account_id: str
    document_date: str
    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    currency: str | None = None
    reference: str = Field(default="", max_length=240)
    idempotency_key: str = Field(min_length=1, max_length=160)


class PrepaymentAllocationIn(BaseModel):
    document_type: Literal["invoice", "bill"]
    document_id: str
    allocation_date: str
    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    idempotency_key: str = Field(min_length=1, max_length=160)


class PrepaymentRefundIn(BaseModel):
    refund_date: str
    amount: Decimal = Field(gt=0, allow_inf_nan=False)
    reference: str = Field(default="", max_length=240)
    idempotency_key: str = Field(min_length=1, max_length=160)


class AssetGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    annual_percentage: Decimal = Field(gt=0, le=100, allow_inf_nan=False)
    frequency: Literal["monthly", "quarterly", "yearly"] = "monthly"
    asset_account_id: str | None = None
    accumulated_depreciation_account_id: str | None = None
    expense_account_id: str | None = None


class FixedAssetIn(BaseModel):
    group_id: str
    name: str = Field(min_length=1, max_length=240)
    acquisition_date: str
    acquisition_cost: Decimal = Field(gt=0, allow_inf_nan=False)
    bank_account_id: str
    idempotency_key: str = Field(min_length=1, max_length=160)


class AssetDisposalIn(BaseModel):
    disposal_date: str
    disposal_amount: Decimal = Field(ge=0, allow_inf_nan=False)
    bank_account_id: str


class DepreciationRunIn(BaseModel):
    period_date: str
    kind: Literal["monthly", "quarterly", "yearly"] = "monthly"


class ReconcileIn(BaseModel):
    target_type: Literal["invoice", "bill"]
    target_id: str


class SplitAllocationIn(BaseModel):
    target_type: Literal["invoice", "bill"]
    target_id: str
    amount: Decimal


class SplitReconcileIn(BaseModel):
    allocations: list[SplitAllocationIn] = Field(min_length=2)


class TaxPrepareIn(BaseModel):
    period_start: str
    period_end: str
    basis: Literal["accrual", "cash"] = "accrual"


class IntegrationIn(BaseModel):
    credentials: dict[str, Any]
    config: dict[str, Any] = Field(default_factory=dict)
    external_tenant_id: str = ""


class IntegrationTestIn(BaseModel):
    credentials: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectorResultOut(BaseModel):
    provider: str
    operation: str
    ok: bool
    live: bool
    message: str


class IntegrationSyncIn(BaseModel):
    object_type: str = Field(min_length=1, max_length=80)

    @field_validator("object_type")
    @classmethod
    def supported_object_type(cls, value: str) -> str:
        key = value.strip().lower()
        if key not in OBJECT_TYPES:
            raise ValueError("Unsupported reviewed import object type")
        return key


class FileImportIn(BaseModel):
    object_type: str = Field(min_length=1, max_length=80)
    csv_content: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class IntegrationApplyIn(BaseModel):
    decisions: dict[str, Literal["apply", "reject"]] = Field(default_factory=dict)


class AccountMappingIn(BaseModel):
    model_config = {"extra": "forbid"}

    local_account_code: str = Field(min_length=1, max_length=80)
    external_account_code: str = Field(min_length=1, max_length=160)
    external_account_name: str = Field(default="", max_length=240)
    status: Literal["Suggested", "Confirmed", "Disabled"] = "Suggested"
    is_default: bool = False


class AccountMappingUpdateIn(BaseModel):
    model_config = {"extra": "forbid"}

    status: Literal["Suggested", "Confirmed", "Disabled"]
    is_default: bool


class BasicJournalLineIn(BaseModel):
    account_id: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    memo: str = ""


class JournalLineIn(BasicJournalLineIn, DimensionIn):
    pass


class JournalIn(BaseModel):
    voucher_code: str
    posting_date: str
    currency: str
    idempotency_key: str
    lines: list[JournalLineIn] = Field(min_length=2)


class OpeningBalanceIn(BaseModel):
    posting_date: str
    lines: list[BasicJournalLineIn]


class OpeningCSVIn(BaseModel):
    csv_content: str = Field(min_length=1, max_length=2_000_000)


class OpeningItemsIn(BaseModel):
    posting_date: str
    csv_content: str | None = Field(default=None, min_length=1, max_length=2_000_000)
    rows: list[dict[str, Any]] | None = None


class InvitationIn(BaseModel):
    email: str
    role: Literal["owner", "administrator", "accountant", "approver", "viewer"]
    valid_days: int = Field(default=7, ge=1, le=30)


class InvitationAcceptIn(BaseModel):
    token: str


api = FastAPI(
    title="FastAccounts API", version=version.VERSION,
    description="Open bookkeeping API for UK and Estonian companies and sole traders/FIEs.",
)

origins = [item.strip() for item in os.getenv("FASTACCOUNTS_CORS_ORIGINS", "").split(",") if item.strip()]
if origins:
    api.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "X-CSRF-Token"])


@api.exception_handler(ValueError)
async def invalid_value(_request: Request, error: ValueError):
    return JSONResponse({"detail": str(error)}, status_code=422)


@api.exception_handler(KeyError)
async def missing_value(_request: Request, error: KeyError):
    return JSONResponse({"detail": str(error.args[0])}, status_code=404)


@api.exception_handler(CopilotDisabled)
async def copilot_disabled(_request: Request, error: CopilotDisabled):
    return JSONResponse({"detail": str(error)}, status_code=409)


@api.exception_handler(CopilotQuotaExceeded)
async def copilot_quota(_request: Request, error: CopilotQuotaExceeded):
    return JSONResponse({"detail": str(error)}, status_code=429)


@api.exception_handler(AccessDenied)
async def forbidden(_request: Request, error: AccessDenied):
    return JSONResponse({"detail": str(error)}, status_code=403)


def current_user(request: Request, x_test_user: str = Header(default="")) -> User:
    session_user = request.session.get("user") if "session" in request.scope else None
    if session_user and session_user.get("email"):
        from web.account_auth import session_user_valid
        if not session_user_valid(session_user):
            request.session.clear()
            raise HTTPException(status_code=401, detail="Sign in is required")
        return User(email=session_user["email"].strip().lower(), name=session_user.get("name", ""))
    if os.getenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "").lower() == "true" and x_test_user:
        return User(email=x_test_user.strip().lower(), name="Test user")
    raise HTTPException(status_code=401, detail="Sign in is required")


def require_csrf(request: Request, user: User = Depends(current_user),
                 x_csrf_token: str = Header(default="")) -> User:
    if os.getenv("FASTACCOUNTS_ALLOW_TEST_AUTH", "").lower() == "true" and request.headers.get("x-test-user"):
        return user
    expected = request.session.get("csrf_token")
    if not expected or not x_csrf_token or not secrets.compare_digest(expected, x_csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token is missing or invalid")
    return user


def _require(organisation_id: str, user: User, roles: set[str]) -> None:
    OrganisationService().require(organisation_id, user.email, roles)


def _object_in_org(table: str, object_id: str, organisation_id: str) -> None:
    allowed = {"bills", "bank_transactions", "vat_returns", "fiscal_periods"}
    if table not in allowed or not get_database().one(
        f"SELECT id FROM {table} WHERE id=? AND organisation_id=?", (object_id, organisation_id)
    ):
        raise HTTPException(status_code=404, detail="Record not found in this organisation")


@api.get("/csrf")
def csrf(request: Request, user: User = Depends(current_user)):
    del user
    token = request.session.get("csrf_token") or secrets.token_urlsafe(32)
    request.session["csrf_token"] = token
    return {"csrf_token": token}


@api.get("/organisations")
def list_organisations(user: User = Depends(current_user)):
    return OrganisationService().for_user(user.email)


@api.get("/email-status")
def get_email_status(user: User = Depends(current_user)):
    del user
    return email_status()


@api.post("/organisations", status_code=201)
def create_organisation(payload: OrganisationIn, user: User = Depends(require_csrf)):
    return OrganisationService().create(**payload.model_dump(), owner_email=user.email)


@api.get("/organisations/{organisation_id}/accounts")
def list_accounts(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return get_database().rows("SELECT * FROM accounts WHERE organisation_id=? ORDER BY code", (organisation_id,))


@api.post("/organisations/{organisation_id}/invitations", status_code=201)
def create_invitation(organisation_id: str, payload: InvitationIn,
                      user: User = Depends(require_csrf)):
    _require(organisation_id, user, {"owner", "administrator"})
    invitation, token = GovernanceService().invite(
        organisation_id, email=payload.email, role=payload.role,
        valid_days=payload.valid_days, actor=user.email,
    )
    return {"invitation": invitation, "accept_token": token,
            "warning": "Deliver this one-time token over a trusted channel"}


@api.post("/invitations/accept")
def accept_invitation(payload: InvitationAcceptIn, user: User = Depends(require_csrf)):
    return GovernanceService().accept_invitation(payload.token, email=user.email)


@api.get("/organisations/{organisation_id}/tax-codes")
def list_tax_codes(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return get_database().rows("SELECT * FROM tax_codes WHERE organisation_id=? AND active=1 ORDER BY code", (organisation_id,))


@api.get("/organisations/{organisation_id}/contacts")
def list_contacts(organisation_id: str, include_inactive: bool = False,
                  user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    if include_inactive:
        return ListExportRepository(get_database()).contacts(organisation_id)
    return get_database().rows(
        "SELECT * FROM contacts WHERE organisation_id=? AND active<>0 ORDER BY name",
        (organisation_id,))


# --- Master data maintenance ------------------------------------------------

@api.get('/organisations/{organisation_id}/master-data/maintenance')
def master_data_maintenance(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, READ_ROLES)
    return MasterDataMaintenanceService().analyse(organisation_id)


@api.post('/organisations/{organisation_id}/master-data/contacts/{contact_id}/deactivate')
def deactivate_contact(organisation_id: str, contact_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    MasterDataMaintenanceService().deactivate_contact(organisation_id, contact_id, actor=user.email)
    return {'deactivated': True}


@api.post('/organisations/{organisation_id}/master-data/contacts/{contact_id}/reactivate')
def reactivate_contact(organisation_id: str, contact_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    MasterDataMaintenanceService().reactivate_contact(organisation_id, contact_id, actor=user.email)
    return {'reactivated': True}


@api.post('/organisations/{organisation_id}/master-data/contacts/{contact_id}/delete')
def delete_contact(organisation_id: str, contact_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    MasterDataMaintenanceService().delete_contact(organisation_id, contact_id, actor=user.email)
    return {'deleted': True}


@api.post('/organisations/{organisation_id}/master-data/items/{item_id}/deactivate')
def deactivate_item(organisation_id: str, item_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    MasterDataMaintenanceService().deactivate_item(organisation_id, item_id, actor=user.email)
    return {'deactivated': True}


@api.post('/organisations/{organisation_id}/master-data/items/{item_id}/delete')
def delete_item(organisation_id: str, item_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    MasterDataMaintenanceService().delete_item(organisation_id, item_id, actor=user.email)
    return {'deleted': True}


@api.get('/organisations/{organisation_id}/contacts/export.csv')
def export_contacts(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return Response(CsvExportService().export(organisation_id, 'contacts'), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="contacts.csv"'})


class MasterDataImportIn(BaseModel):
    kind: Literal['contacts', 'items']
    csv_content: str = Field(min_length=1, max_length=2_000_000)


@api.post('/organisations/{organisation_id}/imports', status_code=201)
def stage_master_data(organisation_id: str, payload: MasterDataImportIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return MasterDataImportService().stage(organisation_id, **payload.model_dump(), actor=user.email)


@api.get('/organisations/{organisation_id}/imports/{batch_id}')
def get_master_data_import(organisation_id: str, batch_id: str, limit: int = 100, offset: int = 0, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return MasterDataImportService().get(organisation_id, batch_id, limit=limit, offset=offset)


@api.post('/organisations/{organisation_id}/imports/{batch_id}/commit')
def commit_master_data_import(organisation_id: str, batch_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return MasterDataImportService().commit(organisation_id, batch_id, actor=user.email)


@api.post('/organisations/{organisation_id}/imports/{batch_id}/discard')
def discard_master_data_import(organisation_id: str, batch_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return MasterDataImportService().discard(organisation_id, batch_id, actor=user.email)


@api.post("/organisations/{organisation_id}/contacts", status_code=201)
def create_contact(organisation_id: str, payload: ContactIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return DocumentService().create_contact(organisation_id, **payload.model_dump())


@api.get('/organisations/{organisation_id}/purchase-schedules')
def list_purchase_schedules(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return jsonable_encoder(PeriodisationService().list(organisation_id), custom_encoder={Decimal: str})


@api.get('/organisations/{organisation_id}/purchase-schedules/{schedule_id}')
def get_purchase_schedule(organisation_id: str, schedule_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return jsonable_encoder(PeriodisationService().get(organisation_id, schedule_id), custom_encoder={Decimal: str})


@api.post('/organisations/{organisation_id}/purchase-schedules', status_code=201)
def create_purchase_schedule(organisation_id: str, payload: PurchaseScheduleIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return jsonable_encoder(PeriodisationService().create(organisation_id, actor=user.email, **payload.model_dump()), custom_encoder={Decimal: str})


@api.patch('/organisations/{organisation_id}/purchase-schedules/{schedule_id}')
def update_purchase_schedule(organisation_id: str, schedule_id: str, payload: PurchaseSchedulePatch, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return jsonable_encoder(PeriodisationService().update(organisation_id, schedule_id, actor=user.email, **payload.model_dump(exclude_unset=True)), custom_encoder={Decimal: str})


@api.post('/organisations/{organisation_id}/purchase-schedules/{schedule_id}/post')
def post_purchase_periods(organisation_id: str, schedule_id: str, payload: PurchasePeriodPostIn | None = None, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return jsonable_encoder(PeriodisationService().post_due(organisation_id, schedule_id, actor=user.email, **(payload.model_dump() if payload else {})), custom_encoder={Decimal: str})


@api.post('/organisations/{organisation_id}/purchase-schedules/{schedule_id}/cancel')
def cancel_purchase_schedule(organisation_id: str, schedule_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return jsonable_encoder(PeriodisationService().cancel(organisation_id, schedule_id, actor=user.email), custom_encoder={Decimal: str})


@api.get("/organisations/{organisation_id}/quotes")
def list_quotes(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return QuoteService().list(organisation_id)


@api.get('/organisations/{organisation_id}/quotes/export.csv')
def export_quotes(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return Response(CsvExportService().export(organisation_id, 'quotes'), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="quotes.csv"'})


@api.get("/organisations/{organisation_id}/quotes/{quote_id}")
def get_quote(organisation_id: str, quote_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return QuoteService().get(organisation_id, quote_id)


@api.post("/organisations/{organisation_id}/quotes", status_code=201)
def create_quote(organisation_id: str, payload: QuoteIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return QuoteService().create(organisation_id, actor=user.email, **payload.model_dump())


@api.patch("/organisations/{organisation_id}/quotes/{quote_id}")
def update_quote(organisation_id: str, quote_id: str, payload: QuotePatch, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return QuoteService().update(organisation_id, quote_id, actor=user.email, **payload.model_dump(exclude_unset=True))


@api.post("/organisations/{organisation_id}/quotes/{quote_id}/send")
def send_quote(organisation_id: str, quote_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return QuoteService().send(organisation_id, quote_id, actor=user.email)


@api.post("/organisations/{organisation_id}/quotes/{quote_id}/accept")
def accept_quote(organisation_id: str, quote_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return QuoteService().accept(organisation_id, quote_id, actor=user.email)


@api.post("/organisations/{organisation_id}/quotes/{quote_id}/decline")
def decline_quote(organisation_id: str, quote_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return QuoteService().decline(organisation_id, quote_id, actor=user.email)


@api.post("/organisations/{organisation_id}/quotes/{quote_id}/expire-status")
def expire_quote(organisation_id: str, quote_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return QuoteService().expire(organisation_id, quote_id, actor=user.email)


@api.post("/organisations/{organisation_id}/quotes/{quote_id}/convert")
def convert_quote(organisation_id: str, quote_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return QuoteService().convert(organisation_id, quote_id, actor=user.email)


def _invoice_list_filters(status: str | None = None, contact_id: str | None = None,
                          date_from: str | None = None, date_to: str | None = None,
                          currency: str | None = None, q: str | None = None):
    try:
        validate_list_dates(date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dict(status=status, contact_id=contact_id, date_from=date_from,
                date_to=date_to, currency=currency, q=q)


@api.get("/organisations/{organisation_id}/invoices")
def list_invoices(organisation_id: str, user: User = Depends(current_user),
                  filters: dict = Depends(_invoice_list_filters)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return InvoiceListService().list(organisation_id, "invoices", **filters)


@api.get("/organisations/{organisation_id}/invoices/export.{format_}")
@api.get("/organisations/{organisation_id}/bills/export.{format_}")
def invoice_list_export(organisation_id: str, format_: str, request: Request,
                        user: User = Depends(current_user),
                        filters: dict = Depends(_invoice_list_filters)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    if format_ not in {"csv", "xlsx"}:
        raise HTTPException(status_code=404, detail="Document export not found")
    kind = request.url.path.split("/")[-2]
    content = InvoiceListService().export(organisation_id, kind, format_, **filters)
    media_type = ("text/csv" if format_ == "csv" else
                  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{kind}.{format_}"'})


@api.get('/organisations/{organisation_id}/fx-revaluations')
def list_fx_revaluations(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return FxRevaluationService().list(organisation_id)


@api.post('/organisations/{organisation_id}/fx-revaluations', status_code=201)
def run_fx_revaluation(organisation_id: str, payload: FxRevaluationIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, {'owner', 'administrator'})
    return FxRevaluationService().run(organisation_id, **payload.model_dump(), actor=user.email)


@api.get('/organisations/{organisation_id}/exchange-rates')
def list_exchange_rates(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return ExchangeRateService().list(organisation_id)


@api.post('/organisations/{organisation_id}/exchange-rates', status_code=201)
def create_exchange_rate(organisation_id: str, payload: ExchangeRateIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, {'owner', 'administrator'})
    return ExchangeRateService().create(organisation_id, **payload.model_dump(), actor=user.email)


@api.delete('/organisations/{organisation_id}/exchange-rates/{rate_id}')
def delete_exchange_rate(organisation_id: str, rate_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, {'owner', 'administrator'})
    return ExchangeRateService().delete(organisation_id, rate_id, actor=user.email)


@api.get('/organisations/{organisation_id}/payment-methods')
def list_payment_methods(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return PaymentLinkService().list_configs(organisation_id)


@api.get('/organisations/{organisation_id}/reminder-rules')
def get_reminder_rules(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return ReminderRuleService().get(organisation_id)


@api.put('/organisations/{organisation_id}/reminder-rules')
def put_reminder_rules(organisation_id: str, payload: ReminderRuleIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, {'owner', 'administrator'})
    return ReminderRuleService().save(organisation_id, **payload.model_dump(), actor=user.email)


@api.get('/organisations/{organisation_id}/document-settings')
def get_document_settings(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return DocumentSettingsService().get(organisation_id)


@api.put('/organisations/{organisation_id}/document-settings')
def put_document_settings(organisation_id: str, payload: DocumentSettingsIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    return DocumentSettingsService().save(organisation_id, **payload.model_dump(), actor=user.email)


@api.post('/organisations/{organisation_id}/document-settings/logo')
async def upload_document_logo(organisation_id: str, file: UploadFile = File(...),
                               user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    content = await file.read(MAX_LOGO_BYTES + 1)
    return DocumentSettingsService().upload_logo(
        organisation_id, filename=file.filename or '', content_type=file.content_type,
        content=content, actor=user.email)


@api.delete('/organisations/{organisation_id}/document-settings/logo')
def delete_document_logo(organisation_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    return DocumentSettingsService().delete_logo(organisation_id, actor=user.email)


@api.get('/organisations/{organisation_id}/document-settings/logo')
def get_document_logo(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    attachment, content = DocumentSettingsService().logo(organisation_id)
    return Response(content, media_type=attachment['content_type'])


# --- AI copilot -------------------------------------------------------------

READ_ROLES = {'owner', 'administrator', 'accountant', 'approver', 'viewer'}


class CopilotMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=3)


class CopilotScanIn(BaseModel):
    attachment_id: str = Field(min_length=1)


class CopilotStageIn(BaseModel):
    kind: str = Field(min_length=1, max_length=20)
    csv_content: str = Field(min_length=1, max_length=2_000_000)
    message_id: str | None = None


class CopilotToggleIn(BaseModel):
    enabled: bool


@api.get('/organisations/{organisation_id}/copilot/status')
def copilot_status(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, READ_ROLES)
    return CopilotService().status(organisation_id, user.email)


@api.get('/organisations/{organisation_id}/copilot/messages')
def copilot_messages(organisation_id: str, limit: int = 50,
                     user: User = Depends(current_user)):
    _require(organisation_id, user, READ_ROLES)
    return CopilotService().messages(organisation_id, user.email, limit=min(max(limit, 1), 100))


@api.post('/organisations/{organisation_id}/copilot/messages', status_code=201)
def copilot_send(organisation_id: str, payload: CopilotMessageIn,
                 user: User = Depends(require_csrf)):
    _require(organisation_id, user, READ_ROLES)
    return CopilotService().send(organisation_id, user.email, payload.content,
                                 attachment_ids=payload.attachment_ids)


@api.post('/organisations/{organisation_id}/copilot/scan', status_code=201)
def copilot_scan(organisation_id: str, payload: CopilotScanIn,
                 user: User = Depends(require_csrf)):
    _require(organisation_id, user, READ_ROLES)
    return CopilotService().scan(organisation_id, user.email, payload.attachment_id)


@api.post('/organisations/{organisation_id}/copilot/stage', status_code=201)
def copilot_stage(organisation_id: str, payload: CopilotStageIn,
                  user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    return CopilotService().stage(organisation_id, user.email, payload.kind,
                                  payload.csv_content, message_id=payload.message_id)


@api.get('/organisations/{organisation_id}/copilot/usage')
def copilot_usage(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    return CopilotService().usage(organisation_id)


@api.get('/organisations/{organisation_id}/copilot/documents')
def copilot_documents(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, READ_ROLES)
    return CopilotService().documents(organisation_id)


@api.put('/organisations/{organisation_id}/copilot/settings')
def copilot_settings(organisation_id: str, payload: CopilotToggleIn,
                     user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    CopilotService().set_enabled(organisation_id, payload.enabled, actor=user.email)
    return CopilotService().status(organisation_id, user.email)


# --- Fiscal period close and reopen -----------------------------------------

@api.get("/organisations/{organisation_id}/periods")
def list_fiscal_periods(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, READ_ROLES)
    return LedgerService().list_periods(organisation_id)


class PeriodActionIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@api.put("/organisations/{organisation_id}/periods/{period_id}/close")
def close_fiscal_period(organisation_id: str, period_id: str, payload: PeriodActionIn,
                        user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    _object_in_org("fiscal_periods", period_id, organisation_id)
    LedgerService().lock_period(period_id, actor=user.email, reason=payload.reason)
    return LedgerService().list_periods(organisation_id)


@api.put("/organisations/{organisation_id}/periods/{period_id}/reopen")
def reopen_fiscal_period(organisation_id: str, period_id: str, payload: PeriodActionIn,
                         user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    _object_in_org("fiscal_periods", period_id, organisation_id)
    LedgerService().unlock_period(period_id, actor=user.email, reason=payload.reason)
    return LedgerService().list_periods(organisation_id)


@api.get('/organisations/{organisation_id}/objects')
def list_objects(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return ObjectService().list(organisation_id)


@api.get('/organisations/{organisation_id}/objects/export.csv')
def export_objects(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return Response(CsvExportService().export(organisation_id, 'objects'), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="objects.csv"'})


@api.get('/organisations/{organisation_id}/objects/{object_id}')
def get_object(organisation_id: str, object_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return ObjectService().get(organisation_id, object_id)


@api.post('/organisations/{organisation_id}/objects', status_code=201)
def create_object(organisation_id: str, payload: ObjectIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    return ObjectService().create(organisation_id, **payload.model_dump(), actor=user.email)


@api.patch('/organisations/{organisation_id}/objects/{object_id}')
def update_object(organisation_id: str, object_id: str, payload: ObjectPatch, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    return ObjectService().update(organisation_id, object_id, **payload.model_dump(exclude_unset=True), actor=user.email)


@api.delete('/organisations/{organisation_id}/objects/{object_id}')
def delete_object(organisation_id: str, object_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    return ObjectService().delete(organisation_id, object_id, actor=user.email)


@api.post('/organisations/{organisation_id}/payment-methods', status_code=201)
def create_payment_method(organisation_id: str, payload: PaymentMethodIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    return PaymentLinkService().create_config(organisation_id, **payload.model_dump(), actor=user.email)


@api.patch('/organisations/{organisation_id}/payment-methods/{method_id}')
def update_payment_method(organisation_id: str, method_id: str, payload: PaymentMethodPatch, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {'owner', 'administrator'})
    return PaymentLinkService().update_config(organisation_id, method_id, **payload.model_dump(exclude_unset=True), actor=user.email)


@api.get('/organisations/{organisation_id}/invoices/{invoice_id}/payment-links')
def get_invoice_payment_links(organisation_id: str, invoice_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return PaymentLinkService().invoice_links(organisation_id, invoice_id)


@api.post("/organisations/{organisation_id}/invoices", status_code=201)
def create_invoice(organisation_id: str, payload: InvoiceIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    data = payload.model_dump()
    data["lines"] = [line.model_dump() for line in payload.lines]
    return DocumentService().create_invoice(organisation_id, actor=user.email, **data)


@api.post("/organisations/{organisation_id}/invoices/{invoice_id}/issue")
def issue_invoice(organisation_id: str, invoice_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    invoice = DocumentService().invoice(invoice_id, organisation_id)
    del invoice
    return DocumentService().issue_invoice(invoice_id, actor=user.email)


@api.post('/organisations/{organisation_id}/invoices/send-bulk')
def send_bulk_invoices(organisation_id: str, payload: BulkSendIn,
                       user: User = Depends(require_csrf),
                       idempotency_key: str | None = Header(default=None, min_length=1, max_length=180)):
    _require(organisation_id, user, WRITE_ROLES)
    return BulkSendingService().send(organisation_id, payload.invoice_ids,
                                     actor=user.email, idempotency_key=idempotency_key)


@api.get("/organisations/{organisation_id}/invoices/{invoice_id}.pdf")
def invoice_pdf(organisation_id: str, invoice_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    document = DocumentService().invoice(invoice_id, organisation_id)
    return Response(DocumentService().invoice_pdf(invoice_id), media_type="application/pdf",
                    headers={"Content-Disposition": f"inline; filename={document.get('number') or 'draft-invoice'}.pdf"})


@api.get("/organisations/{organisation_id}/invoices/{invoice_id}.xml")
def invoice_xml(organisation_id: str, invoice_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    DocumentService().invoice(invoice_id, organisation_id)
    return Response(DocumentService().invoice_xml(invoice_id), media_type="application/xml")


@api.get('/organisations/{organisation_id}/invoices/{invoice_id}')
def get_invoice(organisation_id: str, invoice_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return PaymentLinkService().invoice_payload(organisation_id, invoice_id)


@api.post("/organisations/{organisation_id}/invoice-schedules", status_code=201)
def create_invoice_schedule(organisation_id: str, payload: InvoiceScheduleIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return AutomationService().create_schedule(organisation_id, actor=user.email, **payload.model_dump())


@api.get("/organisations/{organisation_id}/invoice-schedules")
def list_invoice_schedules(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return AutomationService().list_schedules(organisation_id)


@api.get("/organisations/{organisation_id}/invoice-schedules/{schedule_id}")
def get_invoice_schedule(organisation_id: str, schedule_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return AutomationService().schedule(schedule_id, organisation_id)


@api.patch("/organisations/{organisation_id}/invoice-schedules/{schedule_id}")
def update_invoice_schedule(organisation_id: str, schedule_id: str, payload: InvoiceSchedulePatch,
                            user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return AutomationService().update_schedule(schedule_id, organisation_id, actor=user.email,
                                               **payload.model_dump(exclude_unset=True))


@api.post("/organisations/{organisation_id}/invoice-schedules/{schedule_id}/run-now")
def run_invoice_schedule(organisation_id: str, schedule_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return {"runs": [AutomationService().run_now(schedule_id, organisation_id, actor=user.email)]}


@api.get("/organisations/{organisation_id}/reminders/due")
def reminders_due(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return {"email_connected": email_configured(), "items": AutomationService().reminders_due(organisation_id)}


@api.post("/organisations/{organisation_id}/invoices/{invoice_id}/reminders/opt-out")
def reminders_opt_out(organisation_id: str, invoice_id: str, payload: ReminderOptOutIn,
                      user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return AutomationService().set_reminders_opt_out(invoice_id, organisation_id, actor=user.email,
                                                     **payload.model_dump())


@api.post("/organisations/{organisation_id}/invoices/{invoice_id}/reminders/{stage}/send")
def send_reminder(organisation_id: str, invoice_id: str, stage: int, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return AutomationService().send_reminder(invoice_id, organisation_id, stage=stage, actor=user.email, client=None)


@api.get("/organisations/{organisation_id}/bills")
def list_bills(organisation_id: str, user: User = Depends(current_user),
               filters: dict = Depends(_invoice_list_filters)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return InvoiceListService().list(organisation_id, "bills", **filters)


@api.post("/organisations/{organisation_id}/bills", status_code=201)
def create_bill(organisation_id: str, payload: BillIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    data = payload.model_dump()
    data["lines"] = [line.model_dump() for line in payload.lines]
    return DocumentService().create_bill(organisation_id, actor=user.email, **data)


@api.post("/organisations/{organisation_id}/e-invoices/import", status_code=201)
async def import_einvoice(organisation_id: str, file: UploadFile = File(...),
                          user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    content = await file.read(int(os.getenv("MAX_ATTACHMENT_BYTES", "10485760")) + 1)
    try:
        return DocumentService().import_einvoice(
            organisation_id, content=content, filename=file.filename or "e-invoice.xml", actor=user.email)
    except EInvoiceAlreadyImported as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@api.post("/organisations/{organisation_id}/bills/{bill_id}/review")
def review_bill(organisation_id: str, bill_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    _object_in_org("bills", bill_id, organisation_id)
    return DocumentService().submit_bill_for_review(bill_id, actor=user.email)


@api.post("/organisations/{organisation_id}/bills/{bill_id}/approve")
def approve_bill(organisation_id: str, bill_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, APPROVE_ROLES)
    _object_in_org("bills", bill_id, organisation_id)
    return DocumentService().approve_bill(bill_id, actor=user.email)


@api.get("/organisations/{organisation_id}/asset-groups")
def asset_groups(organisation_id: str, locale: Literal["en", "et", "lt", "lv"] = "en",
                 user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return jsonable_encoder(FixedAssetService().groups(organisation_id, locale=locale), custom_encoder={Decimal: str})


@api.post("/organisations/{organisation_id}/asset-groups", status_code=201)
def create_asset_group(organisation_id: str, payload: AssetGroupIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return jsonable_encoder(FixedAssetService().create_group(organisation_id, actor=user.email,
                            **payload.model_dump()), custom_encoder={Decimal: str})


@api.get("/organisations/{organisation_id}/fixed-assets")
def fixed_asset_register(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return jsonable_encoder(FixedAssetService().register(organisation_id), custom_encoder={Decimal: str})


@api.post("/organisations/{organisation_id}/fixed-assets", status_code=201)
def create_fixed_asset(organisation_id: str, payload: FixedAssetIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return jsonable_encoder(FixedAssetService().create(organisation_id, actor=user.email,
                            **payload.model_dump()), custom_encoder={Decimal: str})


@api.get("/organisations/{organisation_id}/fixed-assets/schedule")
def depreciation_schedule(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return jsonable_encoder(FixedAssetService().schedule(organisation_id), custom_encoder={Decimal: str})


@api.get("/organisations/{organisation_id}/fixed-assets/runs")
def depreciation_runs(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return jsonable_encoder(FixedAssetService().runs(organisation_id), custom_encoder={Decimal: str})


@api.post("/organisations/{organisation_id}/fixed-assets/runs")
def run_depreciation(organisation_id: str, payload: DepreciationRunIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return jsonable_encoder(FixedAssetService().run(organisation_id, actor=user.email,
                            **payload.model_dump()), custom_encoder={Decimal: str})


@api.post("/organisations/{organisation_id}/fixed-assets/{asset_id}/dispose")
def dispose_fixed_asset(organisation_id: str, asset_id: str, payload: AssetDisposalIn,
                        user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return jsonable_encoder(FixedAssetService().dispose(organisation_id, asset_id, actor=user.email,
                            **payload.model_dump()), custom_encoder={Decimal: str})


@api.get("/organisations/{organisation_id}/prepayments")
def list_prepayments(organisation_id: str, side: Literal["customer", "supplier"] | None = None,
                    contact_id: str | None = None, outstanding_only: bool = False,
                    user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return jsonable_encoder(PrepaymentService().list(organisation_id, side=side, contact_id=contact_id,
                            outstanding_only=outstanding_only), custom_encoder={Decimal: str})


@api.post("/organisations/{organisation_id}/prepayments", status_code=201)
def create_prepayment(organisation_id: str, payload: PrepaymentIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return jsonable_encoder(PrepaymentService().create(organisation_id, actor=user.email, **payload.model_dump()),
                            custom_encoder={Decimal: str})


@api.get("/organisations/{organisation_id}/prepayments/{prepayment_id}")
def get_prepayment(organisation_id: str, prepayment_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return jsonable_encoder(PrepaymentService().get(organisation_id, prepayment_id), custom_encoder={Decimal: str})


@api.post("/organisations/{organisation_id}/prepayments/{prepayment_id}/allocate")
def allocate_prepayment(organisation_id: str, prepayment_id: str, payload: PrepaymentAllocationIn,
                       user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return jsonable_encoder(PrepaymentService().allocate(organisation_id, prepayment_id, actor=user.email,
                            **payload.model_dump()), custom_encoder={Decimal: str})


@api.post("/organisations/{organisation_id}/prepayments/{prepayment_id}/refund")
def refund_prepayment(organisation_id: str, prepayment_id: str, payload: PrepaymentRefundIn,
                     user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return jsonable_encoder(PrepaymentService().refund(organisation_id, prepayment_id, actor=user.email,
                            **payload.model_dump()), custom_encoder={Decimal: str})


@api.get("/organisations/{organisation_id}/contacts/{contact_id}/prepayments/outstanding")
def contact_prepayments_outstanding(organisation_id: str, contact_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return jsonable_encoder(PrepaymentService().outstanding(organisation_id, contact_id), custom_encoder={Decimal: str})


@api.get("/organisations/{organisation_id}/payment-orders/candidates")
def payment_order_candidates(organisation_id: str, due_before: str | None = None,
                             user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return PaymentOrderService().candidates(organisation_id, due_before=due_before)


@api.post("/organisations/{organisation_id}/payment-orders", status_code=201)
def create_payment_order(organisation_id: str, payload: PaymentOrderIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return PaymentOrderService().create(organisation_id, actor=user.email, **payload.model_dump())


@api.get("/organisations/{organisation_id}/payment-orders")
def list_payment_orders(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return PaymentOrderService().list(organisation_id)


@api.get("/organisations/{organisation_id}/payment-orders/{order_id}.xml")
def download_payment_order(organisation_id: str, order_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    from urllib.parse import quote
    return Response(PaymentOrderService().xml(organisation_id, order_id), media_type="application/xml",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote('payment-order-' + order_id + '.xml', safe='')}"})


@api.post("/organisations/{organisation_id}/attachments/{owner_type}/{owner_id}", status_code=201)
async def attach_evidence(organisation_id: str, owner_type: str, owner_id: str,
                          file: UploadFile = File(...), user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    content = await file.read(int(os.getenv("MAX_ATTACHMENT_BYTES", "10485760")) + 1)
    result = DocumentService().attach_evidence(
        organisation_id, owner_type=owner_type, owner_id=owner_id, filename=file.filename or "attachment",
        content_type=file.content_type or "application/octet-stream", content=content, actor=user.email)
    return {key: value for key, value in result.items() if key != "storage_path"}


@api.get("/organisations/{organisation_id}/attachments")
def list_attachments(organisation_id: str, owner_type: str, owner_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return DocumentService().attachments(organisation_id, owner_type=owner_type, owner_id=owner_id)


@api.get("/organisations/{organisation_id}/attachments/{attachment_id}/download")
def download_attachment(organisation_id: str, attachment_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    from urllib.parse import quote
    attachment, content = DocumentService().evidence_download(organisation_id, attachment_id)
    return Response(content, media_type="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(attachment['filename'], safe='')}",
        "X-Content-Type-Options": "nosniff"})


@api.get("/organisations/{organisation_id}/bank-accounts")
def bank_accounts(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return get_database().rows("SELECT * FROM bank_accounts WHERE organisation_id=? ORDER BY name", (organisation_id,))


@api.post("/organisations/{organisation_id}/bank-accounts", status_code=201)
def create_bank_account(organisation_id: str, payload: BankAccountIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return DocumentService().create_bank_account(organisation_id, **payload.model_dump())


@api.post("/organisations/{organisation_id}/bank-accounts/{bank_account_id}/imports/{file_format}")
async def import_bank(organisation_id: str, bank_account_id: str,
                      file_format: Literal["csv", "camt053"], file: UploadFile = File(...),
                      user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    content = await file.read()
    service = BankingService()
    if file_format == "csv":
        return service.import_csv(organisation_id, bank_account_id, content, actor=user.email)
    return service.import_camt053(organisation_id, bank_account_id, content, actor=user.email)


@api.get("/organisations/{organisation_id}/bank-transactions")
def bank_transactions(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return ListExportRepository(get_database()).bank_transactions(organisation_id)


@api.get('/organisations/{organisation_id}/bank-transactions/export.csv')
def export_bank_transactions(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant', 'approver', 'viewer'})
    return Response(CsvExportService().export(organisation_id, 'bank-transactions'), media_type='text/csv',
                    headers={'Content-Disposition': 'attachment; filename="bank-transactions.csv"'})


@api.post("/organisations/{organisation_id}/bank-transactions/{transaction_id}/suggest")
def suggest_matches(organisation_id: str, transaction_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    _object_in_org("bank_transactions", transaction_id, organisation_id)
    return BankingService().suggest(transaction_id)


@api.post("/organisations/{organisation_id}/bank-transactions/{transaction_id}/reconcile")
def reconcile(organisation_id: str, transaction_id: str, payload: ReconcileIn,
              user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    _object_in_org("bank_transactions", transaction_id, organisation_id)
    return BankingService().reconcile_to_document(transaction_id, actor=user.email, **payload.model_dump())


@api.post("/organisations/{organisation_id}/bank-transactions/{transaction_id}/reconcile-split")
def reconcile_split(organisation_id: str, transaction_id: str, payload: SplitReconcileIn,
                    user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    _object_in_org("bank_transactions", transaction_id, organisation_id)
    return BankingService().reconcile_split(
        transaction_id, actor=user.email,
        allocations=[item.model_dump() for item in payload.allocations],
    )


@api.post("/organisations/{organisation_id}/tax/prepare")
def prepare_tax(organisation_id: str, payload: TaxPrepareIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return TaxService().prepare(organisation_id, **payload.model_dump())


@api.post("/organisations/{organisation_id}/tax/estonia/vd")
def prepare_estonian_vd(organisation_id: str, payload: TaxPrepareIn,
                        user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return TaxService().prepare_estonian_vd(
        organisation_id, period_start=payload.period_start, period_end=payload.period_end
    )


@api.post("/organisations/{organisation_id}/tax/{return_id}/review")
def review_tax(organisation_id: str, return_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, {"owner", "administrator", "accountant"})
    _object_in_org("vat_returns", return_id, organisation_id)
    return TaxService().review(return_id, actor=user.email)


@api.get("/organisations/{organisation_id}/tax/{return_id}/export.csv")
def export_tax(organisation_id: str, return_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant"})
    _object_in_org("vat_returns", return_id, organisation_id)
    return Response(TaxService().export_csv(return_id, actor=user.email), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=vat-{return_id}.csv"})


class TaxReplacementIn(BaseModel):
    from_code_id: str = Field(min_length=1)
    to_code_id: str = Field(min_length=1)


@api.post("/organisations/{organisation_id}/tax/replacement/preview")
def tax_replacement_preview(organisation_id: str, payload: TaxReplacementIn,
                            user: User = Depends(require_csrf)):
    _require(organisation_id, user, APPROVE_ROLES)
    return TaxReplacementService().preview(organisation_id, payload.from_code_id,
                                           payload.to_code_id)


@api.post("/organisations/{organisation_id}/tax/replacement")
def tax_replacement_apply(organisation_id: str, payload: TaxReplacementIn,
                          user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES & {"owner", "administrator"})
    return TaxReplacementService().apply(organisation_id, payload.from_code_id,
                                         payload.to_code_id, actor=user.email)


@api.get('/organisations/{organisation_id}/reports/{tab}.csv')
def export_report(organisation_id: str, tab: str, start: str | None = None, end: str | None = None,
                  as_at: str | None = None, date_from: str | None = None, date_to: str | None = None,
                  object_id: str | None = None, user: User = Depends(current_user)):
    roles = {'owner', 'administrator', 'accountant', 'viewer'}
    if tab in {'trial-balance', 'profit-and-loss', 'balance-sheet', 'cash-flow'}:
        roles.add('approver')
    _require(organisation_id, user, roles)
    content = CsvExportService().report(organisation_id, tab, start=start, end=end, as_at=as_at,
                                       date_from=date_from, date_to=date_to, object_id=object_id)
    return Response(content, media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="{tab}.csv"'})


@api.get("/organisations/{organisation_id}/reports/trial-balance")
def trial_balance(organisation_id: str, start: str, end: str, user: User = Depends(current_user), object_id: str | None = None):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return LedgerService().trial_balance(organisation_id, start=start, end=end, object_id=object_id)


@api.get("/organisations/{organisation_id}/reports/profit-and-loss")
def profit_loss(organisation_id: str, start: str, end: str, user: User = Depends(current_user),
                compare: str = "none", object_id: str | None = None):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return LedgerService().profit_and_loss(organisation_id, start=start, end=end, compare=compare, object_id=object_id)


@api.get("/organisations/{organisation_id}/reports/balance-sheet")
def balance_sheet(organisation_id: str, as_at: str, user: User = Depends(current_user),
                  compare: str = "none", start: str | None = None):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return LedgerService().balance_sheet(organisation_id, as_at=as_at, compare=compare, start=start)


@api.get("/organisations/{organisation_id}/reports/cash-flow")
def cash_flow(organisation_id: str, date_from: str, date_to: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return CashFlowService().statement(organisation_id, date_from=date_from, date_to=date_to)


@api.get("/organisations/{organisation_id}/reports/general-ledger")
def general_ledger(organisation_id: str, start: str, end: str, user: User = Depends(current_user), object_id: str | None = None):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "viewer"})
    return LedgerService().general_ledger(organisation_id, start=start, end=end, object_id=object_id)


def _iso_date_bound(value: str | None, default: str) -> str:
    if value is None:
        return default
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Report dates must use YYYY-MM-DD format") from exc
    if parsed.isoformat() != value:
        raise ValueError("Report dates must use YYYY-MM-DD format")
    return value


def _report_workbook(organisation_id: str, book: str, date_from: str | None,
                     date_to: str | None, filters: dict | None = None) -> bytes:
    if book not in {"general_ledger", "invoices", "employees", "vat_returns"}:
        raise KeyError("Report workbook not found")
    database = get_database()
    organisation = database.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
    if not organisation:
        raise KeyError("Organisation not found")
    if book == "general_ledger":
        start = _iso_date_bound(date_from, "0001-01-01")
        end = _iso_date_bound(date_to, "9999-12-31")
        if start > end:
            raise ValueError("Report date_from cannot be after date_to")
        return general_ledger_workbook(
            organisation, LedgerService(database).general_ledger(organisation_id, start=start, end=end)
        )
    if book == "invoices":
        rows = InvoiceListService(database).list(
            organisation_id, "invoices", date_from=date_from, date_to=date_to, **(filters or {}))
        return invoices_workbook(organisation, rows)
    if book == "employees":
        return employees_workbook(organisation, PayrollService(database).employees(organisation_id))
    rows = database.rows(
        "SELECT * FROM vat_returns WHERE organisation_id=? ORDER BY period_end DESC,created_at DESC",
        (organisation_id,),
    )
    return vat_returns_workbook(organisation, rows)


@api.get("/organisations/{organisation_id}/reports/{book}.xlsx")
def report_workbook(organisation_id: str, book: str, date_from: str | None = None,
                    date_to: str | None = None, user: User = Depends(current_user),
                    status: str | None = None, contact_id: str | None = None,
                    currency: str | None = None, q: str | None = None):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    content = _report_workbook(organisation_id, book, date_from, date_to,
                               dict(status=status, contact_id=contact_id, currency=currency, q=q))
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{book}.xlsx"'},
    )


@api.get("/organisations/{organisation_id}/reports/receivables-aging")
def receivables_aging(organisation_id: str, as_at: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "viewer"})
    return LedgerService().receivables_aging(organisation_id, as_at=as_at)


@api.get("/organisations/{organisation_id}/contacts/{contact_id}/statement")
def contact_statement(organisation_id: str, contact_id: str, date_from: str, date_to: str,
                      side: str = "customer", eur_rate: str | None = None,
                      user: User = Depends(current_user)):
    from decimal import Decimal
    from fastapi.encoders import jsonable_encoder
    _require(organisation_id, user, {"owner", "administrator", "accountant", "viewer"})
    statement = StatementService().statement(organisation_id, contact_id, date_from=date_from,
                                             date_to=date_to, side=side, eur_rate=eur_rate)
    return JSONResponse(jsonable_encoder(statement, custom_encoder={Decimal: str}))


@api.get("/organisations/{organisation_id}/contacts/{contact_id}/statement.pdf")
def contact_statement_pdf(organisation_id: str, contact_id: str, date_from: str, date_to: str,
                          side: str = "customer", eur_rate: str | None = None,
                          user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "viewer"})
    service = StatementService()
    statement = service.statement(organisation_id, contact_id, date_from=date_from,
                                  date_to=date_to, side=side, eur_rate=eur_rate)
    return Response(service.pdf(statement), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{service.filename(statement)}"'})


@api.get("/organisations/{organisation_id}/reports/payables-aging")
def payables_aging(organisation_id: str, as_at: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "viewer"})
    return LedgerService().payables_aging(organisation_id, as_at=as_at)


@api.get("/organisations/{organisation_id}/reports/cash-summary")
def cash_summary(organisation_id: str, start: str, end: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "viewer"})
    return LedgerService().cash_summary(organisation_id, start=start, end=end)


@api.post("/organisations/{organisation_id}/journals", status_code=201)
def create_journal(organisation_id: str, payload: JournalIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, {"owner", "administrator", "accountant"})
    lines = [PostingLine(**line.model_dump()) for line in payload.lines]
    return LedgerService().post(
        organisation_id=organisation_id, voucher_type="manual_journal",
        voucher_id=payload.idempotency_key, voucher_code=payload.voucher_code,
        posting_date=payload.posting_date, lines=lines, actor=user.email,
        currency=payload.currency,
    )


@api.get("/organisations/{organisation_id}/opening-balance")
def opening_balance_snapshot(organisation_id: str, opening_date: str,
                             user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {"viewer"})
    return jsonable_encoder(OpeningBalanceService().snapshot(organisation_id, opening_date=opening_date),
                            custom_encoder={Decimal: str})


@api.post("/organisations/{organisation_id}/opening-balance", status_code=201)
def post_opening_balance(organisation_id: str, payload: OpeningBalanceIn,
                         user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return OpeningBalanceService().post(organisation_id, actor=user.email, **payload.model_dump())


@api.get("/organisations/{organisation_id}/opening-balance/open-items/preview")
def opening_items_preview(organisation_id: str, csv_content: str,
                          user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {"viewer"})
    return jsonable_encoder(parse_open_items_csv(csv_content), custom_encoder={Decimal: str})


@api.post("/organisations/{organisation_id}/opening-balance/open-items/preview")
def opening_items_file_preview(organisation_id: str, payload: OpeningCSVIn,
                               user: User = Depends(require_csrf)):
    _require(organisation_id, user, APPROVE_ROLES | {"viewer"})
    return jsonable_encoder(parse_open_items_csv(payload.csv_content), custom_encoder={Decimal: str})


@api.post("/organisations/{organisation_id}/opening-balance/open-items", status_code=201)
def post_opening_items(organisation_id: str, payload: OpeningItemsIn,
                       user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    if (payload.csv_content is None) == (payload.rows is None):
        raise ValueError("Supply either CSV content or parsed rows")
    return OpeningBalanceService().post_open_items(organisation_id, posting_date=payload.posting_date,
        actor=user.email, rows=payload.csv_content if payload.csv_content is not None else payload.rows)


@api.get("/integrations")
def integration_catalogue(user: User = Depends(current_user)):
    del user
    return [{**item.__dict__, **provider_metadata(item.key)} for item in integrations.CATALOGUE]


@api.get("/organisations/{organisation_id}/integrations")
def organisation_integrations(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {'viewer'})
    return IntegrationService().connections(organisation_id)


class BankLinkIn(BaseModel):
    institution_id: str
    redirect_url: str


class BankFeedAccountIn(BaseModel):
    gocardless_account_id: str


class BankFeedMappingIn(BankFeedAccountIn):
    bank_account_id: str


@api.post("/organisations/{organisation_id}/integrations/open_banking/link")
def open_banking_link(organisation_id: str, payload: BankLinkIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return OpenBankingService().start_link(organisation_id, actor=user.email, **payload.model_dump())


@api.post("/organisations/{organisation_id}/integrations/open_banking/complete-link")
def open_banking_complete(organisation_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return OpenBankingService().complete_link(organisation_id, actor=user.email)


@api.get("/organisations/{organisation_id}/integrations/open_banking/institutions")
def open_banking_institutions(organisation_id: str, country: str, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {"viewer"})
    return OpenBankingService().institutions(country, organisation_id=organisation_id)


@api.get("/organisations/{organisation_id}/integrations/open_banking/accounts")
def open_banking_accounts(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {"viewer"})
    return OpenBankingService().accounts(organisation_id)


@api.post("/organisations/{organisation_id}/integrations/open_banking/link-account")
def open_banking_mapping(organisation_id: str, payload: BankFeedMappingIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return OpenBankingService().link_account(organisation_id, actor=user.email, **payload.model_dump())


@api.get("/organisations/{organisation_id}/integrations/open_banking/pull-status")
def open_banking_pull_status(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {"viewer"})
    return OpenBankingService().pull_status(organisation_id)


@api.post("/organisations/{organisation_id}/integrations/open_banking/pull")
def open_banking_pull(organisation_id: str, payload: BankFeedAccountIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return OpenBankingService().pull(organisation_id, actor=user.email, **payload.model_dump())


@api.post("/organisations/{organisation_id}/integrations/{provider}")
def configure_integration(organisation_id: str, provider: str, payload: IntegrationIn,
                          user: User = Depends(require_csrf)):
    _require(organisation_id, user, {"owner", "administrator"})
    service = IntegrationService()
    connection = service.configure(
        organisation_id, provider, actor=user.email, **payload.model_dump()
    )
    return service.public_connection(connection)


@api.post(
    "/organisations/{organisation_id}/integrations/{provider}/test",
    response_model=ConnectorResultOut,
)
def test_integration(organisation_id: str, provider: str, payload: IntegrationTestIn,
                     user: User = Depends(require_csrf)):
    _require(organisation_id, user, {"owner", "administrator"})
    return IntegrationService().test_connection(
        organisation_id, provider, actor=user.email, **payload.model_dump()
    )


@api.post("/organisations/{organisation_id}/integrations/{provider}/disconnect")
def disconnect_integration(organisation_id: str, provider: str,
                           user: User = Depends(require_csrf)):
    _require(organisation_id, user, {"owner", "administrator"})
    return IntegrationService().disconnect(organisation_id, provider, actor=user.email)


@api.get("/organisations/{organisation_id}/integrations/{provider}/account-mappings")
def list_account_mappings(
    organisation_id: str, provider: str, user: User = Depends(current_user)
):
    _require(organisation_id, user, {"owner", "administrator"})
    return AccountMappingService().list(organisation_id, provider)


@api.post("/organisations/{organisation_id}/integrations/{provider}/account-mappings", status_code=201)
def create_account_mapping(
    organisation_id: str, provider: str, payload: AccountMappingIn,
    user: User = Depends(require_csrf),
):
    _require(organisation_id, user, {"owner", "administrator"})
    return AccountMappingService().create(
        organisation_id, provider, actor=user.email, **payload.model_dump()
    )


@api.put("/organisations/{organisation_id}/integrations/{provider}/account-mappings/{mapping_id}")
def update_account_mapping(
    organisation_id: str, provider: str, mapping_id: str,
    payload: AccountMappingUpdateIn, user: User = Depends(require_csrf),
):
    _require(organisation_id, user, {"owner", "administrator"})
    return AccountMappingService().update(
        organisation_id, provider, mapping_id, actor=user.email, **payload.model_dump()
    )


@api.get("/organisations/{organisation_id}/integrations/{provider}/gl-reconciliation")
def gl_reconciliation(
    organisation_id: str, provider: str, date_from: str | None = None,
    date_to: str | None = None, user: User = Depends(current_user),
):
    _require(
        organisation_id, user,
        {"owner", "administrator", "accountant", "approver", "viewer"},
    )
    return {
        "rows": AccountMappingService().reconcile(
            organisation_id, provider, date_from=date_from, date_to=date_to
        )
    }


@api.post("/organisations/{organisation_id}/integrations/{provider}/sync")
def run_integration_sync(
    organisation_id: str,
    provider: str,
    payload: IntegrationSyncIn,
    user: User = Depends(require_csrf),
):
    _require(organisation_id, user, {"owner", "administrator"})
    return ImportService().run_sync(
        organisation_id, provider, payload.object_type, actor=user.email
    )


@api.post("/organisations/{organisation_id}/integrations/file_import/import")
def import_employee_file(
    organisation_id: str,
    payload: FileImportIn,
    user: User = Depends(require_csrf),
):
    _require(organisation_id, user, {"owner", "administrator"})
    return ImportService().run_sync(
        organisation_id,
        "file_import",
        payload.object_type,
        actor=user.email,
        credentials={"csv_content": payload.csv_content},
        config=payload.config,
    )


@api.get("/organisations/{organisation_id}/integrations/{provider}/sync/{sync_run_id}")
def integration_sync_review(
    organisation_id: str,
    provider: str,
    sync_run_id: str,
    user: User = Depends(current_user),
):
    _require(organisation_id, user, {"owner", "administrator"})
    result = ImportService().get_staged(organisation_id, sync_run_id=sync_run_id)
    if result["summary"]["provider"] != provider.strip().lower():
        raise KeyError("Sync run not found")
    return result


@api.post("/organisations/{organisation_id}/integrations/{provider}/sync/{sync_run_id}/apply")
def apply_integration_sync(
    organisation_id: str,
    provider: str,
    sync_run_id: str,
    payload: IntegrationApplyIn,
    user: User = Depends(require_csrf),
):
    _require(organisation_id, user, {"owner", "administrator"})
    return ImportService().apply_staged(
        organisation_id,
        provider,
        sync_run_id,
        payload.decisions,
        actor=user.email,
    )


@api.get("/organisations/{organisation_id}/integrations/{provider}/syncs")
def integration_syncs(
    organisation_id: str,
    provider: str,
    user: User = Depends(current_user),
):
    _require(organisation_id, user, {"owner", "administrator"})
    return ImportService().syncs(organisation_id, provider)

# Accounting-bureau payroll API. Monetary values are returned as decimal strings.


@api.post('/organisations/{organisation_id}/integrations/{provider}/push/journals/{batch_id}/prepare')
def prepare_journal_push(organisation_id: str, provider: str, batch_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, APPROVE_ROLES)
    return PushService().prepare(organisation_id, provider, 'journals', batch_id, user.email)


@api.post('/organisations/{organisation_id}/integrations/{provider}/push/pay-runs/{run_id}/prepare')
def prepare_payroll_push(organisation_id: str, provider: str, run_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, APPROVE_ROLES)
    return PushService().prepare(organisation_id, provider, 'pay_runs', run_id, user.email)


@api.get('/organisations/{organisation_id}/integrations/{provider}/pushes')
def provider_pushes(organisation_id: str, provider: str, object_type: str | None = None, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {'viewer'})
    return PushService().list(organisation_id, provider, object_type)


@api.get('/organisations/{organisation_id}/pushes/{push_id}')
def get_push(organisation_id: str, push_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {'viewer'})
    return PushService().get(organisation_id, push_id)


@api.post('/organisations/{organisation_id}/pushes/{push_id}/review')
def review_push(organisation_id: str, push_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, APPROVE_ROLES)
    return PushService().review(organisation_id, push_id, user.email)


@api.post('/organisations/{organisation_id}/pushes/{push_id}/execute')
def execute_push(organisation_id: str, push_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant'})
    return PushService().execute(organisation_id, push_id, user.email)


@api.get('/organisations/{organisation_id}/pay-runs/{run_id}/pushes')
def payroll_pushes(organisation_id: str, run_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {'viewer'})
    return PayrollService().pushes(organisation_id, run_id)


@api.get('/organisations/{organisation_id}/integrations/{provider}/account-mappings/suggest')
def suggest_account_mappings(organisation_id: str, provider: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {'owner', 'administrator', 'accountant'})
    return AccountMappingService().suggestions(organisation_id, provider)


PayBasis = Literal['monthly', 'hourly', 'board_fee']


class EmployeeIn(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    email: str | None = None
    personal_id: str | None = None
    # Monthly salary or board fee; leave empty for hourly employees.
    gross_salary: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    funded_pension_percent: Decimal = Decimal('2')
    apply_tax_free_minimum: bool = False
    board_member: bool = False
    active: bool = True
    pay_basis: PayBasis | None = None
    fte: Decimal | None = Field(default=None, gt=0, le=1, decimal_places=4)
    hourly_rate: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    social_tax_minimum_exemption: str | None = None
    employment_start_date: str | None = None
    employment_end_date: str | None = None


class EmployeePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    email: str | None = None
    personal_id: str | None = None
    gross_salary: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    funded_pension_percent: Decimal | None = None
    apply_tax_free_minimum: bool | None = None
    board_member: bool | None = None
    active: bool | None = None
    pay_basis: PayBasis | None = None
    fte: Decimal | None = Field(default=None, gt=0, le=1, decimal_places=4)
    hourly_rate: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    social_tax_minimum_exemption: str | None = None
    employment_start_date: str | None = None
    employment_end_date: str | None = None


class PayRunIn(BaseModel):
    period: str = Field(pattern=r'^\d{4}-(0[1-9]|1[0-2])$')
    # Hours worked per hourly employee id for this month.
    hours: dict[str, Decimal] | None = None


@api.exception_handler(PayrollConflict)
async def payroll_conflict(_request: Request, error: PayrollConflict):
    return JSONResponse({'detail': str(error)}, status_code=409)


@api.get('/organisations/{organisation_id}/employees')
def payroll_employees(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {'viewer'})
    return PayrollService().employees(organisation_id)


@api.post('/organisations/{organisation_id}/employees', status_code=201)
def payroll_create_employee(organisation_id: str, payload: EmployeeIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return PayrollService().save_employee(organisation_id, actor=user.email, **payload.model_dump(exclude_unset=True))


@api.patch('/organisations/{organisation_id}/employees/{employee_id}')
def payroll_update_employee(organisation_id: str, employee_id: str, payload: EmployeePatch, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return PayrollService().save_employee(organisation_id, employee_id=employee_id, actor=user.email, **payload.model_dump(exclude_unset=True))


@api.get('/organisations/{organisation_id}/pay-runs')
def payroll_runs(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {'viewer'})
    return PayrollService().runs(organisation_id)


@api.post('/organisations/{organisation_id}/pay-runs', status_code=201)
def payroll_create_run(organisation_id: str, payload: PayRunIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return PayrollService().create_run(organisation_id, period=payload.period, actor=user.email, hours=payload.hours)


@api.post('/organisations/{organisation_id}/pay-runs/{run_id}/approve')
def payroll_approve(organisation_id: str, run_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, APPROVE_ROLES)
    return PayrollService().approve(organisation_id, run_id, actor=user.email)


@api.delete('/organisations/{organisation_id}/pay-runs/{run_id}', status_code=204)
def payroll_delete(organisation_id: str, run_id: str, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    PayrollService().delete_run(organisation_id, run_id, actor=user.email)
    return Response(status_code=204)


@api.get('/organisations/{organisation_id}/pay-runs/{run_id}/payslips.pdf')
def payroll_payslips(organisation_id: str, run_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {'viewer'})
    return Response(PayrollService().payslips_pdf(organisation_id, run_id), media_type='application/pdf',
                    headers={'Content-Disposition': 'attachment; filename="payslips.pdf"'})


@api.get('/organisations/{organisation_id}/pay-runs/{run_id}/workbook.xlsx')
def payroll_workbook(organisation_id: str, run_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {'viewer'})
    return Response(
        PayrollService().workbook_xlsx(organisation_id, run_id),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename="pay-run-workbook.xlsx"'},
    )


@api.get('/organisations/{organisation_id}/payroll/tsd-preparations')
def payroll_tsd_preparations(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {'viewer'})
    return TSDExportService().preparations(organisation_id)


@api.post('/organisations/{organisation_id}/pay-runs/{run_id}/tsd/prepare')
def payroll_prepare_tsd(organisation_id: str, run_id: str,
                        user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return TSDExportService().prepare(organisation_id, run_id, actor=user.email)


@api.get('/organisations/{organisation_id}/pay-runs/{run_id}/tsd/{preparation_id}')
def payroll_get_tsd(organisation_id: str, run_id: str, preparation_id: str,
                    user: User = Depends(current_user)):
    _require(organisation_id, user, APPROVE_ROLES | {'viewer'})
    result = TSDExportService().get(organisation_id, preparation_id)
    if result['pay_run_id'] != run_id:
        raise KeyError('TSD preparation not found')
    return result


@api.post('/organisations/{organisation_id}/pay-runs/{run_id}/tsd/{preparation_id}/review')
def payroll_review_tsd(organisation_id: str, run_id: str, preparation_id: str,
                       user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    prepared = TSDExportService().get(organisation_id, preparation_id)
    if prepared['pay_run_id'] != run_id:
        raise KeyError('TSD preparation not found')
    return TSDExportService().review(organisation_id, preparation_id, actor=user.email)


@api.get('/organisations/{organisation_id}/pay-runs/{run_id}/tsd/{preparation_id}/export.xbrl.xml')
def payroll_export_tsd_xbrl(organisation_id: str, run_id: str, preparation_id: str,
                            user: User = Depends(current_user)):
    _require(organisation_id, user, WRITE_ROLES)
    prepared = TSDExportService().get(organisation_id, preparation_id)
    if prepared['pay_run_id'] != run_id:
        raise KeyError('TSD preparation not found')
    payload = TSDExportService().export_xbrl_gl(organisation_id, preparation_id, actor=user.email)
    return Response(payload, media_type='application/xml', headers={
        'Content-Disposition': f'attachment; filename="tsd-{prepared["period"]}.xbrl.xml"'
    })


@api.get('/organisations/{organisation_id}/pay-runs/{run_id}/tsd/{preparation_id}/export.csv')
def payroll_export_tsd_csv(organisation_id: str, run_id: str, preparation_id: str,
                           user: User = Depends(current_user)):
    _require(organisation_id, user, WRITE_ROLES)
    prepared = TSDExportService().get(organisation_id, preparation_id)
    if prepared['pay_run_id'] != run_id:
        raise KeyError('TSD preparation not found')
    payload = TSDExportService().export_csv(organisation_id, preparation_id, actor=user.email)
    return Response(payload, media_type='text/csv', headers={
        'Content-Disposition': f'attachment; filename="tsd-{prepared["period"]}.csv"'
    })
