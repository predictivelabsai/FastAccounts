"""Deterministic-shape, synthetic-only demo books for UK and Estonia."""
from __future__ import annotations

from datetime import date

from banking import BankingService
from database import get_database
from documents import DocumentService
from organisations import OrganisationService


DEMO_EMAIL = "demo@fastaccounts.local"


def _seed_organisation(country: str) -> dict:
    db = get_database()
    name = "Northstar Studio Ltd" if country == "UK" else "Põhjatäht Teenused OÜ"
    existing = db.one("SELECT * FROM organisations WHERE name=?", (name,))
    if existing:
        return existing
    orgs, docs = OrganisationService(db), DocumentService(db)
    organisation = orgs.create(
        name=name, country_code=country,
        entity_type="UK_COMPANY" if country == "UK" else "EE_OU",
        owner_email=DEMO_EMAIL,
        registration_no="09999991" if country == "UK" else "14999991",
        vat_no="GB999999973" if country == "UK" else "EE149999991",
    )
    contact = docs.create_contact(
        organisation["id"], name="Acme Synthetic Customer",
        country_code="GB" if country == "UK" else "EE", contact_type="customer",
        email="accounts@example.invalid", address="1 Example Street",
    )
    supplier = docs.create_contact(
        organisation["id"], name="Example Cloud Supplier",
        country_code="GB" if country == "UK" else "EE", contact_type="supplier",
        email="billing@example.invalid",
    )
    accounts = {row["system_role"]: row for row in db.rows(
        "SELECT * FROM accounts WHERE organisation_id=?", (organisation["id"],)
    )}
    tax_code = "UK20" if country == "UK" else "EE24"
    tax = db.one("SELECT * FROM tax_codes WHERE organisation_id=? AND code=?", (organisation["id"], tax_code))
    period_date = db.scalar(
        "SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1", (organisation["id"],)
    )
    docs.create_item(
        organisation["id"], code="CONSULT", name="Consulting service",
        sales_account_id=accounts["SALES"]["id"], tax_code_id=tax["id"], unit_price="750",
    )
    invoice = docs.create_invoice(
        organisation["id"], contact_id=contact["id"], issue_date=period_date,
        actor=DEMO_EMAIL, reference="SYNTHETIC-UAT-001",
        lines=[{"description": "Synthetic consulting engagement", "quantity": 2,
                "unit_price": "750", "account_id": accounts["SALES"]["id"], "tax_code_id": tax["id"]}],
    )
    invoice = docs.issue_invoice(invoice["id"], actor=DEMO_EMAIL)
    bill = docs.create_bill(
        organisation["id"], contact_id=supplier["id"], supplier_number="SYN-CLOUD-001",
        bill_date=period_date, due_date=period_date, actor=DEMO_EMAIL,
        lines=[{"description": "Synthetic cloud hosting", "quantity": 1,
                "unit_price": "100", "account_id": accounts["EXPENSE"]["id"], "tax_code_id": tax["id"]}],
    )
    docs.approve_bill(bill["id"], actor=DEMO_EMAIL)
    bank = docs.create_bank_account(
        organisation["id"], name="Synthetic operating account",
        currency=organisation["base_currency"], iban="EE001010000000000001" if country == "EE" else "",
        sort_code="12-34-56" if country == "UK" else "",
    )
    statement = (
        "date,amount,currency,counterparty,reference,id\n"
        f"{period_date},{invoice['total']},{organisation['base_currency']},Acme Synthetic Customer,{invoice['number']},SYN-BANK-{country}-1\n"
    ).encode()
    BankingService(db).import_csv(organisation["id"], bank["id"], statement, actor=DEMO_EMAIL)
    return organisation


def seed_demo() -> list[dict]:
    db = get_database()
    db.migrate()
    return [_seed_organisation("UK"), _seed_organisation("EE")]


if __name__ == "__main__":
    for organisation in seed_demo():
        print(f"Seeded {organisation['name']} ({organisation['id']})")
