from datetime import date
from decimal import Decimal

from payroll_leave_liability import (
    LeaveLot, accrued_days, consume_fifo, expiry_date, liability_value,
)


def test_entitlement_accrues_pro_rata_by_calendar_day():
    assert accrued_days(28, date(2026, 7, 1), date(2026, 12, 31), 2026) == Decimal('14.1151')


def test_expiry_policies_and_fifo_consumption():
    assert expiry_date(2024, '1_january_year_plus_2') == date(2026, 1, 1)
    assert expiry_date(2024, '31_december_year_plus_1') == date(2025, 12, 31)
    lots = [LeaveLot(Decimal('10'), date(2025, 1, 1), date(2027, 1, 1)),
            LeaveLot(Decimal('7'), date(2026, 1, 1), None)]
    remaining, consumed, shortage = consume_fifo(lots, Decimal('12'), date(2026, 10, 1))
    assert [days for _, days in consumed] == [Decimal('10'), Decimal('2')]
    assert remaining[0].days == Decimal('5')
    assert shortage == 0


def test_expired_lot_is_not_available():
    remaining, consumed, shortage = consume_fifo(
        [LeaveLot(Decimal('4'), date(2024, 1, 1), date(2025, 12, 31))], 2,
        date(2026, 1, 1))
    assert remaining == [] and consumed == [] and shortage == 2


def test_liability_adds_employer_social_costs():
    value = liability_value(Decimal('5'), Decimal('100'), date(2026, 10, 31))
    assert value['wage_liability'] == '500.00'
    assert value['social_tax'] == '165.00'
    assert value['employer_unemployment'] == '4.00'
    assert value['total_liability'] == '669.00'
