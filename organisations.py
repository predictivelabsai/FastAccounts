"""Organisation tenancy, role checks, and country-aware bootstrap data."""
from __future__ import annotations

import calendar
from datetime import date
from typing import Iterable

from core_utils import audit, canonical_json, new_id, utc_now
from database import Database, get_database


ROLES = {"owner", "administrator", "accountant", "approver", "viewer"}
WRITE_ROLES = {"owner", "administrator", "accountant"}
APPROVE_ROLES = {"owner", "administrator", "accountant", "approver"}
ENTITY_COUNTRIES = {
    "UK_COMPANY": "UK", "UK_SOLE_TRADER": "UK",
    "EE_OU": "EE", "EE_FIE": "EE",
}


UK_ACCOUNTS = (
    ("1000", "Business bank", "Asset", "Debit", "BANK"),
    ("1100", "Trade receivables", "Asset", "Debit", "AR"),
    ("1200", "VAT receivable", "Asset", "Debit", "INPUT_VAT"),
    ("2000", "Trade payables", "Liability", "Credit", "AP"),
    ("2100", "VAT payable", "Liability", "Credit", "OUTPUT_VAT"),
    ("3000", "Owner capital / share capital", "Equity", "Credit", "CAPITAL"),
    ("3200", "Retained earnings", "Equity", "Credit", "RETAINED_EARNINGS"),
    ("4000", "Sales", "Income", "Credit", "SALES"),
    ("5000", "Cost of sales", "Expense", "Debit", "COST_OF_SALES"),
    ("6000", "Operating expenses", "Expense", "Debit", "EXPENSE"),
)

EE_ACCOUNTS = (
    ("1010", "Arvelduskonto", "Asset", "Debit", "BANK"),
    ("1210", "Nõuded ostjate vastu", "Asset", "Debit", "AR"),
    ("1510", "Sisendkäibemaks", "Asset", "Debit", "INPUT_VAT"),
    ("2010", "Võlad tarnijatele", "Liability", "Credit", "AP"),
    ("2510", "Käibemaksukohustus", "Liability", "Credit", "OUTPUT_VAT"),
    ("3010", "Oma-/osakapital", "Equity", "Credit", "CAPITAL"),
    ("3310", "Eelmiste perioodide kasum", "Equity", "Credit", "RETAINED_EARNINGS"),
    ("4010", "Müügitulu", "Income", "Credit", "SALES"),
    ("5010", "Müüdud kaupade kulu", "Expense", "Debit", "COST_OF_SALES"),
    ("6010", "Tegevuskulud", "Expense", "Debit", "EXPENSE"),
)

UK_TAXES = (
    ("UK20", "Standard rate 20%", 20, "standard", {"vat_box": [1, 6]}),
    ("UK5", "Reduced rate 5%", 5, "reduced", {"vat_box": [1, 6]}),
    ("UK0", "Zero rated", 0, "zero", {"vat_box": [6]}),
    ("UKEX", "Exempt", 0, "exempt", {"vat_box": [6]}),
    ("UKOS", "Outside scope", 0, "out_of_scope", {}),
    ("UKRC", "Reverse charge", 20, "reverse_charge", {"vat_box": [1, 4, 6, 7]}),
)

EE_TAXES = (
    ("EE24", "Standard rate 24%", 24, "standard", {"kmd": [1, 4, 5]}),
    ("EE13", "Reduced rate 13%", 13, "reduced", {"kmd": [2, 4, 5]}),
    ("EE9", "Reduced rate 9%", 9, "reduced", {"kmd": [2, 4, 5]}),
    ("EE0", "Zero rated", 0, "zero", {"kmd": [3]}),
    ("EEEX", "Tax exempt", 0, "exempt", {"kmd": [8]}),
    ("EEOS", "Outside scope", 0, "out_of_scope", {}),
    ("EERC", "Reverse charge", 24, "reverse_charge", {"kmd": [1, 4, 5]}),
    ("EEICS", "Intra-EU supply", 0, "intra_eu", {"kmd": [3], "vd": True}),
)


class AccessDenied(PermissionError):
    pass


