"""Offline CSV/TSV employee import connector.

Native Excel workbooks are intentionally out of scope. Export them as CSV or
TSV first. The alias table is explicit so supported source headers stay
reviewable and deterministic.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

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
    """Parse one uploaded employee CSV/TSV export without network access."""

    key = "file_import"

    def __init__(self, csv_content: str, config: Mapping[str, Any] | None = None):
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
        if object_type not in {"employee", "employees"}:
            raise ValueError("File import supports employee imports only")
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
