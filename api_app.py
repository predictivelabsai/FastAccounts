"""Typed FastAPI surface for the FastAccounts bookkeeping workspace."""
from __future__ import annotations

import os
import secrets
from decimal import Decimal
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

import integrations
import version
from banking import BankingService
from automation import AutomationService, email_configured, email_status
from connectors.registry import provider_metadata
from database import get_database
from documents import DocumentService
from integration_service import IntegrationService
from import_service import ImportService
from ledger import LedgerService, PostingLine
from organisations import APPROVE_ROLES, WRITE_ROLES, AccessDenied, OrganisationService
from governance import GovernanceService
from tax import TaxService
from payroll import PayrollConflict, PayrollService


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
    payment_terms_days: int = Field(default=14, ge=0, le=365)


class LineIn(BaseModel):
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal
    account_id: str
    tax_code_id: str | None = None


class InvoiceIn(BaseModel):
    contact_id: str
    issue_date: str
    due_date: str | None = None
    currency: str | None = None
    amount_type: Literal["exclusive", "inclusive", "no_tax"] = "exclusive"
    reference: str = ""
    notes: str = ""
    document_type: Literal["invoice", "credit_note"] = "invoice"
    original_invoice_id: str | None = None
    lines: list[LineIn] = Field(min_length=1)


class BillIn(BaseModel):
    contact_id: str
    supplier_number: str
    bill_date: str
    due_date: str
    currency: str | None = None
    reference: str = ""
    notes: str = ""
    document_type: Literal["bill", "supplier_credit"] = "bill"
    lines: list[LineIn] = Field(min_length=1)


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


class FileImportIn(BaseModel):
    object_type: str = Field(min_length=1, max_length=80)
    csv_content: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class IntegrationApplyIn(BaseModel):
    decisions: dict[str, Literal["apply", "reject"]] = Field(default_factory=dict)


class JournalLineIn(BaseModel):
    account_id: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    memo: str = ""


class JournalIn(BaseModel):
    voucher_code: str
    posting_date: str
    currency: str
    idempotency_key: str
    lines: list[JournalLineIn] = Field(min_length=2)


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
    allowed = {"bills", "bank_transactions", "vat_returns"}
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
def list_contacts(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return get_database().rows("SELECT * FROM contacts WHERE organisation_id=? ORDER BY name", (organisation_id,))


@api.post("/organisations/{organisation_id}/contacts", status_code=201)
def create_contact(organisation_id: str, payload: ContactIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    return DocumentService().create_contact(organisation_id, **payload.model_dump())


@api.get("/organisations/{organisation_id}/invoices")
def list_invoices(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return get_database().rows(
        "SELECT i.*,c.name contact_name FROM invoices i JOIN contacts c ON c.id=i.contact_id "
        "WHERE i.organisation_id=? ORDER BY i.issue_date DESC,i.created_at DESC", (organisation_id,)
    )


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
def list_bills(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return get_database().rows(
        "SELECT b.*,c.name contact_name FROM bills b JOIN contacts c ON c.id=b.contact_id "
        "WHERE b.organisation_id=? ORDER BY b.bill_date DESC,b.created_at DESC", (organisation_id,)
    )


@api.post("/organisations/{organisation_id}/bills", status_code=201)
def create_bill(organisation_id: str, payload: BillIn, user: User = Depends(require_csrf)):
    _require(organisation_id, user, WRITE_ROLES)
    data = payload.model_dump()
    data["lines"] = [line.model_dump() for line in payload.lines]
    return DocumentService().create_bill(organisation_id, actor=user.email, **data)


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
    return get_database().rows(
        "SELECT * FROM bank_transactions WHERE organisation_id=? ORDER BY booking_date DESC", (organisation_id,)
    )


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


@api.get("/organisations/{organisation_id}/reports/trial-balance")
def trial_balance(organisation_id: str, start: str, end: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return LedgerService().trial_balance(organisation_id, start=start, end=end)


@api.get("/organisations/{organisation_id}/reports/profit-and-loss")
def profit_loss(organisation_id: str, start: str, end: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return LedgerService().profit_and_loss(organisation_id, start=start, end=end)


@api.get("/organisations/{organisation_id}/reports/balance-sheet")
def balance_sheet(organisation_id: str, as_at: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "approver", "viewer"})
    return LedgerService().balance_sheet(organisation_id, as_at=as_at)


@api.get("/organisations/{organisation_id}/reports/general-ledger")
def general_ledger(organisation_id: str, start: str, end: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "viewer"})
    return LedgerService().general_ledger(organisation_id, start=start, end=end)


@api.get("/organisations/{organisation_id}/reports/receivables-aging")
def receivables_aging(organisation_id: str, as_at: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator", "accountant", "viewer"})
    return LedgerService().receivables_aging(organisation_id, as_at=as_at)


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
    lines = [PostingLine(account_id=line.account_id, debit=line.debit, credit=line.credit, memo=line.memo)
             for line in payload.lines]
    return LedgerService().post(
        organisation_id=organisation_id, voucher_type="manual_journal",
        voucher_id=payload.idempotency_key, voucher_code=payload.voucher_code,
        posting_date=payload.posting_date, lines=lines, actor=user.email,
        currency=payload.currency,
    )


@api.get("/integrations")
def integration_catalogue(user: User = Depends(current_user)):
    del user
    return [{**item.__dict__, **provider_metadata(item.key)} for item in integrations.CATALOGUE]


@api.get("/organisations/{organisation_id}/integrations")
def organisation_integrations(organisation_id: str, user: User = Depends(current_user)):
    _require(organisation_id, user, {"owner", "administrator"})
    return IntegrationService().connections(organisation_id)


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
