"""Tenant-scoped selection for document lists and their exports."""
from __future__ import annotations

from datetime import date


class InvoiceListRepository:
    def __init__(self, db):
        self.db = db

    def list(self, organisation_id: str, kind: str, *, status=None, contact_id=None,
             date_from=None, date_to=None, currency=None, q=None) -> list[dict]:
        if kind not in {"invoices", "bills"}:
            raise ValueError("Unknown document kind")
        day = "issue_date" if kind == "invoices" else "bill_date"
        number = "number" if kind == "invoices" else "supplier_number"
        clauses, params = ["d.organisation_id=?"], [organisation_id]
        if kind == "invoices" and status == "Overdue":
            clauses.extend(["d.status IN ('Issued','Part Paid')", "d.due_date<?"])
            params.append(date.today().isoformat())
            status = None
        for field, value in (("status", status), ("contact_id", contact_id), ("currency", currency)):
            if value is not None:
                clauses.append(f"d.{field}=?")
                params.append(value)
        for operator, value in ((">=", date_from), ("<=", date_to)):
            if value is not None:
                clauses.append(f"d.{day}{operator}?")
                params.append(value)
        if q:
            # Treat search characters literally, including SQL LIKE wildcards.
            pattern = "%" + q.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
            clauses.append(f"(LOWER(d.{number}) LIKE LOWER(?) ESCAPE '!' OR "
                           "LOWER(d.reference) LIKE LOWER(?) ESCAPE '!' OR LOWER(c.name) LIKE LOWER(?) ESCAPE '!')")
            params.extend([pattern] * 3)
        return self.db.rows(
            f"SELECT d.*,c.name contact_name FROM {kind} d JOIN contacts c "
            "ON c.id=d.contact_id AND c.organisation_id=d.organisation_id "
            "WHERE " + " AND ".join(clauses) + f" ORDER BY d.{day} DESC,d.created_at DESC,d.id DESC",
            tuple(params),
        )
