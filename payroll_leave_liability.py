"""Pure, FIFO leave entitlement and liability calculations."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core_utils import decimal, money
from payroll_rules import rules_for


@dataclass(frozen=True)
class LeaveLot:
    days: Decimal
    accrued_on: date
    expires_on: date | None
    kind: str = 'basic'


def accrued_days(days_per_year, employed_from: date, employed_to: date,
                 year: int) -> Decimal:
    """Calendar-day pro-rata, retaining four decimal places for entitlement."""
    start = max(employed_from, date(year, 1, 1))
    end = min(employed_to, date(year, 12, 31))
    if start > end:
        return Decimal('0.0000')
    days = Decimal((end - start).days + 1)
    year_days = Decimal((date(year + 1, 1, 1) - date(year, 1, 1)).days)
    return (decimal(days_per_year) * days / year_days).quantize(Decimal('0.0001'))


def expiry_date(accrual_year: int, policy: str) -> date | None:
    if policy == 'none':
        return None
    if policy == '1_january_year_plus_2':
        return date(accrual_year + 2, 1, 1)
    if policy == '31_december_year_plus_1':
        return date(accrual_year + 1, 12, 31)
    raise ValueError('Invalid leave expiry policy')


def consume_fifo(lots: list[LeaveLot], leave_days, as_at: date):
    remaining = decimal(leave_days)
    consumed = []
    kept = []
    for lot in sorted(lots, key=lambda item: (item.accrued_on, item.expires_on or date.max)):
        available = lot.days if lot.expires_on is None or lot.expires_on >= as_at else Decimal('0')
        take = min(remaining, available)
        if take:
            consumed.append((lot, take))
            remaining -= take
        left = lot.days - take
        if left > 0 and (lot.expires_on is None or lot.expires_on >= as_at):
            kept.append(LeaveLot(left, lot.accrued_on, lot.expires_on, lot.kind))
    return kept, consumed, remaining


def liability_value(remaining_days, average_daily_pay, valuation_date: date):
    rules = rules_for(valuation_date)
    wage = money(decimal(remaining_days) * decimal(average_daily_pay))
    social_tax = money(wage * rules.social_tax_rate)
    employer_ui = money(wage * rules.ui_employer_rate)
    return {
        'remaining_days': str(decimal(remaining_days)),
        'average_daily_pay': str(money(average_daily_pay)),
        'wage_liability': str(wage),
        'social_tax': str(social_tax),
        'employer_unemployment': str(employer_ui),
        'total_liability': str(wage + social_tax + employer_ui),
        'valuation_date': valuation_date.isoformat(),
        'rule_year': rules.year,
    }
