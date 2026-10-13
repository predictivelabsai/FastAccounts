"""Read-only invoice and bill lists with CSV and Excel rendering."""
from __future__ import annotations

import csv
from datetime import date
from io import StringIO

from database import get_database
from excel_export import document_list_workbook, document_list_values, DOCUMENT_LIST_HEADERS
from invoice_list_repository import InvoiceListRepository


def validate_list_dates(date_from=None, date_to=None):
    for value in (date_from, date_to):
        if value is not None:
            try:
                parsed = date.fromisoformat(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("Document dates must use YYYY-MM-DD format") from exc
            if parsed.isoformat() != value:
                raise ValueError("Document dates must use YYYY-MM-DD format")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ValueError("Document date_from cannot be after date_to")


def _csv_text(value):
    # Preserve user text while preventing spreadsheet formula execution.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


class InvoiceListService:
    def __init__(self, db=None):
        self.db = db or get_database()

    def list(self, organisation_id, kind, **filters):
        validate_list_dates(filters.get("date_from"), filters.get("date_to"))
        return InvoiceListRepository(self.db).list(organisation_id, kind, **filters)

    def export(self, organisation_id, kind, format_, **filters):
        rows = self.list(organisation_id, kind, **filters)
        if format_ == "xlsx":
            organisation = self.db.one("SELECT * FROM organisations WHERE id=?", (organisation_id,))
            return document_list_workbook(organisation, rows, kind)
        if format_ != "csv":
            raise ValueError("Unknown document export format")
        output = StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(DOCUMENT_LIST_HEADERS)
        for row in rows:
            writer.writerow([_csv_text(value) for value in document_list_values(row, kind)])
        return output.getvalue().encode("utf-8-sig")
