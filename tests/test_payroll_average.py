from datetime import date
from decimal import Decimal

import pytest

from core_utils import money
from payroll_average import RULE_VERSION, calculate_average_pay


def test_average_pay_uses_only_approved_wages_in_six_full_prior_months():
    result = calculate_average_pay(
        {'pay_basis': 'monthly', 'gross_salary': '2400'}, date(2026, 10, 15),
        approved_items=[
            {'period': '2026-04', 'status': 'Approved', 'pay_basis': 'monthly', 'gross_salary': '1000',
             'components': [{'direction': 'income', 'amount': '100', 'is_wage': True},
                            {'direction': 'income', 'amount': '500', 'is_wage': False}]},
            {'period': '2026-05', 'status': 'Draft', 'pay_basis': 'monthly', 'gross_salary': '900'},
            {'period': '2026-03', 'status': 'Approved', 'pay_basis': 'monthly', 'gross_salary': '800'},
        ],
    )
    assert result.rule_version == RULE_VERSION
    assert result.source_months == ('2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09')
    assert result.period_start == '2026-04-01' and result.period_end == '2026-09-30'
    assert result.wage_total == Decimal('1100.00')
    assert result.frozen_wage_item_count == 1
    assert result.average_daily_pay == money(Decimal('1100') / result.daily_denominator)


def test_average_pay_excludes_public_holidays_and_unpaid_absence_days_only():
    employee = {'pay_basis': 'monthly', 'gross_salary': '1000'}
    items = [{'period': month, 'status': 'Approved', 'pay_basis': 'monthly', 'gross_salary': '1000'}
             for month in ('2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09')]
    base = calculate_average_pay(employee, date(2026, 10, 1), approved_items=items)
    result = calculate_average_pay(employee, date(2026, 10, 1), approved_items=items,
                                   absences=[{'start_date': '2026-04-06', 'end_date': '2026-04-07', 'wage_paid': False},
                                             {'start_date': '2026-05-04', 'end_date': '2026-05-06', 'wage_paid': True}])
    assert result.public_holidays == base.public_holidays
    assert result.unpaid_absence_days == 2
    assert result.daily_denominator == base.daily_denominator - 2
    assert result.available_working_days == base.available_working_days - 2
    assert result.average_daily_pay > base.average_daily_pay
    assert result.average_working_day_pay > base.average_working_day_pay


def test_average_hourly_pay_uses_wage_components_and_paid_hours():
    result = calculate_average_pay(
        {'pay_basis': 'hourly', 'hourly_rate': '8.00'}, date(2026, 10, 1),
        approved_items=[{'period': '2026-09', 'status': 'Approved', 'pay_basis': 'hourly',
                         'hourly_rate': '10.00', 'hours': '100',
                         'components': [{'direction': 'income', 'amount': '50', 'is_wage': True},
                                        {'direction': 'income', 'amount': '40', 'is_wage': False}]}],
    )
    assert result.wage_total == Decimal('1050.00')
    assert result.paid_hours == Decimal('100')
    assert result.average_hourly_pay == Decimal('10.50')
    assert result.fallback_used is False


def test_reviewed_historical_monthly_wages_join_approved_item_history():
    result = calculate_average_pay(
        {'pay_basis': 'monthly', 'gross_salary': '2000'}, date(2026, 10, 1),
        approved_items=[{'period': '2026-09', 'status': 'Approved', 'pay_basis': 'monthly', 'gross_salary': '2000'}],
        historical_earnings=[{'period': '2026-04', 'wage_total': '1750', 'worked_days': 20, 'worked_hours': '160'}],
    )
    assert result.wage_total == Decimal('3750.00')
    assert result.frozen_wage_item_count == 1 and result.historical_earning_count == 1
    assert result.paid_hours == Decimal('160')


def test_average_pay_falls_back_to_current_agreed_salary_when_history_is_empty():
    result = calculate_average_pay({'pay_basis': 'monthly', 'gross_salary': '3000'}, date(2026, 10, 20))
    assert result.fallback_used is True
    assert result.fallback_description
    assert result.wage_total == Decimal('18000.00')
    assert result.average_daily_pay == money(Decimal('18000') / result.daily_denominator)
    assert result.as_dict()['average_daily_pay'] == str(result.average_daily_pay)


def test_average_pay_requires_an_explicit_wage_paid_flag_for_absences():
    with pytest.raises(ValueError, match='state whether wages were paid'):
        calculate_average_pay({'gross_salary': '2000'}, date(2026, 10, 1),
                              absences=[{'start_date': '2026-04-06', 'end_date': '2026-04-06'}])
