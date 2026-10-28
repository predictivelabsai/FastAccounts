"""Offline APA TSD checks over frozen payout data."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from payroll_tsd_types import PAYMENT_TYPES


class APAValidationError(ValueError):
    def __init__(self, findings):
        self.findings = findings
        super().__init__("APA export is blocked by validation findings")


def valid_estonian_personal_code(value: str) -> bool:
    if len(value) != 11 or not value.isascii() or not value.isdigit():
        return False
    weights = (1, 2, 3, 4, 5, 6, 7, 8, 9, 1)
    check = sum(int(digit) * weight for digit, weight in zip(value[:10], weights)) % 11
    if check == 10:
        check = sum(int(digit) * weight for digit, weight in zip(value[:10], (3, 4, 5, 6, 7, 8, 9, 1, 2, 3))) % 11
        if check == 10:
            check = 0
    return int(value[-1]) == check


def validate_payout(payout: dict, records: list[dict], *, locale: str = "et") -> list[dict]:
    """Return deterministic findings; MUST/PUNANE findings block XML export."""
    findings = []

    def add(code, category, et, en):
        findings.append({"rule_code": code, "category": category,
                         "message_et": et, "message_en": en,
                         "message": et if locale == "et" else en,
                         "blocking": category in {"MUST", "PUNANE"}})

    for record in records:
        personal_id = str(record.get("recipient_personal_id") or "")
        payment_type = record.get("tsd_payment_type")
        code = str(payment_type)
        if not valid_estonian_personal_code(personal_id):
            add("KR_YLD_03", "MUST", f"Väljamakse saaja isikukood {personal_id} ei ole korrektne.",
                f"Recipient personal code {personal_id} is invalid.")
        if not code.isdigit() or int(code) not in PAYMENT_TYPES or int(code) == 120:
            add("KR_KALK_YLD_01", "SININE", f"Väljamakse liik {code} ei ole residendist füüsilisele isikule lubatud.",
                f"Payment type {code} is not allowed for a resident natural person.")
            continue
        kind = PAYMENT_TYPES[int(code)]
        for field, label, rule in (("employee_unemployment_insurance", "töötuskindlustusmakse", "KR_TK_1"),
                                   ("funded_pension", "kogumispensioni makse", "KR_KOP_01")):
            if Decimal(str(record.get(field, 0))) > 0 and not (kind.ui_applies if field.startswith("employee") else kind.ii_pillar_applies):
                add(rule, "PUNANE", f"Väljamakse saajale {personal_id} tehtud väljamaksel liigiga {kind.name} ei tohi {label} summa olla määratud.",
                    f"{label.capitalize()} must not be set for recipient {personal_id} and payment type {kind.name}.")
        if not kind.tax_free_allowed and Decimal(str(record.get("tax_free_minimum", 0))) > 0:
            add("KR_MVT_01", "PUNANE", f"Väljamakse saajale {personal_id} tehtud väljamaksel liigiga {kind.name} ei ole maksuvaba tulu määramine lubatud.",
                f"Tax-free income is not allowed for recipient {personal_id} and payment type {kind.name}.")
        cap = Decimal(str(record.get("gross_amount", 0))) - Decimal(str(record.get("funded_pension", 0))) - Decimal(str(record.get("employee_unemployment_insurance", 0)))
        if Decimal(str(record.get("tax_free_minimum", 0))) > cap:
            add("KR_MVT_08", "PUNANE", f"Täpsustage maksuvaba tulu summat. Väljamakse saajale {personal_id} määratud maksuvaba tulu ületab arvutatud piirmäära {cap}.",
                f"Correct the tax-free amount for recipient {personal_id}; it exceeds the calculated limit {cap}.")
        for field in ("gross_amount", "tax_free_minimum", "income_tax", "social_tax", "employee_unemployment_insurance", "employer_unemployment_insurance", "funded_pension", "social_tax_base", "net_amount"):
            if Decimal(str(record.get(field, 0))) < 0:
                add("KR_YLD_01", "PUNANE", f"Väljamakse saajale {personal_id} määratud summa ei tohi olla negatiivne.",
                    f"Amounts for recipient {personal_id} must not be negative.")
                break
        try:
            expected_month = date.fromisoformat(str(payout["payout_date"])).strftime("%Y-%m")
        except (ValueError, KeyError):
            expected_month = ""
        if not expected_month or str(record.get("payment_month")) != expected_month:
            add("KR_KALK_XML_FAIL_05", "MUST", f"Väljamakse kuupäev ei kuulu deklareeritud maksustamisperioodi {record.get('payment_month', '')}.",
                f"Payment date does not belong to the declared month {record.get('payment_month', '')}.")
    return findings


def require_exportable(payout: dict, records: list[dict]) -> list[dict]:
    findings = validate_payout(payout, records)
    blocking = [finding for finding in findings if finding["blocking"]]
    if blocking:
        raise APAValidationError(blocking)
    return findings
