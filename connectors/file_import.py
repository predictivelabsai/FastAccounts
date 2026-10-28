"""Deterministic offline employee CSV/TSV and journal workbook imports."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import date, datetime
from zipfile import ZipFile, BadZipFile
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any
from openpyxl.utils.exceptions import InvalidFileException

from core_utils import money

from .base import ConnectorResult


HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "external_id": ("ID", "Employee ID", "Töötaja ID"),
    "name": ("Name", "Nimi", "Full name"),
    "email": ("Email", "E-post", "e-mail"),
    "gross_salary": ("Salary", "Base salary", "Palk", "Baaspalk", "Gross salary"),
    "personal_id": ("Personal ID", "Isikukood", "Personal code", "ID code"),
    "status": ("Status", "Staatus"),
}

_ACTIVE_STATUSES = {"", "active", "aktiivne", "tööl"}
_ALIAS_LOOKUP = {
    alias.strip().casefold(): canonical
    for canonical, aliases in HEADER_ALIASES.items()
    for alias in aliases
}


class FileImportConnector:
    """Parse uploaded employee text or journal workbook bytes offline."""

    key = "file_import"
    PULL_OBJECT_TYPES = (
        "employee", "employees", "journal", "payroll_opening_leave",
        "historical_earnings",
    )

    def __init__(self, csv_content: str | bytes, config: Mapping[str, Any] | None = None):
        self.csv_content = csv_content
        self.config = dict(config or {})

    def check(self) -> ConnectorResult:
        return ConnectorResult(
            provider=self.key,
            operation="check",
            ok=True,
            live=False,
            message="File import is ready; upload an employee CSV export to stage records.",
        )

    def pull(self, object_type: str, *, cursor: str | None = None) -> ConnectorResult:
        del cursor
        if object_type in {"payroll_opening_leave", "historical_earnings"}:
            records = tuple(parse_payroll_history_file(
                self.csv_content, object_type, self.config.get("filename", "")
            ))
            return ConnectorResult(
                self.key, f"pull:{object_type}", True, False,
                f"Parsed {len(records)} {object_type.replace('_', ' ')} records",
                records, None,
            )
        if object_type == "journal":
            records = tuple(parse_journal_workbook(self.csv_content))
            return ConnectorResult(self.key, "pull:journal", True, False,
                                   f"Parsed {len(records)} journal blocks", records, None)
        if object_type not in {"employee", "employees"}:
            raise ValueError("File import supports employees and journals only")
        records = tuple(self._parse())
        return ConnectorResult(
            provider=self.key,
            operation=f"pull:{object_type}",
            ok=True,
            live=False,
            message=f"Parsed {len(records)} employee records from the uploaded file",
            records=records,
            cursor=None,
        )

    def push(self, object_type: str, records: list[dict[str, Any]]) -> ConnectorResult:
        del records
        return ConnectorResult(
            provider=self.key,
            operation=f"push:{object_type}",
            ok=False,
            live=False,
            message="File import is an import-only connector; no records were sent.",
        )

    def _parse(self) -> list[dict[str, Any]]:
        if not isinstance(self.csv_content, str) or not self.csv_content.strip(
            "\ufeff\r\n\t "
        ):
            raise ValueError("CSV content is empty")
        content = self.csv_content.lstrip("\ufeff")
        delimiter = self._delimiter(content)
        reader = csv.reader(
            io.StringIO(content, newline=""), delimiter=delimiter, strict=True
        )
        try:
            rows = list(reader)
        except csv.Error as error:
            raise ValueError(
                f"CSV could not be parsed near row {reader.line_num}: {error}"
            ) from error
        if not rows or not any(str(value).strip() for value in rows[0]):
            raise ValueError("CSV header row is missing")

        headers = [value.strip() for value in rows[0]]
        if any(not header for header in headers):
            position = next(index + 1 for index, header in enumerate(headers) if not header)
            raise ValueError(f"CSV header {position} is empty")
        duplicate_headers = sorted(
            {header for header in headers if headers.count(header) > 1}
        )
        if duplicate_headers:
            raise ValueError(f"CSV contains duplicate header: {duplicate_headers[0]}")

        mapped: dict[int, str] = {}
        source_for_field: dict[str, str] = {}
        for index, header in enumerate(headers):
            canonical = _ALIAS_LOOKUP.get(header.casefold())
            if not canonical:
                continue
            if canonical in source_for_field:
                raise ValueError(
                    f"CSV headers '{source_for_field[canonical]}' and '{header}' "
                    f"both map to '{canonical}'"
                )
            mapped[index] = canonical
            source_for_field[canonical] = header
        if not mapped:
            raise ValueError(
                "CSV header row is missing or unrecognized: " + ", ".join(headers)
            )
        if "name" not in source_for_field:
            raise ValueError(
                "CSV header is missing required 'name' column; headers: " + ", ".join(headers)
            )

        records: list[dict[str, Any]] = []
        for row_number, values in enumerate(rows[1:], start=2):
            if not any(str(value).strip() for value in values):
                continue
            if len(values) != len(headers):
                raise ValueError(
                    f"CSV row {row_number} has {len(values)} values; expected "
                    f"{len(headers)} from the header"
                )
            records.append(self._record(headers, mapped, values, row_number))
        return records

    @staticmethod
    def _delimiter(content: str) -> str:
        sample = content[:8192]
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
        except csv.Error:
            return ","

    @staticmethod
    def _record(
        headers: list[str], mapped: dict[int, str], values: list[str], row_number: int
    ) -> dict[str, Any]:
        record: dict[str, Any] = {"active": True}
        for index, (header, raw_value) in enumerate(zip(headers, values, strict=True)):
            value = raw_value.strip()
            canonical = mapped.get(index)
            if canonical is None:
                record[f"file_{header}"] = value
            elif canonical == "status":
                record["active"] = value.casefold() in _ACTIVE_STATUSES
            elif canonical == "gross_salary":
                if value:
                    try:
                        salary = money(value)
                    except (InvalidOperation, ValueError) as error:
                        raise ValueError(
                            f"CSV row {row_number} has invalid money in header '{header}'"
                        ) from error
                    if salary != Decimal("0.00"):
                        record["gross_salary"] = salary
            elif value:
                record[canonical] = value

        name = str(record.get("name") or "").strip()
        if not name:
            name_index = next(
                index for index, field in mapped.items() if field == "name"
            )
            raise ValueError(
                f"CSV row {row_number} has no employee name in header "
                f"'{headers[name_index]}'"
            )
        record["name"] = name
        record["external_id"] = (
            str(record.get("external_id") or "").strip()
            or _stable_external_id(record)
        )
        return record


def _stable_external_id(record: Mapping[str, Any]) -> str:
    salary = record.get("gross_salary")
    identity = {
        "name": str(record.get("name") or "").strip(),
        "email": str(record.get("email") or "").strip().casefold(),
        "gross_salary": format(salary, "f") if isinstance(salary, Decimal) else "",
    }
    digest = hashlib.sha256(
        json.dumps(
            identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"file-{digest}"


_PAYROLL_HEADERS = {
    "personal_code": (
        "personal code", "personal id", "isikukood", "isikukood ehk personal code",
    ),
    "days_per_year": (
        "days per year", "annual leave entitlement", "puhkusepaevi aastas",
        "puhkusepaevade arv aastas",
    ),
    "effective_date": ("effective date", "valid from", "kehtiv alates", "joustumise kuupaev"),
    "cutover_date": ("cutover date", "balance date", "snapshot date", "saldo kuupaev"),
    "basic_unused_days": (
        "basic unused days", "unused basic leave days", "basic leave days",
        "pohipuhkuse algsaldo", "pohipuhkuse paevad",
    ),
    "extended_unused_days": (
        "extended unused days", "unused extended leave days", "extended leave days",
        "lisapuhkuse algsaldo", "lisapuhkuse paevad",
    ),
    "earning_month": ("month", "earning month", "yyyy-mm", "kuu", "tootasu kuu"),
    "wage_total": ("wage total", "gross wages", "wages", "tootasu kokku", "palga summa"),
    "unpaid_absence_days": (
        "unpaid absence calendar days", "unpaid absence days", "unpaid days",
        "tasustamata puudumise kalendripaevi", "tasustamata puudumise paevad",
    ),
}
_PAYROLL_HEADER_LOOKUP = {
    re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", alias.casefold()).encode("ascii", "ignore").decode()): field
    for field, aliases in _PAYROLL_HEADERS.items() for alias in aliases
}


def parse_payroll_history_file(content: str | bytes, object_type: str, filename: str = "") -> list[dict[str, Any]]:
    """Parse payroll opening-balance or historic-earnings CSV/XLSX rows offline."""
    if not isinstance(content, (str, bytes)):
        raise ValueError("Payroll import file must be CSV or XLSX")
    raw = content.encode("utf-8") if isinstance(content, str) else content
    if not raw or len(raw) > 2_000_000:
        raise ValueError("Payroll import file must be non-empty and under 2 MB")
    required = ({"personal_code", "days_per_year", "effective_date", "cutover_date",
                 "basic_unused_days", "extended_unused_days"}
                if object_type == "payroll_opening_leave" else
                {"personal_code", "earning_month", "wage_total", "unpaid_absence_days"})
    if object_type not in {"payroll_opening_leave", "historical_earnings"}:
        raise ValueError("Unsupported payroll history import type")
    rows: list[list[Any]]
    try:
        if raw.startswith(b"PK") or filename.casefold().endswith(".xlsx"):
            from openpyxl import load_workbook
            with ZipFile(io.BytesIO(raw)) as archive:
                if sum(item.file_size for item in archive.infolist()) > 20_000_000:
                    raise ValueError("Payroll workbook is too large when expanded")
            book = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
            try:
                sheet = book.active
                if sheet.max_row and sheet.max_row > 10000 or sheet.max_column and sheet.max_column > 200:
                    raise ValueError("Payroll workbook exceeds the row or column limit")
                rows = [[cell.value for cell in row] for row in sheet.iter_rows()]
            finally:
                book.close()
        else:
            text = raw.decode("utf-8-sig")
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=FileImportConnector._delimiter(text), strict=True)
            rows = list(reader)
    except ValueError:
        raise
    except (UnicodeDecodeError, csv.Error, BadZipFile, OSError, KeyError, InvalidFileException) as error:
        raise ValueError("Payroll import file is malformed or unsupported") from error
    if not rows or not any(value is not None and str(value).strip() for value in rows[0]):
        raise ValueError("Payroll import header row is missing")
    headers = [str(value or "").strip() for value in rows[0]]
    canonical = [_PAYROLL_HEADER_LOOKUP.get(re.sub(
        r"[^a-z0-9]", "", unicodedata.normalize("NFKD", name.casefold()).encode("ascii", "ignore").decode())) for name in headers]
    if any(not name for name in headers):
        raise ValueError("Payroll import header contains an empty column")
    if len([name for name in canonical if name]) != len(set(name for name in canonical if name)):
        raise ValueError("Payroll import contains duplicate recognised headers")
    missing = sorted(required - set(canonical))
    if missing:
        raise ValueError("Payroll import is missing required columns: " + ", ".join(missing))
    digest = hashlib.sha256(raw).hexdigest()
    records = []
    for row_number, values in enumerate(rows[1:], start=2):
        if not any(value is not None and str(value).strip() for value in values):
            continue
        identity = f"{digest}:{row_number}"
        record: dict[str, Any] = {"external_id": identity, "source_key": f"file:{identity}", "file_row": row_number}
        if len(values) != len(headers):
            record["import_error"] = f"Row {row_number} has {len(values)} values; expected {len(headers)}"
        for name, value in zip(canonical, values):
            if name and value is not None:
                record[name] = value.isoformat() if isinstance(value, (date, datetime)) else str(value).strip()
        records.append(record)
    return records


def _journal_header(value: Any) -> str | None:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = re.sub(r"[^a-z]", "", text)
    for field, aliases in {
        "account_code": {"konto", "kontokood", "kontonumber", "account", "accountcode", "accountnumber"},
        "description": {"operatsioonikirjeldus", "kirjeldus", "description", "operationdescription", "memo"},
        "debit": {"deebet", "debit", "dr"},
        "credit": {"kreedit", "credit", "cr"},
        "date": {"kuupaev", "kandekuupaev", "date", "postingdate", "transactiondate"},
    }.items():
        if text in aliases:
            return field
    return None


def parse_journal_workbook(content: bytes) -> list[dict[str, Any]]:
    """Read every titled journal block; keep invalid blocks available for review."""
    from openpyxl import load_workbook

    if not isinstance(content, bytes) or not content or len(content) > 2_000_000:
        raise ValueError("Journal workbook must be an XLSX file under 2 MB")
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 20_000_000:
                raise ValueError("Journal workbook is too large when expanded")
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=False)
    except (BadZipFile, OSError, KeyError) as error:
        raise ValueError("Journal workbook is not a valid XLSX file") from error
    records = []
    try:
        for sheet in book:
            title = None
            block = None
            columns = {}

            def finish():
                if block is None:
                    return
                dates = sorted({line["date"] for line in block["lines"] if line.get("date")})
                if len(dates) > 1:
                    block["import_warning"] = "Journal block contains different posting dates"
                block["date"] = dates[0] if len(dates) == 1 else None
                identity = json.dumps(block, sort_keys=True, ensure_ascii=False, default=str)
                block["external_id"] = "journal-" + hashlib.sha256(identity.encode()).hexdigest()
                records.append(block)

            if sheet.max_row and sheet.max_row > 10000:
                raise ValueError("Journal workbook exceeds the row limit")
            if sheet.max_column and sheet.max_column > 200:
                raise ValueError("Journal workbook is too large when expanded")
            rows = [cells for cells in sheet.iter_rows()
                    if any(cell.value is not None and str(cell.value).strip() for cell in cells)]
            required = {"account_code", "description", "debit", "credit"}
            row_headers = [{field: index for index, cell in enumerate(cells)
                            if (field := _journal_header(cell.value))} for cells in rows]
            for index, cells in enumerate(rows):
                row_number = next(cell.row for cell in cells if cell.value is not None)
                if row_number > 10000:
                    raise ValueError("Journal workbook exceeds the row limit")
                values = [cell.value for cell in cells]
                headers = row_headers[index]
                if required <= headers.keys():
                    finish()
                    if not title:
                        raise ValueError("Journal header must follow a block title")
                    block = {"name": title, "sheet": sheet.title, "header_row": row_number, "lines": []}
                    title = None
                    columns = headers
                    continue
                nonempty = [value for value in values if value is not None and str(value).strip()]
                if index + 1 < len(rows) and required <= row_headers[index + 1].keys():
                    finish()
                    block = None
                    title = " ".join(str(value).strip() for value in nonempty)
                    continue
                if block is None:
                    continue
                line = {"row_number": row_number, "account_code": "", "description": "", "debit": None, "credit": None}
                try:
                    for field, column in columns.items():
                        value = values[column] if column < len(values) else None
                        if column < len(cells) and cells[column].data_type == "f":
                            raise ValueError("Journal formulas must be replaced with values")
                        if field in {"debit", "credit"}:
                            if value not in (None, ""):
                                amount = Decimal(str(value).replace(" ", "").replace("\u00a0", "").replace(",", "."))
                                if not amount.is_finite() or amount < 0:
                                    raise ValueError("Journal amounts must be non-negative finite numbers")
                                if money(amount) != amount:
                                    raise ValueError("Journal amounts must use whole cents")
                                line[field] = amount
                        elif field == "date":
                            if value not in (None, ""):
                                if isinstance(value, (datetime, date)):
                                    line[field] = value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
                                else:
                                    text = str(value).strip()
                                    line[field] = (datetime.strptime(text, "%d.%m.%Y").date().isoformat()
                                                   if "." in text else date.fromisoformat(text).isoformat())
                        else:
                            line[field] = str(value).strip() if value is not None else ""
                except (ValueError, InvalidOperation):
                    block["import_warning"] = "Journal line contains an invalid amount, date or formula"
                block["lines"].append(line)
            finish()
    finally:
        book.close()
    if not records:
        raise ValueError("No titled journal blocks found in the workbook")
    return records
