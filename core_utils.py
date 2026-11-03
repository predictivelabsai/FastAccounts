"""Shared deterministic helpers for accounting services."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4


MONEY = Decimal("0.01")
FOUR_DP = Decimal("0.0001")


def new_id() -> str:
    return str(uuid4())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return date.today().isoformat()


def decimal(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def parse_decimal_ee(value: object) -> Decimal:
    """Parse unambiguous decimal text from Estonian accounting exports."""
    if isinstance(value, Decimal):
        result = value
    else:
        text = str(value).strip()
        text = re.sub(r"\s*(?:EUR|€)\s*$", "", text, flags=re.IGNORECASE).strip()
        text = text.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
        if not text or not re.fullmatch(r"[+-]?(?:\d+(?:[.,]\d+)?|\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?)", text):
            raise ValueError(f"Invalid decimal value: {value!r}")
        if "," in text and "." in text:
            decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
            thousands_separator = "." if decimal_separator == "," else ","
            text = text.replace(thousands_separator, "").replace(decimal_separator, ".")
        elif "," in text:
            if text.count(",") > 1:
                raise ValueError(f"Invalid decimal value: {value!r}")
            text = text.replace(",", ".")
        elif text.count(".") > 1:
            raise ValueError(f"Invalid decimal value: {value!r}")
        try:
            result = Decimal(text)
        except InvalidOperation as error:
            raise ValueError(f"Invalid decimal value: {value!r}") from error
    if not result.is_finite():
        raise ValueError(f"Invalid decimal value: {value!r}")
    return result


def money(value: object) -> Decimal:
    return decimal(value).quantize(MONEY, rounding=ROUND_HALF_UP)


def four_dp(value: object) -> Decimal:
    return decimal(value).quantize(FOUR_DP, rounding=ROUND_HALF_UP)


def db_number(value: Decimal) -> str:
    """Pass exact numbers through both SQLite and PostgreSQL adapters."""
    return format(value, "f")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def audit(tx, organisation_id: str | None, actor: str, action: str,
          object_type: str, object_id: str, details: object | None = None) -> None:
    tx.execute(
        "INSERT INTO audit_events(id,organisation_id,actor,action,object_type,object_id,details_json,created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (new_id(), organisation_id, actor, action, object_type, object_id,
         canonical_json(details or {}), utc_now()),
    )