class OrganisationService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    def create(self, *, name: str, country_code: str, entity_type: str,
               owner_email: str, base_currency: str | None = None,
               registration_no: str = "", vat_no: str = "",
               fiscal_year_start: int = 1) -> dict:
        country = country_code.upper()
        entity = entity_type.upper()
        email = owner_email.strip().lower()
        if ENTITY_COUNTRIES.get(entity) != country:
            raise ValueError("Entity type does not belong to the selected country")
        if not name.strip() or "@" not in email:
            raise ValueError("Organisation name and a valid owner email are required")
        currency = (base_currency or ("GBP" if country == "UK" else "EUR")).upper()
        if len(currency) != 3 or not 1 <= fiscal_year_start <= 12:
            raise ValueError("Invalid currency or fiscal year start")
        organisation_id = new_id()
        now = utc_now()
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO organisations(id,name,country_code,entity_type,base_currency,registration_no,vat_no,fiscal_year_start,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (organisation_id, name.strip(), country, entity, currency,
                 registration_no.strip() or None, vat_no.strip() or None,
                 fiscal_year_start, now, now),
            )
            tx.execute(
                "INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)",
                (new_id(), organisation_id, email, "owner", now),
            )
            self._seed_accounts(tx, organisation_id, country)
            self._seed_taxes(tx, organisation_id, country)
            for document_type, prefix in (("invoice", "INV-"), ("credit_note", "CRN-")):
                tx.execute(
                    "INSERT INTO document_sequences(organisation_id,document_type,prefix,next_number) VALUES (?,?,?,1)",
                    (organisation_id, document_type, prefix),
                )
            self._seed_periods(tx, organisation_id, fiscal_year_start)
            audit(tx, organisation_id, email, "organisation.created", "organisation", organisation_id,
                  {"country": country, "entity_type": entity})
        return self.get(organisation_id)

    def _seed_accounts(self, tx, organisation_id: str, country: str) -> None:
        for code, name, account_type, normal_balance, role in (UK_ACCOUNTS if country == "UK" else EE_ACCOUNTS):
            tx.execute(
                "INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) VALUES (?,?,?,?,?,?,?)",
                (new_id(), organisation_id, code, name, account_type, normal_balance, role),
            )

    def _seed_taxes(self, tx, organisation_id: str, country: str) -> None:
        valid_from = "2025-01-01" if country == "EE" else "2011-01-04"
        for code, name, rate, kind, mapping in (UK_TAXES if country == "UK" else EE_TAXES):
            tx.execute(
                "INSERT INTO tax_codes(id,organisation_id,code,name,country_code,rate,kind,return_mapping,valid_from) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (new_id(), organisation_id, code, name, country, rate, kind,
                 canonical_json(mapping), valid_from),
            )

    def _seed_periods(self, tx, organisation_id: str, start_month: int) -> None:
        year = date.today().year - (1 if date.today().month < start_month else 0)
        for offset in range(2):
            fiscal_start_year = year + offset
            for month_offset in range(12):
                month_index = start_month - 1 + month_offset
                period_year = fiscal_start_year + month_index // 12
                period_month = month_index % 12 + 1
                last_day = calendar.monthrange(period_year, period_month)[1]
                starts = date(period_year, period_month, 1)
                ends = date(period_year, period_month, last_day)
                tx.execute(
                    "INSERT INTO fiscal_periods(id,organisation_id,code,starts_on,ends_on) VALUES (?,?,?,?,?)",
                    (new_id(), organisation_id, starts.strftime("%Y-%m"), starts.isoformat(), ends.isoformat()),
                )

    def get(self, organisation_id: str) -> dict:
        row = self.db.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
        if not row:
            raise KeyError("Organisation not found")
        return row

    def for_user(self, email: str) -> list[dict]:
        return self.db.rows(
            "SELECT o.*,m.role FROM organisations o JOIN memberships m ON m.organisation_id=o.id "
            "WHERE lower(m.email)=lower(?) AND o.active=1 ORDER BY o.name",
            (email.strip(),),
        )

    def role(self, organisation_id: str, email: str) -> str | None:
        row = self.db.one(
            "SELECT role FROM memberships WHERE organisation_id=? AND lower(email)=lower(?)",
            (organisation_id, email.strip()),
        )
        return row["role"] if row else None

    def require(self, organisation_id: str, email: str, allowed: Iterable[str]) -> str:
        role = self.role(organisation_id, email)
        if role not in set(allowed):
            raise AccessDenied("You do not have permission for this organisation")
        return role

    def add_member(self, organisation_id: str, actor: str, email: str, role: str) -> dict:
        self.require(organisation_id, actor, {"owner", "administrator"})
        if role not in ROLES:
            raise ValueError("Unknown role")
        member_id, now = new_id(), utc_now()
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)",
                (member_id, organisation_id, email.strip().lower(), role, now),
            )
            audit(tx, organisation_id, actor, "membership.created", "membership", member_id,
                  {"email": email.strip().lower(), "role": role})
        return self.db.one("SELECT * FROM memberships WHERE id=?", (member_id,)) or {}
