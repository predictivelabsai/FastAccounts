from datetime import date
from decimal import Decimal

import pytest

from payroll_absence_pay import (
    employer_sick_benefit, unused_leave_compensation, vacation_pay,
    vacation_payout_date,
)


def test_vacation_pay_methods_return_auditable_breakdown():
    args = dict(average_daily_pay='100', leave_days=5, monthly_salary='2200',
                leave_working_days=5, norm_working_days=22)
    assert vacation_pay('average', **args)['amount'] == '500.00'
    assert vacation_pay('unchanged_salary', **args)['amount'] == '500.00'
    assert vacation_pay('best_of', **args)['method'] == 'best_of'
    assert vacation_pay('fixed_sum', **args, fixed_sum='275')['amount'] == '275.00'
    assert vacation_pay('best_of', **{**args, 'average_daily_pay': '120'})['amount'] == '600.00'


def test_fixed_sum_requires_explicit_amount():
    with pytest.raises(ValueError):
        vacation_pay('fixed_sum', average_daily_pay=0, leave_days=1)


def test_employer_sick_pay_covers_days_two_to_five_at_seventy_percent():
    result = employer_sick_benefit(Decimal('100'), date(2026, 10, 1),
                                   date(2026, 10, 1), date(2026, 10, 6))
    assert result['qualifying_days'] == 4
    assert result['amount'] == '280.00'
    assert result['health_fund_day_start'] == 6


def test_termination_compensation_and_vacation_payout_date():
    assert unused_leave_compensation(Decimal('3.5'), Decimal('40')) == Decimal('140.00')
    assert vacation_payout_date(date(2026, 10, 5)) == date(2026, 10, 2)
