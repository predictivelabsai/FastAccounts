from decimal import Decimal

from payroll_tsd_types import PAYMENT_TYPES, payment_type


def test_resident_matrix_rows_include_rates_and_exemptions():
    assert payment_type(10).social_tax_rate == Decimal("0.33")
    assert payment_type(10).monthly_minimum_applies is True
    assert payment_type(13).ui_applies is False
    assert payment_type(17).ii_pillar_applies is True
    assert payment_type(21).monthly_minimum_applies is False
    assert payment_type(24).social_tax_rate is None
    assert payment_type(33).allowed_exemptions == ("MVT_610",)
    assert all(code < 120 for code in PAYMENT_TYPES if code != 120)


def test_unknown_payment_type_is_rejected():
    try:
        payment_type(999)
    except ValueError as exc:
        assert "Unsupported TSD payment type" in str(exc)
    else:
        raise AssertionError("unknown type accepted")
