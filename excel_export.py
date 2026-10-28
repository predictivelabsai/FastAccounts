"""Pure in-process Excel renderers for accounting report workbooks.

Domain calculations remain Decimal-based. Excel numeric cells are deliberately
written as ``float(Decimal)`` because Excel stores numbers as IEEE-754 doubles;
the exported EUR values are already rounded to two decimals and remain suitable
for native spreadsheet totals, filters and formatting.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font


MONEY_FORMAT = "#,##0.00"


def _book(organisation: dict, title: str) -> Workbook:
    workbook = Workbook()
    workbook.properties.title = title
    workbook.properties.subject = str((organisation or {}).get("name") or "")
    workbook.properties.creator = "FastAccounts"
    return workbook


def _header_row(ws, headers) -> None:
    ws.append(list(headers))
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)


def _put(ws, row: int, col: int, value) -> None:
    cell = ws.cell(row=row, column=col)
    if value is None:
        cell.value = ""
    elif isinstance(value, Decimal):
        cell.value = float(value)
        cell.number_format = MONEY_FORMAT
    elif isinstance(value, (date, datetime)):
        cell.value = value.isoformat()
    else:
        cell.value = value


def _from_decimal(value) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _finish(workbook: Workbook) -> bytes:
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _total_row(ws, label_column: int, money_columns: tuple[int, ...], totals: dict[int, Decimal]) -> None:
    row = ws.max_row + 1
    _put(ws, row, label_column, "Total")
    ws.cell(row=row, column=label_column).font = Font(bold=True)
    for column in money_columns:
        _put(ws, row, column, totals[column])
        ws.cell(row=row, column=column).font = Font(bold=True)


def pay_run_workbook(organisation: dict, run: dict, items: list[dict],
                     journal_lines: list[dict] | None = None) -> bytes:
    workbook = _book(organisation, "Payroll pay run")
    summary = workbook.active
    summary.title = "Summary"
    for label, value in (
        ("Organisation", (organisation or {}).get("name")),
        ("Run ID", (run or {}).get("id")),
        ("Period", (run or {}).get("period")),
        ("Status", (run or {}).get("status")),
    ):
        summary.append([label, "" if value is None else value])
        summary.cell(row=summary.max_row, column=1).font = Font(bold=True)
    summary.append([])
    _header_row(summary, ("Metric", "Run total", "Item sum"))
    for label, run_key, item_key in (
        ("Gross", "total_gross", "gross"),
        ("Net", "total_net", "net"),
        ("Employer cost", "total_employer_cost", "employer_cost"),
    ):
        row = summary.max_row + 1
        _put(summary, row, 1, label)
        _put(summary, row, 2, _from_decimal((run or {}).get(run_key)))
        _put(summary, row, 3, sum((_from_decimal(item.get(item_key)) for item in items), Decimal("0")))

    item_sheet = workbook.create_sheet("Items")
    item_headers = (
        "Name", "Personal ID", "Pay basis", "Gross", "Funded pension",
        "Employee unemployment insurance", "Income tax", "Social tax",
        "Employer unemployment insurance", "Net", "Employer cost",
    )
    _header_row(item_sheet, item_headers)
    item_money = {
        4: "gross", 5: "funded_pension", 6: "ui_employee", 7: "income_tax",
        8: "social_tax", 9: "ui_employer", 10: "net", 11: "employer_cost",
    }
    item_totals = {column: Decimal("0") for column in item_money}
    for item in items:
        row = item_sheet.max_row + 1
        _put(item_sheet, row, 1, item.get("employee_name") or item.get("name"))
        _put(item_sheet, row, 2, item.get("personal_id"))
        _put(item_sheet, row, 3, item.get("pay_basis"))
        for column, key in item_money.items():
            amount = _from_decimal(item.get(key))
            _put(item_sheet, row, column, amount)
            item_totals[column] += amount
    _total_row(item_sheet, 1, tuple(item_money), item_totals)

    if any(item.get('components') for item in items):
        from web import i18n
        from payroll_components import FLAGS, FLAG_LABELS
        language = 'et' if organisation.get('country_code') == 'EE' else 'en'
        def label(key):
            return i18n.catalog(language)['workspace'].get(key, key)
        components = workbook.create_sheet(label('Payment components')[:31])
        _header_row(components, [label(key) for key in ('Employee', 'Payment type', 'Direction', 'Amount', *FLAG_LABELS)])
        for item in items:
            for line in item.get('components', []):
                row = components.max_row + 1
                values = [item['employee_name'], label(line['name']), label('Income' if line['direction'] == 'income' else 'Deduction'),
                          _from_decimal(line['amount']), *(label('Yes' if line[key] else 'No') for key in FLAGS)]
                for column, value in enumerate(values, 1):
                    _put(components, row, column, value)
                    if isinstance(value, str):
                        components.cell(row, column).data_type = 's'

    if journal_lines is not None:
        accounting = workbook.create_sheet("Accounting")
        _header_row(accounting, ("Account code", "Account name", "Memo", "Debit", "Credit"))
        accounting_totals = {4: Decimal("0"), 5: Decimal("0")}
        for line in journal_lines:
            row = accounting.max_row + 1
            _put(accounting, row, 1, line.get("account_code"))
            _put(accounting, row, 2, line.get("account_name"))
            _put(accounting, row, 3, line.get("memo"))
            for column, key in ((4, "debit"), (5, "credit")):
                amount = _from_decimal(line.get(key))
                _put(accounting, row, column, amount)
                accounting_totals[column] += amount
        _total_row(accounting, 1, (4, 5), accounting_totals)
    return _finish(workbook)


def general_ledger_workbook(organisation: dict, entries: list[dict]) -> bytes:
    workbook = _book(organisation, "General ledger")
    sheet = workbook.active
    sheet.title = "General Ledger"
    _header_row(sheet, (
        "Entry date", "Voucher code", "Voucher type", "Account code",
        "Account name", "Memo", "Debit", "Credit",
    ))
    totals = {7: Decimal("0"), 8: Decimal("0")}
    for entry in entries:
        row = sheet.max_row + 1
        for column, key in enumerate((
            "entry_date", "voucher_code", "voucher_type", "account_code", "account_name", "memo",
        ), 1):
            _put(sheet, row, column, entry.get(key))
        for column, key in ((7, "debit"), (8, "credit")):
            amount = _from_decimal(entry.get(key))
            _put(sheet, row, column, amount)
            totals[column] += amount
    _total_row(sheet, 1, (7, 8), totals)
    return _finish(workbook)


def invoices_workbook(organisation: dict, invoices: list[dict]) -> bytes:
    workbook = _book(organisation, "Invoices")
    sheet = workbook.active
    sheet.title = "Invoices"
    _header_row(sheet, (
        "Number", "Contact name", "Issue date", "Due date", "Currency",
        "Net", "VAT", "Gross", "Status",
    ))
    totals = {6: Decimal("0"), 7: Decimal("0"), 8: Decimal("0")}
    for invoice in invoices:
        row = sheet.max_row + 1
        for column, key in enumerate(("number", "contact_name", "issue_date", "due_date", "currency"), 1):
            _put(sheet, row, column, invoice.get(key))
        for column, key in ((6, "subtotal"), (7, "tax_total"), (8, "total")):
            amount = _from_decimal(invoice.get(key))
            _put(sheet, row, column, amount)
            totals[column] += amount
        _put(sheet, row, 9, invoice.get("status"))
    _total_row(sheet, 1, (6, 7, 8), totals)
    return _finish(workbook)


def employees_workbook(organisation: dict, employees: list[dict]) -> bytes:
    workbook = _book(organisation, "Employees")
    sheet = workbook.active
    sheet.title = "Employees"
    _header_row(sheet, (
        "Name", "Personal ID", "Email", "Country code", "Pay basis", "Gross salary",
        "Hourly rate", "Funded pension percent", "FTE", "Employment start date",
        "Employment end date", "Phone", "IBAN", "Bank account owner", "Address", "Date of birth",
    ))
    for employee in employees:
        row = sheet.max_row + 1
        values = (
            employee.get("name"), employee.get("personal_id"), employee.get("email"),
            employee.get("country_code") or (organisation or {}).get("country_code"),
            employee.get("pay_basis"), _from_decimal(employee.get("gross_salary")),
            _from_decimal(employee.get("hourly_rate")),
            _from_decimal(employee.get("funded_pension_percent")), _from_decimal(employee.get("fte")),
            employee.get("employment_start_date"), employee.get("employment_end_date"),
            employee.get("phone"), employee.get("iban"), employee.get("bank_account_owner"),
            employee.get("address"), employee.get("date_of_birth"),
        )
        for column, value in enumerate(values, 1):
            _put(sheet, row, column, value)
    return _finish(workbook)


def vat_returns_workbook(organisation: dict, returns_: list[dict]) -> bytes:
    workbook = _book(organisation, "VAT returns")
    sheet = workbook.active
    sheet.title = "VAT Returns"
    fields = (
        "id", "organisation_id", "country_code", "period_start", "period_end", "basis",
        "status", "boxes_json", "reviewed_by", "reviewed_at", "submission_reference", "created_at",
    )
    _header_row(sheet, fields)
    for return_ in returns_:
        row = sheet.max_row + 1
        for column, field in enumerate(fields, 1):
            value = return_.get(field)
            if field == "boxes_json" and isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            _put(sheet, row, column, value)
    return _finish(workbook)


DOCUMENT_LIST_HEADERS = (
    "Number", "Reference", "Contact name", "Date", "Due date", "Currency",
    "Net", "VAT", "Gross", "Paid", "Status",
)


def document_list_values(document: dict, kind: str) -> tuple:
    sales = kind == "invoices"
    return (
        document.get("number" if sales else "supplier_number") or "",
        document.get("reference") or "", document.get("contact_name") or "",
        document.get("issue_date" if sales else "bill_date"), document.get("due_date"),
        document.get("currency"),
        *(_from_decimal(document.get(key)).quantize(Decimal("0.01"))
          for key in ("subtotal", "tax_total", "total", "paid_total")),
        document.get("status"),
    )


def document_list_workbook(organisation: dict, documents: list[dict], kind: str) -> bytes:
    title = "Invoices" if kind == "invoices" else "Bills"
    workbook = _book(organisation, title)
    sheet = workbook.active
    sheet.title = title
    _header_row(sheet, DOCUMENT_LIST_HEADERS)
    for document in documents:
        row = sheet.max_row + 1
        for column, value in enumerate(document_list_values(document, kind), 1):
            _put(sheet, row, column, value)
            if isinstance(value, str):
                sheet.cell(row=row, column=column).data_type = "s"
    # Currency is retained on each row; mixed currencies are never summed.
    return _finish(workbook)
