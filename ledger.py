"""Immutable double-entry ledger and core financial reports."""
from __future__ import annotations

from dataclasses import dataclass
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from database import Database, get_database
from objects import dimensions, validate_dimensions
from objects_repository import ObjectRepository, DIMENSIONS
from exchange_rates import positive_rate


def comparison_periods(start: str, end: str, compare: str) -> tuple[str, str, str, str]:
    """Calendar-aligned whole periods; equal day counts for arbitrary ranges."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last:
        raise ValueError("Report start must be on or before its end")
    if compare not in {"none", "previous", "prior_year", "ytd"}:
        raise ValueError("Invalid comparison mode")

    def prior_year(day):
        return day.replace(year=day.year - 1, day=min(day.day, monthrange(day.year - 1, day.month)[1]))

    if compare == "ytd":
        first = date(last.year, 1, 1)
        last = date(last.year, last.month, monthrange(last.year, last.month)[1])
        before_first, before_last = prior_year(first), prior_year(last)
        before_last = before_last.replace(day=monthrange(before_last.year, before_last.month)[1])
    elif compare == "prior_year":
        before_first, before_last = prior_year(first), prior_year(last)
        if first.day == 1 and last.day == monthrange(last.year, last.month)[1]:
            before_last = before_last.replace(day=monthrange(before_last.year, before_last.month)[1])
    else:
        before_last = first - timedelta(days=1)
        if first.day == 1 and last.day == monthrange(last.year, last.month)[1]:
            months = (last.year - first.year) * 12 + last.month - first.month + 1
            month_index = first.year * 12 + first.month - 1 - months
            before_first = date(month_index // 12, month_index % 12 + 1, 1)
        else:
            before_first = first - (last - first + timedelta(days=1))
    return tuple(day.isoformat() for day in (first, last, before_first, before_last))


def _add_comparison(report: dict, comparative: dict, compare: str) -> dict:
    report["compare"] = compare
    report["comparative"] = comparative
    by_code = {row["code"]: row for row in comparative["accounts"]}
    for row in report["accounts"]:
        row["comparative_balance"] = by_code[row["code"]]["balance"]
    return report


@dataclass(frozen=True)
class PostingLine:
    account_id: str
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    contact_id: str | None = None
    due_date: str | None = None
    memo: str = ""
    source_line_type: str | None = None
    source_line_id: str | None = None
    transaction_amount: Decimal = Decimal("0")
    transaction_currency: str = ""
    reverses_entry_id: str | None = None
    projects_project_id: str | None = None
    projects_location_id: str | None = None
    projects_person_id: str | None = None
    projects_object_id: str | None = None


class LedgerService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    def _validate_period(self, tx, organisation_id: str, posting_date: str) -> None:
        period = tx.one(
            "SELECT status FROM fiscal_periods WHERE organisation_id=? AND starts_on<=? AND ends_on>=?",
            (organisation_id, posting_date, posting_date),
        )
        if not period:
            raise ValueError("Posting date is outside configured fiscal periods")
        if period["status"] == "Locked":
            raise ValueError("The fiscal period is locked")

    def post(self, *, organisation_id: str, voucher_type: str, voucher_id: str,
             voucher_code: str, posting_date: str, lines: list[PostingLine],
             actor: str, currency: str, exchange_rate: Decimal = Decimal("1"),
             reverses_batch_id: str | None = None, tx=None, allow_inactive_objects: bool = False) -> dict:
        if len(lines) < 2:
            raise ValueError("A posting needs at least two lines")
        exchange_rate = positive_rate(exchange_rate)
        debit = sum((money(line.debit) for line in lines), Decimal("0"))
        credit = sum((money(line.credit) for line in lines), Decimal("0"))
        if debit <= 0 or debit != credit:
            raise ValueError(f"Unbalanced posting: debit {debit} credit {credit}")
        for line in lines:
            if (money(line.debit) > 0) == (money(line.credit) > 0):
                raise ValueError("Each posting line must contain exactly one debit or credit")

        def perform(work):
            objects = ObjectRepository(work, organisation_id)
            if any(any(dimensions(line).values()) for line in lines):
                objects.lock_organisation()
            existing = work.one(
                "SELECT * FROM posting_batches WHERE organisation_id=? AND voucher_type=? AND voucher_id=?",
                (organisation_id, voucher_type, voucher_id),
            )
            if existing:
                return existing
            for line in lines:
                validate_dimensions(objects, line, active=not (allow_inactive_objects or bool(line.reverses_entry_id)))
            self._validate_period(work, organisation_id, posting_date)
            account_ids = {row["id"] for row in work.rows(
                "SELECT id FROM accounts WHERE organisation_id=? AND active=1", (organisation_id,)
            )}
            if any(line.account_id not in account_ids for line in lines):
                raise ValueError("Posting contains an account from another organisation or an inactive account")
            base_currency = work.scalar('SELECT base_currency FROM organisations WHERE id=?', (organisation_id,))
            converted = [(money(decimal(line.debit) * exchange_rate), money(decimal(line.credit) * exchange_rate))
                         if (line.transaction_currency or currency) != base_currency
                         else (money(line.debit), money(line.credit)) for line in lines]
            base_debit = sum((amounts[0] for amounts in converted), Decimal('0'))
            base_credit = sum((amounts[1] for amounts in converted), Decimal('0'))
            if base_debit <= 0 or base_debit != base_credit:
                raise ValueError(f'Unbalanced posting after exchange rate rounding: debit {base_debit} credit {base_credit}')
            batch_id, now = new_id(), utc_now()
            work.execute(
                "INSERT INTO posting_batches(id,organisation_id,voucher_type,voucher_id,voucher_code,posting_date,status,reverses_batch_id,created_at) "
                "VALUES (?,?,?,?,?,?,'Draft',?,?)",
                (batch_id, organisation_id, voucher_type, voucher_id, voucher_code,
                 posting_date, reverses_batch_id, now),
            )
            for index, line in enumerate(lines, 1):
                entry_id = new_id()
                transaction_currency = line.transaction_currency or currency
                transaction_amount = line.transaction_amount or (line.debit - line.credit)
                work.execute(
                    "INSERT INTO gl_entries(id,organisation_id,posting_batch_id,line_number,entry_date,account_id,debit,credit,currency,transaction_amount,transaction_currency,exchange_rate,contact_id,due_date,memo,source_line_type,source_line_id,reverses_entry_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (entry_id, organisation_id, batch_id, index, posting_date, line.account_id,
                     db_number(converted[index - 1][0]), db_number(converted[index - 1][1]), base_currency,
                     db_number(money(transaction_amount)), transaction_currency,
                     db_number(decimal(exchange_rate)), line.contact_id, line.due_date,
                     line.memo, line.source_line_type, line.source_line_id, line.reverses_entry_id),
                )
                objects.save_dimensions('gl', batch_id, entry_id, dimensions(line))
            work.execute(
                "UPDATE posting_batches SET status='Posted',posted_at=?,posted_by=? WHERE id=?",
                (now, actor, batch_id),
            )
            audit(work, organisation_id, actor, "ledger.posted", "posting_batch", batch_id,
                  {"voucher_type": voucher_type, "voucher_code": voucher_code,
                   "debit": str(base_debit), "credit": str(base_credit)})
            return work.one("SELECT * FROM posting_batches WHERE id=?", (batch_id,)) or {}

        if tx is not None:
            return perform(tx)
        with self.db.transaction() as own_tx:
            return perform(own_tx)

    def reverse(self, batch_id: str, *, reversal_date: str, actor: str,
                reason: str = "") -> dict:
        with self.db.transaction() as tx:
            batch = tx.one("SELECT * FROM posting_batches WHERE id=?", (batch_id,))
            if not batch or batch["status"] != "Posted":
                raise ValueError("Only a posted, unreversed batch can be reversed")
            entries = tx.rows(
                "SELECT * FROM gl_entries WHERE posting_batch_id=? ORDER BY line_number", (batch_id,)
            )
            for row in entries:
                row.update(tx.one('SELECT * FROM gl_entry_objects WHERE organisation_id=? AND line_id=?',
                                  (batch['organisation_id'], row['id'])) or {})
            lines = [PostingLine(
                account_id=row["account_id"], debit=decimal(row["credit"]),
                credit=decimal(row["debit"]), contact_id=row["contact_id"],
                due_date=row["due_date"], memo=f"Reversal: {reason or row['memo'] or ''}".strip(),
                source_line_type=row["source_line_type"], source_line_id=row["source_line_id"],
                transaction_amount=-decimal(row["transaction_amount"]),
                transaction_currency=row["transaction_currency"], reverses_entry_id=row["id"],
                **{key: row.get(key) for key in DIMENSIONS},
            ) for row in entries]
            reversal = self.post(
                organisation_id=batch["organisation_id"], voucher_type="reversal",
                voucher_id=batch_id, voucher_code=f"REV-{batch['voucher_code']}",
                posting_date=reversal_date, lines=lines, actor=actor,
                currency=entries[0]["currency"], reverses_batch_id=batch_id, tx=tx,
            )
            tx.execute("UPDATE posting_batches SET status='Reversed' WHERE id=?", (batch_id,))
            audit(tx, batch["organisation_id"], actor, "ledger.reversed", "posting_batch", batch_id,
                  {"reversal_batch_id": reversal["id"], "reason": reason})
            return reversal

    def lock_period(self, period_id: str, *, actor: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("A lock reason is required")
        with self.db.transaction() as tx:
            period = tx.one("SELECT * FROM fiscal_periods WHERE id=?", (period_id,))
            if not period:
                raise KeyError("Period not found")
            if period["status"] == "Locked":
                raise ValueError("The fiscal period is already locked")
            tx.execute(
                "UPDATE fiscal_periods SET status='Locked',locked_at=?,locked_by=?,lock_reason=? WHERE id=?",
                (utc_now(), actor, reason.strip(), period_id),
            )
            audit(tx, period["organisation_id"], actor, "period.locked", "fiscal_period", period_id,
                  {"reason": reason.strip()})

    def unlock_period(self, period_id: str, *, actor: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("A reopen reason is required")
        with self.db.transaction() as tx:
            period = tx.one("SELECT * FROM fiscal_periods WHERE id=?", (period_id,))
            if not period:
                raise KeyError("Period not found")
            if period["status"] != "Locked":
                raise ValueError("The fiscal period is not locked")
            tx.execute(
                "UPDATE fiscal_periods SET status='Open',locked_at=NULL,locked_by=NULL,lock_reason=NULL WHERE id=?",
                (period_id,),
            )
            audit(tx, period["organisation_id"], actor, "period.reopened", "fiscal_period", period_id,
                  {"reason": reason.strip(), "locked_at": period["locked_at"],
                   "locked_by": period["locked_by"]})

    def list_periods(self, organisation_id: str) -> list[dict]:
        return self.db.rows(
            "SELECT id,code,starts_on,ends_on,status,locked_at,locked_by,lock_reason "
            "FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on",
            (organisation_id,),
        )

    def _object_filter(self, organisation_id, object_id):
        if not object_id:
            return '', ()
        with self.db.transaction() as tx:
            ObjectRepository(tx, organisation_id).get(object_id)
        fields = DIMENSIONS
        predicate = ' OR '.join(f'd.{key}=?' for key in fields)
        return (' AND EXISTS (SELECT 1 FROM gl_entry_objects d WHERE d.organisation_id=g.organisation_id '
                'AND d.line_id=g.id AND (' + predicate + ')) ', tuple(object_id for _ in fields))

    def trial_balance(self, organisation_id: str, *, start: str, end: str, object_id: str | None = None) -> list[dict]:
        condition, params = self._object_filter(organisation_id, object_id)
        rows = self.db.rows(
            "SELECT a.code,a.name,a.account_type,COALESCE(SUM(g.debit),0) debit,COALESCE(SUM(g.credit),0) credit "
            "FROM accounts a LEFT JOIN gl_entries g ON g.account_id=a.id AND g.entry_date BETWEEN ? AND ? "
            "AND g.organisation_id=a.organisation_id " + condition +
            "AND EXISTS (SELECT 1 FROM posting_batches p WHERE p.id=g.posting_batch_id "
            "AND p.organisation_id=g.organisation_id AND p.status IN ('Posted','Reversed')) "
            "WHERE a.organisation_id=? GROUP BY a.id,a.code,a.name,a.account_type ORDER BY a.code",
            (start, end, *params, organisation_id),
        )
        for row in rows:
            row["debit"] = money(row["debit"])
            row["credit"] = money(row["credit"])
            row["balance"] = money(row["debit"] - row["credit"])
        return rows

    def profit_and_loss(self, organisation_id: str, *, start: str, end: str, compare: str = "none", object_id: str | None = None) -> dict:
        if compare != "none":
            start, end, before_start, before_end = comparison_periods(start, end, compare)
            return _add_comparison(
                self.profit_and_loss(organisation_id, start=start, end=end, object_id=object_id),
                self.profit_and_loss(organisation_id, start=before_start, end=before_end, object_id=object_id), compare)
        rows = [r for r in self.trial_balance(organisation_id, start=start, end=end, object_id=object_id)
                if r["account_type"] in {"Income", "Expense"}]
        income = sum((-r["balance"] for r in rows if r["account_type"] == "Income"), Decimal("0"))
        expenses = sum((r["balance"] for r in rows if r["account_type"] == "Expense"), Decimal("0"))
        return {"start": start, "end": end, "income": money(income),
                "expenses": money(expenses), "profit": money(income - expenses), "accounts": rows}

    def balance_sheet(self, organisation_id: str, *, as_at: str, compare: str = "none",
                      start: str | None = None) -> dict:
        if compare != "none":
            start = start or as_at[:7] + "-01"
            current_start, current_end, before_start, before_end = comparison_periods(start, as_at, compare)
            result = _add_comparison(self.balance_sheet(organisation_id, as_at=current_end),
                                    self.balance_sheet(organisation_id, as_at=before_end), compare)
            result["comparison_period"] = {"start": current_start, "end": current_end,
                                           "comparative_start": before_start, "comparative_end": before_end}
            return result
        rows = [r for r in self.trial_balance(organisation_id, start="0001-01-01", end=as_at)
                if r["account_type"] in {"Asset", "Liability", "Equity"}]
        assets = sum((r["balance"] for r in rows if r["account_type"] == "Asset"), Decimal("0"))
        liabilities = sum((-r["balance"] for r in rows if r["account_type"] == "Liability"), Decimal("0"))
        equity = sum((-r["balance"] for r in rows if r["account_type"] == "Equity"), Decimal("0"))
        current_earnings = self.profit_and_loss(organisation_id, start="0001-01-01", end=as_at)["profit"]
        return {"as_at": as_at, "assets": money(assets), "liabilities": money(liabilities),
                "equity": money(equity), "current_earnings": money(current_earnings),
                "liabilities_and_equity": money(liabilities + equity + current_earnings), "accounts": rows}

    def general_ledger(self, organisation_id: str, *, start: str, end: str, object_id: str | None = None) -> list[dict]:
        condition, params = self._object_filter(organisation_id, object_id)
        return self.db.rows(
            "SELECT g.id,g.entry_date,a.code account_code,a.name account_name,g.debit,g.credit,g.currency,"
            "g.memo,p.voucher_type,p.voucher_code,p.status,c.name contact_name,"
            "d.projects_project_id,d.projects_location_id,d.projects_person_id,d.projects_object_id "
            "FROM gl_entries g JOIN accounts a ON a.id=g.account_id "
            "JOIN posting_batches p ON p.id=g.posting_batch_id LEFT JOIN contacts c ON c.id=g.contact_id "
            "LEFT JOIN gl_entry_objects d ON d.organisation_id=g.organisation_id AND d.line_id=g.id "
            "WHERE g.organisation_id=? AND g.entry_date BETWEEN ? AND ? AND p.status IN ('Posted','Reversed') "
            + condition +
            "ORDER BY g.entry_date,p.created_at,g.line_number",
            (organisation_id, start, end, *params),
        )

    def receivables_aging(self, organisation_id: str, *, as_at: str) -> dict:
        return self._aging(organisation_id, as_at=as_at, document="invoice")

    def payables_aging(self, organisation_id: str, *, as_at: str) -> dict:
        return self._aging(organisation_id, as_at=as_at, document="bill")

    def _aging(self, organisation_id: str, *, as_at: str, document: str) -> dict:
        if document == "invoice":
            query = (
                "SELECT i.id,i.number,c.name contact_name,i.issue_date document_date,i.due_date,i.currency,"
                "i.total-i.paid_total outstanding FROM invoices i JOIN contacts c ON c.id=i.contact_id "
                "WHERE i.organisation_id=? AND i.status IN ('Issued','Part Paid') AND i.issue_date<=?"
            )
        else:
            query = (
                "SELECT b.id,b.supplier_number number,c.name contact_name,b.bill_date document_date,b.due_date,b.currency,"
                "b.total-b.paid_total outstanding FROM bills b JOIN contacts c ON c.id=b.contact_id "
                "WHERE b.organisation_id=? AND b.status IN ('Approved','Part Paid') AND b.bill_date<=?"
            )
        from datetime import date
        items, buckets = self.db.rows(query, (organisation_id, as_at)), {
            "current": Decimal("0"), "1_30": Decimal("0"), "31_60": Decimal("0"),
            "61_90": Decimal("0"), "over_90": Decimal("0"),
        }
        at = date.fromisoformat(as_at)
        for item in items:
            days = (at - date.fromisoformat(item["due_date"])).days
            bucket = "current" if days <= 0 else "1_30" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 else "over_90"
            item["days_overdue"] = max(days, 0)
            item["bucket"] = bucket
            item["outstanding"] = money(item["outstanding"])
            buckets[bucket] += item["outstanding"]
        return {"as_at": as_at, "buckets": {key: money(value) for key, value in buckets.items()},
                "total": money(sum(buckets.values(), Decimal("0"))), "items": items}

    def cash_summary(self, organisation_id: str, *, start: str, end: str) -> dict:
        rows = self.db.rows(
            "SELECT a.code,a.name,COALESCE(SUM(g.debit-g.credit),0) movement "
            "FROM bank_accounts b JOIN accounts a ON a.id=b.ledger_account_id "
            "LEFT JOIN gl_entries g ON g.account_id=a.id AND g.entry_date BETWEEN ? AND ? "
            "AND EXISTS (SELECT 1 FROM posting_batches p WHERE p.id=g.posting_batch_id AND p.status IN ('Posted','Reversed')) "
            "WHERE b.organisation_id=? GROUP BY a.id,a.code,a.name ORDER BY a.code",
            (start, end, organisation_id),
        )
        for row in rows:
            row["movement"] = money(row["movement"])
        return {"start": start, "end": end,
                "net_cash_movement": money(sum((r["movement"] for r in rows), Decimal("0"))),
                "accounts": rows}
