from copy import deepcopy
from decimal import Decimal

import pytest

from tsd_apa_rules import validate_payout

PAYOUT = {"id": "p1", "payout_date": "2026-10-31"}
RECORD = {"recipient_personal_id": "49001010012", "tsd_payment_type": 10,
          "payment_month": "2026-10", "gross_amount": Decimal("100"),
          "tax_free_minimum": Decimal("10"), "income_tax": Decimal("0"),
          "social_tax": Decimal("33"), "employee_unemployment_insurance": Decimal("1.6"),
          "employer_unemployment_insurance": Decimal("0.8"), "funded_pension": Decimal("2"),
          "social_tax_base": Decimal("100"), "net_amount": Decimal("86.4")}


def codes(payout=PAYOUT, record=RECORD):
    return {finding["rule_code"] for finding in validate_payout(payout, [record])}


def test_valid_frozen_payout_has_no_findings():
    assert codes() == set()


@pytest.mark.parametrize(("field", "value", "expected"), [
    ("recipient_personal_id", "invalid", "KR_XBRL_VALJAMAKSED_10"),
    ("tsd_payment_type", 120, "KR_XBRL_VALJAMAKSED_14"),
    ("payment_month", "2026-11", "KR_XBRL_VALJAMAKSED_17"),
    ("recipient_personal_id", "49001010018", "KR_XBRL_VALJAMAKSED_10"),
    ("gross_amount", Decimal("-1"), "FA_APA_AMOUNT_01"),
    ("tax_free_minimum", Decimal("100"), "KR_MVT_08"),
    ("tsd_payment_type", 11, "KR_MVT_01"),
    ("tsd_payment_type", 21, "KR_TK_1"),
    ("tsd_payment_type", 24, "KR_KOP_01"),
])
def test_offline_rule_rejects_invalid_frozen_values(field, value, expected):
    record = deepcopy(RECORD)
    record[field] = value
    if expected == "KR_TK_1":
        record["employee_unemployment_insurance"] = Decimal("1")
    if expected == "KR_KOP_01":
        record["funded_pension"] = Decimal("1")
    if expected == "KR_MVT_01":
        record["tax_free_minimum"] = Decimal("10")
    assert expected in codes(record=record)
