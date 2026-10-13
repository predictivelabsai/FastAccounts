"""Bulk VAT replacement for draft invoice and bill lines.

Tax codes change (a rate rises, a recovery ratio narrows); drafts that were
created under the old code are still unposted. This service rewrites their
lines and header totals in one audited, organisation-locked transaction.
Posted documents stay immutable by design: previews report them as skipped so
an accountant can reverse-and-rebook deliberately instead.

Recomputation keeps the amount basis: exclusive lines keep their net and
recompute tax and gross; inclusive sales lines keep the gross and recompute
the net/tax split. Bills are always exclusive. Supplier-declared VAT cents on
draft bills are replaced on purpose (the preview states this), and replaced
bill lines obtain the target code's recoverable percentage.
"""
from __future__ import annotations

from decimal import Decimal

from core_utils import audit, db_number, decimal, money, utc_now
from database import get_database


def _line_amounts(raw: Decimal, rate: Decimal, amount_type: str) -> dict:
    """Recompute one line under the target code, keeping the amount basis."""
    if amount_type == "inclusive" and rate:
        gross = money(raw)
        net = money(gross / (Decimal("1") + rate / Decimal("100")))
        tax = money(gross - net)
    else:
        net = money(raw)
        tax = money(net * rate / Decimal("100"))
        gross = money(net + tax)
    return {"net_amount": net, "tax_amount": tax, "gross_amount": gross}


HEADERS = {
    "invoice": ("invoices", "invoice_lines", "invoice_id", "number"),
    "bill": ("bills", "bill_lines", "bill_id", "supplier_number"),
}


