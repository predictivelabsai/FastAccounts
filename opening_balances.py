"""Opening balance and ledger-only receivable/payable imports."""
from __future__ import annotations

import calendar
import csv
import hashlib
import io
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

from core_utils import canonical_json, money, new_id, utc_now
from database import Database, get_database
from documents import DocumentService
from ledger import LedgerService, PostingLine


CSV_COLUMNS = ("type", "name", "original_number", "original_date", "due_date", "amount")
ALREADY_POSTED = "Opening balances already posted; add a correcting journal instead"


def _amount(value) -> Decimal:
    try:
        if isinstance(value, (float, bool)):
            raise ValueError
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount != money(amount):
            raise ValueError
        return money(amount)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Amounts must be non-negative decimals with at most two decimal places") from None


def _open_item(row, number):
    try:
        if not isinstance(row, dict) or set(row) != set(CSV_COLUMNS):
            raise ValueError("Expected columns: " + ",".join(CSV_COLUMNS))
        item = {key: str(row[key]).strip() for key in CSV_COLUMNS}
        if item["type"] not in {"customer", "supplier"}:
            raise ValueError("Type must be customer or supplier")
        if any(row[key] is None or not item[key] for key in ("name", "original_number")):
            raise ValueError("Name and original number are required")
        for key in ("original_date", "due_date"):
            item[key] = date.fromisoformat(item[key]).isoformat()
        item["amount"] = _amount(row["amount"])
        if item["amount"] <= 0:
            raise ValueError("Amount must be positive")
        return item
    except (ValueError, TypeError) as error:
        raise ValueError(f"Row {number}: {error}") from None


def parse_open_items_csv(content: str) -> dict:
    if not isinstance(content, str) or len(content) > 2_000_000:
        raise ValueError("CSV content must be text of at most 2,000,000 characters")
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff"), newline=""), strict=True)
    rows, errors = [], []
    try:
        if reader.fieldnames != list(CSV_COLUMNS):
            raise ValueError("Row 1: Expected columns: " + ",".join(CSV_COLUMNS))
        for row in reader:
            try:
                rows.append(_open_item(row, reader.line_num))
            except ValueError as error:
                errors.append(str(error))
    except csv.Error as error:
        errors.append(f"Row {reader.line_num + 1}: {error}")
    if errors:
        raise ValueError("; ".join(errors))
    if not rows:
        raise ValueError("Row 2: At least one opening item is required")
    totals = {side: sum((r["amount"] for r in rows if r["type"] == side), Decimal("0"))
              for side in ("customer", "supplier")}
    return {"rows": rows, "totals": totals}


