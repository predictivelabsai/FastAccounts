"""Public integration catalogue and connection capability metadata."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Integration:
    key: str
    name: str
    category: str
    markets: tuple[str, ...]
    status: str
    logo: str
    logo_alt: str
    description: str
    capabilities: tuple[str, ...]
    direction: str
    ownership: str
    docs_url: str


CATALOGUE = (
    Integration(
        key="quickbooks",
        name="QuickBooks Online",
        category="Accounting platform",
        markets=("UK",),
        status="Adapter ready · not connected",
        logo="/static/integrations/quickbooks.svg",
        logo_alt="QuickBooks logo",
        description="Coexist with an existing QuickBooks company through reviewed imports and controlled exports.",
        capabilities=("Contacts", "Invoices and bills", "Payments", "Accounts and tax", "Attachments"),
        direction="Import first · export by policy",
        ownership="Configured per object",
        docs_url="https://developer.intuit.com/app/developer/qbo/docs/learn/explore-the-quickbooks-online-api",
    ),
    Integration(
        key="xero",
        name="Xero",
        category="Accounting platform",
        markets=("UK", "EE"),
        status="Adapter ready · not connected",
        logo="/static/integrations/xero.svg",
        logo_alt="Xero logo",
        description="Exchange accounting data with a Xero organisation using tenant-scoped OAuth and explicit conflict review.",
        capabilities=("Contacts", "Invoices and credit notes", "Payments", "Bank transactions", "Reports"),
        direction="Import first · export by policy",
        ownership="Configured per object",
        docs_url="https://developer.xero.com/documentation/api/accounting/overview",
    ),
    Integration(
        key="merit",
        name="Merit Aktiva",
        category="Accounting platform",
        markets=("EE",),
        status="Adapter ready · test company needed",
        logo="/static/integrations/merit-aktiva.svg",
        logo_alt="Merit Aktiva logo",
        description="Support Estonian accountant workflows with HMAC-signed V2 invoice, payment, tax, GL and report exchange.",
        capabilities=("Sales and purchase invoices", "Payments", "Tax IDs", "GL transactions", "Dimensions"),
        direction="Import and export · reviewed",
        ownership="Configured per object",
        docs_url="https://api.merit.ee/connecting-robots/reference-manual/",
    ),
    Integration(
        key="hmrc",
        name="HMRC Making Tax Digital",
        category="Filing agent",
        markets=("UK",),
        status="Sandbox adapter · filing gated",
        logo="/static/integrations/hmrc.svg",
        logo_alt="HMRC service mark",
        description="Prepare accountant-reviewed VAT workpapers now; add sandbox obligations and submission flows before production approval.",
        capabilities=("VAT obligations", "Nine-box workpaper", "Review declaration", "Submission receipt plan"),
        direction="FastAccounts to HMRC",
        ownership="Accountant-approved filing",
        docs_url="https://developer.service.hmrc.gov.uk/api-documentation/docs/api/service/vat-api/1.0",
    ),
    Integration(
        key="emta",
        name="Estonian Tax and Customs Board",
        category="Filing agent",
        markets=("EE",),
        status="Export ready · filing gated",
        logo="/static/integrations/emta.svg",
        logo_alt="Estonian Tax and Customs Board service mark",
        description="Generate accountant-reviewed KMD and VD workpapers and retain a stub for a future supported filing channel.",
        capabilities=("KMD workpaper", "VD preparation", "Audit export", "Direct filing discovery"),
        direction="FastAccounts to accountant",
        ownership="Accountant-reviewed export",
        docs_url="https://www.emta.ee/en/business-client/taxes-and-payment/value-added-tax",
    ),
    Integration(
        key="open_banking",
        name="Open banking",
        category="Bank data",
        markets=("UK", "EE"),
        status="Read-only candidate",
        logo="/static/integrations/open-banking.svg",
        logo_alt="Open banking icon",
        description="Read booked transactions through a selected AISP after GB/EE business-bank coverage and legal review.",
        capabilities=("Consent lifecycle", "Accounts and balances", "Booked transactions", "Reconciliation input"),
        direction="Read-only first",
        ownership="Bank remains source",
        docs_url="https://standards.openbanking.org.uk/api-specifications/latest/",
    ),
)


def get_integration(key: str) -> Integration | None:
    return next((item for item in CATALOGUE if item.key == key), None)
