"""Read-only direct-method cash flows in the organisation's base currency."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from core_utils import decimal, money
from database import Database, get_database


BUCKETS = ("receipts", "supplier_payments", "payroll", "vat", "revenue",
           "expenses", "financing", "internal", "other")


def _allocate(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Allocate cents deterministically, with the residual on the last share."""
    remaining, total = amount, sum(weights, Decimal("0"))
    shares = []
    for weight in weights:
        share = min(remaining, money(remaining * weight / total)) if total else Decimal("0")
        shares.append(share)
        remaining -= share
        total -= weight
    return shares


def _bucket(entry: dict) -> str:
    role = entry["system_role"] or ""
    if role == "AR":
        return "receipts"
    if role == "AP":
        return "supplier_payments"
    if role.startswith("PAYROLL_"):
        return "payroll"
    if role in {"OUTPUT_VAT", "INPUT_VAT"}:
        return "vat"
    if role in {"CAPITAL", "RETAINED_EARNINGS"}:
        return "financing"
    return {"Income": "revenue", "Expense": "expenses"}.get(entry["account_type"], "other")


class CashFlowService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    def statement(self, organisation_id: str, *, date_from: str, date_to: str) -> dict:
        try:
            start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        except (TypeError, ValueError):
            raise ValueError("Statement dates must be ISO dates") from None
        if start > end:
            raise ValueError("Statement start must be on or before its end")
        with self.db.transaction() as tx:
            organisation = tx.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
            if not organisation:
                raise KeyError("Organisation not found")
            accounts = tx.rows("SELECT id,code,name FROM accounts WHERE organisation_id=? "
                               "AND system_role='BANK' ORDER BY code", (organisation_id,))
            entries = tx.rows(
                "SELECT g.*,a.system_role,a.account_type,p.voucher_code,p.voucher_type "
                "FROM gl_entries g JOIN accounts a ON a.id=g.account_id "
                "AND a.organisation_id=g.organisation_id "
                "JOIN posting_batches p ON p.id=g.posting_batch_id AND p.organisation_id=g.organisation_id "
                "WHERE g.organisation_id=? AND g.entry_date<=? AND p.status IN ('Posted','Reversed') "
                "ORDER BY g.entry_date,p.created_at,p.id,g.line_number,g.id",
                (organisation_id, end.isoformat()))
        details = {a["id"]: {**a, "opening_balance": Decimal("0"),
                   "closing_balance": Decimal("0"), "movements": []} for a in accounts}
        batches = defaultdict(list)
        buckets = {key: {"inflows": Decimal("0"), "outflows": Decimal("0")} for key in BUCKETS}
        for entry in entries:
            if entry["account_id"] in details:
                amount = money(decimal(entry["debit"]) - decimal(entry["credit"]))
                account = details[entry["account_id"]]
                account["closing_balance"] += amount
                if entry["entry_date"] < start.isoformat():
                    account["opening_balance"] += amount
            if entry["entry_date"] >= start.isoformat():
                batches[entry["posting_batch_id"]].append(entry)
        for lines in batches.values():
            liquid = [line for line in lines if line["account_id"] in details]
            sides = [[line for line in liquid if decimal(line[side]) > 0] for side in ("debit", "credit")]
            totals = [sum((money(line[side]) for line in subset), Decimal("0"))
                      for side, subset in zip(("debit", "credit"), sides)]
            internal = min(totals)
            # Journal lines do not encode pairwise contra links. Match liquid
            # sides first, then distribute external cash over opposite contra
            # amounts. This deterministic convention also handles mixed batches.
            for side, subset, direction in zip(("debit", "credit"), sides, ("inflows", "outflows")):
                transfers = _allocate(internal, [money(line[side]) for line in subset])
                contra_side = "credit" if side == "debit" else "debit"
                contra = [line for line in lines if line["account_id"] not in details
                          and decimal(line[contra_side]) > 0]
                weights = [money(line[contra_side]) for line in contra]
                for line, transfer in zip(subset, transfers):
                    amount = money(line[side])
                    allocations = {"internal": transfer} if transfer else {}
                    external = amount - transfer
                    if contra:
                        for other, share in zip(contra, _allocate(external, weights)):
                            key = _bucket(other)
                            allocations[key] = allocations.get(key, Decimal("0")) + share
                    elif external:
                        allocations["other"] = external
                    allocations = {key: money(value) for key, value in allocations.items() if value}
                    for key, value in allocations.items():
                        buckets[key][direction] += value
                    details[line["account_id"]]["movements"].append({
                        "entry_id": line["id"], "posting_batch_id": line["posting_batch_id"],
                        "date": line["entry_date"], "document_number": line["voucher_code"],
                        "memo": line["memo"], "contact_id": line["contact_id"],
                        "amount": amount if side == "debit" else -amount,
                        "direction": direction, "allocations": allocations})
        for values in buckets.values():
            values["net"] = money(values["inflows"] - values["outflows"])
            values["inflows"] = money(values["inflows"])
            values["outflows"] = money(values["outflows"])
        for account in details.values():
            account["opening_balance"] = money(account["opening_balance"])
            account["closing_balance"] = money(account["closing_balance"])
        return {"organisation_id": organisation_id, "date_from": start.isoformat(), "date_to": end.isoformat(),
                "base_currency": organisation["base_currency"],
                "opening_balance": money(sum((a["opening_balance"] for a in details.values()), Decimal("0"))),
                "closing_balance": money(sum((a["closing_balance"] for a in details.values()), Decimal("0"))),
                "inflows": money(sum((v["inflows"] for k, v in buckets.items() if k != "internal"), Decimal("0"))),
                "outflows": money(sum((v["outflows"] for k, v in buckets.items() if k != "internal"), Decimal("0"))),
                "buckets": buckets, "accounts": list(details.values())}
