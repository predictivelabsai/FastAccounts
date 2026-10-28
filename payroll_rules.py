"""Verified, immutable payroll rules selected by settlement date.

Only 2026 is configured. Sources and scope are recorded in docs/payroll_rules.md.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


class UnsupportedPayrollYear(ValueError):
    """No verified payroll rules exist for the requested year."""

    def __init__(self):
        super().__init__('Payroll rules are not configured for this year')


@dataclass(frozen=True)
class PayrollRules:
    year: int
    income_tax_rate: Decimal
    basic_exemption: Decimal
    ui_employee_rate: Decimal
    ui_employer_rate: Decimal
    social_tax_rate: Decimal
    social_tax_monthly_base: Decimal
    minimum_wages: tuple[tuple[date, Decimal, Decimal], ...]

    def minimum_wage(self, applies_on: date) -> tuple[Decimal, Decimal]:
        if applies_on.year != self.year:
            raise UnsupportedPayrollYear()
        return next((monthly, hourly) for start, monthly, hourly in reversed(self.minimum_wages)
                    if start <= applies_on)


@dataclass(frozen=True)
class SickBenefitRules:
    year: int
    employer_day_start: int
    employer_day_end: int
    rate: Decimal
    health_fund_day_start: int
    unpaid_day_count: int


_RULES = {2026: PayrollRules(
    2026, Decimal('0.22'), Decimal('700'), Decimal('0.016'), Decimal('0.008'),
    Decimal('0.33'), Decimal('886'),
    ((date(2026, 1, 1), Decimal('886'), Decimal('5.31')),
     (date(2026, 4, 1), Decimal('946'), Decimal('5.67')))),
}

_SICK_BENEFIT_RULES = {
    2026: SickBenefitRules(2026, 2, 5, Decimal('0.70'), 6, 1),
}


def rules_for(applies_on: date) -> PayrollRules:
    try:
        return _RULES[applies_on.year]
    except KeyError:
        raise UnsupportedPayrollYear() from None


def sick_benefit_rules_for(year: int) -> SickBenefitRules:
    """Return the reviewed, year-specific employer sick benefit defaults."""
    try:
        return _SICK_BENEFIT_RULES[year]
    except KeyError:
        raise UnsupportedPayrollYear() from None


def settlement_date(period: str, salary_payout_date: date | str | None = None,
                   payday_rule_date: date | str | None = None) -> date:
    """Resolve tax settlement date in priority order: salary payout, payday, month end."""
    for value in (salary_payout_date, payday_rule_date):
        if value is not None:
            return value if isinstance(value, date) else date.fromisoformat(value)
    import calendar
    year, month = map(int, period.split('-'))
    return date(year, month, calendar.monthrange(year, month)[1])


def remaining_monthly_exemption(application_mode: str, application_amount: Decimal | None,
                                monthly_maximum: Decimal, already_used: Decimal) -> Decimal:
    """Return this pay item's share of an employee's payment-month exemption."""
    if application_mode == 'none':
        return Decimal('0.00')
    if application_mode == 'maximum':
        applicable = monthly_maximum
    elif application_mode == 'limited' and application_amount is not None:
        applicable = min(application_amount, monthly_maximum)
    else:
        raise ValueError('Invalid tax-free application')
    return max(Decimal('0.00'), applicable - already_used)

