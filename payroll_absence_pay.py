"""Pure absence-pay methods and payout-date rules."""
from datetime import date, timedelta
from decimal import Decimal

from core_utils import db_number, decimal, money
from payroll_calendar import is_working_day
from payroll_rules import sick_benefit_rules_for

VACATION_PAY_METHODS = ('average', 'unchanged_salary', 'best_of', 'fixed_sum')


def vacation_pay(method, *, average_daily_pay, leave_days, monthly_salary=None,
                 leave_working_days=0, norm_working_days=0, fixed_sum=None):
    if method not in VACATION_PAY_METHODS:
        raise ValueError('Choose a valid vacation pay method')
    if leave_days < 0 or leave_working_days < 0:
        raise ValueError('Leave days cannot be negative')
    average = money(decimal(average_daily_pay) * Decimal(leave_days))
    unchanged = (money(decimal(monthly_salary) * Decimal(leave_working_days) / Decimal(norm_working_days))
                 if monthly_salary is not None and norm_working_days > 0 else Decimal('0.00'))
    if method == 'average':
        amount = average
    elif method == 'unchanged_salary':
        amount = unchanged
    elif method == 'best_of':
        amount = max(average, unchanged)
    else:
        if fixed_sum is None:
            raise ValueError('A fixed sum is required for the fixed-sum method')
        amount = money(fixed_sum)
        if amount < 0:
            raise ValueError('A fixed sum cannot be negative')
    return {
        'method': method,
        'average_amount': db_number(average),
        'unchanged_salary_amount': db_number(unchanged),
        'fixed_sum': None if fixed_sum is None else db_number(money(fixed_sum)),
        'amount': db_number(amount),
        'leave_days': leave_days,
        'leave_working_days': leave_working_days,
    }


def employer_sick_benefit(average_daily_pay, sick_start, absence_start, absence_end):
    """Employer benefit for qualifying calendar days in one sickness period."""
    rules = sick_benefit_rules_for(sick_start.year)
    if absence_start < sick_start or absence_end < absence_start:
        raise ValueError('Sickness dates must be in order')
    qualifying_days = 0
    current = absence_start
    while current <= absence_end:
        sickness_day = (current - sick_start).days + 1
        if rules.employer_day_start <= sickness_day <= rules.employer_day_end:
            qualifying_days += 1
        current += timedelta(days=1)
    daily = money(decimal(average_daily_pay) * rules.rate)
    amount = money(daily * Decimal(qualifying_days))
    return {
        'rule_year': rules.year,
        'employer_day_start': rules.employer_day_start,
        'employer_day_end': rules.employer_day_end,
        'rate': str(rules.rate),
        'sick_start': sick_start.isoformat(),
        'absence_start': absence_start.isoformat(),
        'absence_end': absence_end.isoformat(),
        'unpaid_day_count': rules.unpaid_day_count,
        'qualifying_days': qualifying_days,
        'average_daily_pay': db_number(money(average_daily_pay)),
        'benefit_daily_pay': db_number(daily),
        'amount': db_number(amount),
        'health_fund_day_start': rules.health_fund_day_start,
    }


def unused_leave_compensation(remaining_leave_days, average_daily_pay):
    if remaining_leave_days < 0:
        raise ValueError('Remaining leave days cannot be negative')
    return money(decimal(remaining_leave_days) * decimal(average_daily_pay))


def vacation_payout_date(leave_start):
    """Return the working day immediately before the leave start date."""
    current = leave_start - timedelta(days=1)
    while not is_working_day(current):
        current -= timedelta(days=1)
    return current