class TaxReplacementService:
    def __init__(self, db=None):
        self.db = db or get_database()

    # API ------------------------------------------------------------------

    def preview(self, organisation_id, from_code_id, to_code_id):
        source, target = self._codes(organisation_id, from_code_id, to_code_id)
        return {
            "source_code": {"id": source["id"], "code": source["code"],
                            "name": source["name"], "rate": str(source["rate"])},
            "target_code": {"id": target["id"], "code": target["code"],
                            "name": target["name"], "rate": str(target["rate"])},
            "documents": self._candidates(organisation_id, source, target),
            "skipped_posted": self._skipped_posted(organisation_id, source["id"]),
        }

    def apply(self, organisation_id, from_code_id, to_code_id, *, actor):
        source, target = self._codes(organisation_id, from_code_id, to_code_id)
        candidates = self._candidates(organisation_id, source, target)
        if not candidates:
            raise ValueError("No draft documents use the source tax code")
        summary = {"replaced_documents": len(candidates), "replaced_lines": 0,
                   "source_code": source["code"], "target_code": target["code"],
                   "skipped_posted": self._skipped_posted(organisation_id, source["id"])}
        with self.db.transaction() as tx:
            locked = tx.execute(
                "UPDATE organisations SET name=name WHERE id=?", (organisation_id,))
            if not locked.rowcount:
                raise KeyError("Organisation not found")
            for candidate in candidates:
                self._rewrite(tx, organisation_id, candidate, source, target, summary)
                audit(tx, organisation_id, actor, "tax.replaced",
                      "invoice" if candidate["kind"] == "invoice" else "bill",
                      candidate["id"],
                      {"source_code": source["code"], "target_code": target["code"],
                       "old_tax_total": candidate["old_tax_total"],
                       "new_tax_total": candidate["new_tax_total"],
                       "affected_lines": candidate["affected_lines"]})
        return summary

    # internals ------------------------------------------------------------

    def _codes(self, organisation_id, from_code_id, to_code_id):
        if not from_code_id or from_code_id == to_code_id:
            raise ValueError("The replacement tax code must differ from the source")
        source = self.db.one(
            "SELECT * FROM tax_codes WHERE id=? AND organisation_id=?",
            (from_code_id, organisation_id))
        target = self.db.one(
            "SELECT * FROM tax_codes WHERE id=? AND organisation_id=?",
            (to_code_id, organisation_id))
        if not source:
            raise KeyError("Source tax code not found")
        if not target:
            raise KeyError("Target tax code not found")
        if not target["active"]:
            raise ValueError("The replacement tax code must be active")
        return source, target

    def _candidates(self, organisation_id, source, target):
        """Draft documents with affected lines and their recomputed tax totals."""
        rows = []
        for kind, (header, line_table, id_column, label) in HEADERS.items():
            from_column = "invoice_id" if kind == "invoice" else "bill_id"
            for document in self.db.rows(
                    f"SELECT * FROM {header} WHERE organisation_id=? AND status='Draft' "
                    f"AND id IN (SELECT {from_column} FROM {line_table} WHERE tax_code_id=?) "
                    f"ORDER BY {label}", (organisation_id, source["id"])):
                affected_lines, old_tax_total, new_tax_total = self._recalculate(
                    organisation_id, document, kind, source, target)
                rows.append({
                    "kind": kind, "id": document["id"], "label": str(document[label] or ""),
                    "currency": document["currency"], "total_lines": len(self._lines(organisation_id, kind, document["id"])),
                    "affected_lines": len(affected_lines),
                    "old_tax_total": str(old_tax_total), "new_tax_total": str(new_tax_total),
                    "delta": str(money(new_tax_total - old_tax_total)),
                })
        return rows

    def _lines(self, organisation_id, kind, document_id):
        header, line_table, id_column, _ = HEADERS[kind]
        return self.db.rows(
            f"SELECT l.* FROM {line_table} l JOIN {header} h ON h.id=l.{id_column} "
            f"WHERE l.{id_column}=? AND h.organisation_id=? ORDER BY l.line_number",
            (document_id, organisation_id))

    def _skipped_posted(self, organisation_id, from_code_id):
        counts = {}
        for kind, (header, line_table, id_column, _) in HEADERS.items():
            counts[kind] = int(self.db.scalar(
                f"SELECT COUNT(*) FROM {header} h WHERE h.organisation_id=? AND "
                f"h.status NOT IN ('Draft','Voided') AND h.id IN "
                f"(SELECT {id_column} FROM {line_table} WHERE tax_code_id=?)",
                (organisation_id, from_code_id)) or 0)
        return counts

    def _recalculate(self, organisation_id, document, kind, source, target):
        """Return affected line ids and old/new whole-document tax totals."""
        rate = decimal(target["rate"])
        amount_type = (document.get("line_amount_type") or "exclusive") if kind == "invoice" else "exclusive"
        affected, tax_total = [], Decimal("0")
        for line in self._lines(organisation_id, kind, document["id"]):
            belongs = str(line["tax_code_id"] or "") == str(source["id"])
            if belongs:
                affected.append(line["id"])
                tax_total += _line_amounts(
                    decimal(line["quantity"]) * decimal(line["unit_price"]),
                    rate, amount_type)["tax_amount"]
            else:
                tax_total += decimal(line["tax_amount"])
        old_tax_total = sum((decimal(line["tax_amount"])
                             for line in self._lines(organisation_id, kind, document["id"])),
                            Decimal("0"))
        return affected, money(old_tax_total), money(tax_total)

    def _rewrite(self, tx, organisation_id, candidate, source, target, summary):
        header, line_table, id_column, _ = HEADERS[candidate["kind"]]
        rate = decimal(target["rate"])
        recoverable = decimal(target["recoverable_percent"] or 100)
        row = tx.one(f"SELECT * FROM {header} WHERE id=? AND organisation_id=?",
                     (candidate["id"], organisation_id))
        if not row or row["status"] != "Draft":
            raise KeyError("Draft document not found")
        amount_type = (row.get("line_amount_type") or "exclusive") if candidate["kind"] == "invoice" else "exclusive"
        subtotal, tax_total = Decimal("0"), Decimal("0")
        for line in tx.rows(
                f"SELECT * FROM {line_table} WHERE {id_column}=? ORDER BY line_number",
                (candidate["id"],)):
            affects = str(line["tax_code_id"] or "") == str(source["id"])
            if affects:
                amounts = _line_amounts(
                    decimal(line["quantity"]) * decimal(line["unit_price"]), rate, amount_type)
                if candidate["kind"] == "bill":
                    recoverable_tax = money(amounts["tax_amount"] * recoverable / Decimal("100"))
                    tx.execute(
                        f"UPDATE {line_table} SET tax_code_id=?,tax_rate=?,net_amount=?,"
                        "tax_amount=?,recoverable_tax=?,gross_amount=? WHERE id=?",
                        (target["id"], db_number(rate), db_number(amounts["net_amount"]),
                         db_number(amounts["tax_amount"]), db_number(recoverable_tax),
                         db_number(amounts["gross_amount"]), line["id"]))
                else:
                    tx.execute(
                        f"UPDATE {line_table} SET tax_code_id=?,tax_rate=?,net_amount=?,"
                        "tax_amount=?,gross_amount=? WHERE id=?",
                        (target["id"], db_number(rate), db_number(amounts["net_amount"]),
                         db_number(amounts["tax_amount"]),
                         db_number(amounts["gross_amount"]), line["id"]))
                summary["replaced_lines"] += 1
            else:
                amounts = {"net_amount": decimal(line["net_amount"]),
                           "tax_amount": decimal(line["tax_amount"])}
            subtotal += amounts["net_amount"]
            tax_total += amounts["tax_amount"]
        tx.execute(
            f"UPDATE {header} SET subtotal=?,tax_total=?,total=?,updated_at=? WHERE id=?",
            (db_number(money(subtotal)), db_number(money(tax_total)),
             db_number(money(subtotal + tax_total)), utc_now(), candidate["id"]))