class OpeningBalanceService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()
        self.ledger = LedgerService(self.db)

    def _organisation(self, tx, organisation_id, *, lock=False):
        if lock and self.db.dialect == "sqlite":
            tx.execute("BEGIN IMMEDIATE")
        query = "SELECT * FROM organisations WHERE id=?"
        if lock and self.db.dialect == "postgres":
            query += " FOR UPDATE"
        organisation = tx.one(query, (organisation_id,))
        if not organisation:
            raise KeyError("Organisation not found")
        return organisation

    def _ensure_period(self, tx, organisation_id, posting_date):
        query = "SELECT * FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on"
        if self.db.dialect == "postgres":
            query += " FOR UPDATE"
        periods = tx.rows(query, (organisation_id,))
        covering = [p for p in periods if p["starts_on"] <= posting_date <= p["ends_on"]]
        if any(p["status"] == "Locked" for p in covering):
            raise ValueError("Opening balances must post to an open period")
        if covering:
            return
        month = date.fromisoformat(posting_date).replace(day=1)
        # Create the requested month only. Existing periods, including future ones,
        # are never modified or reopened.
        tx.execute(
            "INSERT INTO fiscal_periods(id,organisation_id,code,starts_on,ends_on,status) "
            "VALUES (?,?,?,?,?,'Open') ON CONFLICT (organisation_id,code) DO NOTHING",
            (new_id(), organisation_id, month.strftime("%Y-%m"), month.isoformat(),
             month.replace(day=calendar.monthrange(month.year, month.month)[1]).isoformat()),
        )
        self.ledger._validate_period(tx, organisation_id, posting_date)

    def ensure_period(self, organisation_id, posting_date):
        posting_date = date.fromisoformat(posting_date).isoformat()
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id, lock=True)
            self._ensure_period(tx, organisation_id, posting_date)

    def snapshot(self, organisation_id, *, opening_date):
        opening_date = date.fromisoformat(opening_date).isoformat()
        with self.db.transaction() as tx:
            organisation = self._organisation(tx, organisation_id)
            accounts = tx.rows(
                "SELECT * FROM accounts WHERE organisation_id=? AND account_type IN ('Asset','Liability','Equity') ORDER BY code",
                (organisation_id,))
            balances = defaultdict(lambda: [Decimal("0"), Decimal("0")])
            for entry in tx.rows(
                "SELECT g.account_id,g.debit,g.credit FROM gl_entries g JOIN posting_batches p ON p.id=g.posting_batch_id "
                "WHERE g.organisation_id=? AND p.organisation_id=? AND g.entry_date<=? AND p.status IN ('Posted','Reversed')",
                (organisation_id, organisation_id, opening_date)):
                balances[entry["account_id"]][0] += money(entry["debit"])
                balances[entry["account_id"]][1] += money(entry["credit"])
            for account in accounts:
                debit, credit = balances[account["id"]]
                account.update(debit=debit, credit=credit, balance=debit-credit)
            batch = self._existing(tx, organisation_id, "opening_balance", "opening")
            return {"opening_date": opening_date, "currency": organisation["base_currency"],
                    "accounts": accounts, "opening_batch": batch}

    @staticmethod
    def _existing(tx, organisation_id, voucher_type, voucher_id):
        return tx.one("SELECT * FROM posting_batches WHERE organisation_id=? AND voucher_type=? AND voucher_id=?",
                      (organisation_id, voucher_type, voucher_id))

    @staticmethod
    def _control(tx, organisation_id, role, account_type):
        account = tx.one("SELECT * FROM accounts WHERE organisation_id=? AND system_role=? AND active=1",
                         (organisation_id, role))
        if not account or account["account_type"] != account_type:
            raise ValueError(f"An active {account_type} account with system role {role} is required")
        return account["id"]

    @staticmethod
    def _signature(lines):
        totals = defaultdict(lambda: [Decimal("0"), Decimal("0")])
        for line in lines:
            totals[line.account_id][0] += line.debit
            totals[line.account_id][1] += line.credit
        return dict(totals)

    def post(self, organisation_id, *, posting_date, actor, lines):
        posting_date = date.fromisoformat(posting_date).isoformat()
        with self.db.transaction() as tx:
            organisation = self._organisation(tx, organisation_id, lock=True)
            accounts = {a["id"]: a for a in tx.rows("SELECT * FROM accounts WHERE organisation_id=?",
                                                    (organisation_id,))}
            inputs = []
            for line in lines:
                account = accounts.get(line.get("account_id"))
                if not account or not account["active"]:
                    raise KeyError("Account not found in this organisation or inactive")
                if account["account_type"] not in {"Asset", "Liability", "Equity"}:
                    raise ValueError("Opening balances only allow Asset, Liability and Equity accounts; income and expense accounts are not allowed")
                debit, credit = _amount(line.get("debit", "0")), _amount(line.get("credit", "0"))
                if debit and credit:
                    raise ValueError("Each opening line must contain exactly one debit or credit")
                if debit or credit:
                    inputs.append(PostingLine(account["id"], debit=debit, credit=credit,
                                              memo="Opening balances", source_line_type="opening_balance_input"))
            existing = self._existing(tx, organisation_id, "opening_balance", "opening")
            if existing:
                stored = [PostingLine(e["account_id"], debit=money(e["debit"]), credit=money(e["credit"]))
                          for e in tx.rows("SELECT * FROM gl_entries WHERE organisation_id=? AND posting_batch_id=? "
                                           "AND source_line_type='opening_balance_input'", (organisation_id, existing["id"]))]
                if existing["status"] != "Posted" or existing["posting_date"] != posting_date or (
                        inputs and self._signature(inputs) != self._signature(stored)):
                    raise ValueError(ALREADY_POSTED)
                return existing
            if not inputs:
                raise ValueError("At least one non-zero opening balance is required")
            retained = self._control(tx, organisation_id, "RETAINED_EARNINGS", "Equity")
            self._ensure_period(tx, organisation_id, posting_date)
            remainder = sum((line.debit - line.credit for line in inputs), Decimal("0"))
            posting = list(inputs)
            if remainder:
                posting.append(PostingLine(retained, debit=max(-remainder, Decimal("0")),
                    credit=max(remainder, Decimal("0")), memo="Opening balances",
                    source_line_type="opening_balance_offset"))
            return self.ledger.post(organisation_id=organisation_id, voucher_type="opening_balance",
                voucher_id="opening", voucher_code="Opening balances", posting_date=posting_date,
                actor=actor, currency=organisation["base_currency"], lines=posting, tx=tx)

    def post_open_items(self, organisation_id, *, posting_date, actor, rows):
        posting_date = date.fromisoformat(posting_date).isoformat()
        if isinstance(rows, str):
            content = rows
            items = parse_open_items_csv(content)["rows"]
        else:
            items = [_open_item(row, number) for number, row in enumerate(rows, 2)]
            if not items:
                raise ValueError("At least one opening item is required")
            content = canonical_json(items)
        voucher_id = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        if any(item["original_date"] > posting_date for item in items):
            raise ValueError("Original dates must be on or before the opening posting date")
        with self.db.transaction() as tx:
            organisation = self._organisation(tx, organisation_id, lock=True)
            existing = self._existing(tx, organisation_id, "opening_balance_open_items", voucher_id)
            if existing:
                if existing["posting_date"] != posting_date or existing["status"] != "Posted":
                    raise ValueError("Opening file already posted; add a correcting journal instead")
                return existing
            self._ensure_period(tx, organisation_id, posting_date)
            retained = self._control(tx, organisation_id, "RETAINED_EARNINGS", "Equity")
            controls = {side: self._control(tx, organisation_id, role, kind)
                        for side, role, kind in (("customer", "AR", "Asset"), ("supplier", "AP", "Liability"))
                        if any(item["type"] == side for item in items)}
            totals = defaultdict(lambda: Decimal("0"))
            posting = []
            for item in items:
                contact = tx.one("SELECT * FROM contacts WHERE organisation_id=? AND name=? ORDER BY id LIMIT 1",
                                 (organisation_id, item["name"]))
                side = item["type"]
                if not contact:
                    contact = DocumentService(self.db).create_contact(organisation_id, name=item["name"],
                        country_code=organisation["country_code"], contact_type=side, tx=tx)
                elif contact["contact_type"] not in {side, "both"}:
                    tx.execute("UPDATE contacts SET contact_type='both',updated_at=? WHERE organisation_id=? AND id=?",
                               (utc_now(), organisation_id, contact["id"]))
                amount = item["amount"]
                totals[side] += amount
                posting.append(PostingLine(controls[side], debit=amount if side == "customer" else Decimal("0"),
                    credit=amount if side == "supplier" else Decimal("0"), contact_id=contact["id"],
                    due_date=item["due_date"], memo=f"Opening: {item['original_number']} {item['original_date']}"))
            for side, total in totals.items():
                posting.append(PostingLine(retained, debit=total if side == "supplier" else Decimal("0"),
                    credit=total if side == "customer" else Decimal("0"), memo="Opening balances"))
            return self.ledger.post(organisation_id=organisation_id, voucher_type="opening_balance_open_items",
                voucher_id=voucher_id, voucher_code="Opening receivables/payables", posting_date=posting_date,
                actor=actor, currency=organisation["base_currency"], lines=posting, tx=tx)
