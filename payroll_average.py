"""Pure, year-versioned average-pay calculations for Estonian payroll."""
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal

from core_utils import decimal, db_number, money
from payroll_calendar import is_working_day, norm_hours, public_holidays

RULE_VERSION = 'EE-AVG-2026-v1'


def _flag(value):
    return value is True or value == 1 or value == '1'


@dataclass(frozen=True)
class AveragePayBreakdown:
    rule_version: str
    event_date: str
    period_start: str
    period_end: str
    source_months: tuple[str, ...]
    frozen_wage_item_count: int
    historical_earning_count: int
    wage_total: Decimal
    calendar_days: int
    public_holidays: int
    unpaid_absence_days: int
    daily_denominator: int
    average_daily_pay: Decimal
    available_working_days: int
    average_working_day_pay: Decimal
    paid_hours: Decimal
    average_hourly_pay: Decimal
    fallback_used: bool
    fallback_description: str

    def as_dict(self):
        result = asdict(self)
        for key in ('wage_total', 'average_daily_pay', 'average_working_day_pay', 'paid_hours', 'average_hourly_pay'):
            result[key] = db_number(result[key])
        result['source_months'] = list(self.source_months)
        return result


def _month_window(event_date: date):
    event_month = date(event_date.year, event_date.month, 1)
    end = event_month - timedelta(days=1)
    start_month_number = event_month.year * 12 + event_month.month - 1 - 6
    start_year, start_month_zero = divmod(start_month_number, 12)
    start = date(start_year, start_month_zero + 1, 1)
    months = tuple(_add_month(start, index).strftime('%Y-%m') for index in range(6))
    return start, end, months


def _add_month(day, offset):
    index = day.year * 12 + day.month - 1 + offset
    year, month_zero = divmod(index, 12)
    return date(year, month_zero + 1, 1)


def _period_date(value):
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value + '-01' if len(value) == 7 else value)
    raise ValueError('Earning period must be a YYYY-MM string or date')


def _item_wages(item):
    if item.get('wage_total') is not None:
        return money(item['wage_total'])
    basis = item.get('pay_basis', 'monthly')
    if basis == 'monthly':
        base = money(item.get('gross_salary') or 0)
    elif basis == 'hourly':
        base = money(decimal(item.get('hourly_rate') or 0) * decimal(item.get('hours') or 0))
    else:
        base = Decimal(0)
    components = sum((money(component['amount']) for component in item.get('components', ())
                      if component.get('direction') == 'income' and _flag(component.get('is_wage'))), Decimal(0))
    return money(base + components)


def _item_hours(item, period):
    if item.get('worked_hours') is not None:
        return decimal(item['worked_hours'])
    if item.get('pay_basis') == 'hourly':
        return decimal(item.get('hours') or 0)
    worked = item.get('worked_days')
    norm = item.get('norm_days')
    if worked is None or not norm:
        return Decimal(0)
    year, month = (int(part) for part in period.split('-'))
    return Decimal(norm_hours(year, month)) * Decimal(worked) / Decimal(norm)


def calculate_average_pay(employee, event_date, *, approved_items=(), historical_earnings=(), absences=()):
    """Calculate calendar-day, working-day and hourly averages with a reviewable breakdown.

    Inputs are immutable approved run snapshots and already-reviewed historical
    earnings. Absence records supply `wage_paid`; only days with no paid wage are
    removed from the denominator. No database reads or writes occur here.
    """
    event = date.fromisoformat(event_date) if isinstance(event_date, str) else event_date
    if not isinstance(event, date):
        raise ValueError('Event date must be a date')
    start, end, source_months = _month_window(event)
    included = set(source_months)
    wage_rows = []
    hours_total = Decimal(0)
    frozen_count = historical_count = 0
    for source, collection in (('frozen', approved_items), ('history', historical_earnings)):
        for item in collection:
            period_date = _period_date(item.get('period') or item.get('earning_period'))
            period = period_date.strftime('%Y-%m')
            if period not in included:
                continue
            if source == 'frozen' and item.get('status', item.get('run_status')) != 'Approved':
                continue
            wage = _item_wages(item)
            wage_rows.append((source, item, period, wage))
            hours_total += _item_hours(item, period)
            if source == 'frozen':
                frozen_count += 1
            else:
                historical_count += 1
    wage_total = money(sum((row[3] for row in wage_rows), Decimal(0)))

    holidays = {day for year in range(start.year, end.year + 1) for day in public_holidays(year)
                if start <= day <= end}
    unpaid_dates = set()
    for absence in absences:
        wage_paid = absence.get('wage_paid')
        if not isinstance(wage_paid, bool):
            raise ValueError('Each average-pay absence must state whether wages were paid')
        if wage_paid:
            continue
        absence_start = max(start, date.fromisoformat(absence['start_date']))
        absence_end = min(end, date.fromisoformat(absence['end_date']))
        if absence_end < absence_start:
            continue
        cursor = absence_start
        while cursor <= absence_end:
            unpaid_dates.add(cursor)
            cursor += timedelta(days=1)
    excluded_dates = holidays | unpaid_dates
    daily_denominator = max(0, (end - start).days + 1 - len(excluded_dates))
    unpaid_absence_days = len(unpaid_dates - holidays)
    cursor = start
    available_working_days = 0
    while cursor <= end:
        if is_working_day(cursor) and cursor not in unpaid_dates:
            available_working_days += 1
        cursor += timedelta(days=1)

    fallback = not wage_rows or wage_total == 0
    fallback_description = ''
    if fallback:
        basis = employee.get('pay_basis', 'monthly')
        if basis == 'hourly' and employee.get('hourly_rate') is not None:
            monthly_hours = sum((Decimal(norm_hours(year, month)) for year, month in
                                 ((d.year, d.month) for d in (_add_month(start, i) for i in range(6)))), Decimal(0))
            wage_total = money(decimal(employee['hourly_rate']) * monthly_hours)
            hours_total = monthly_hours
            fallback_description = 'Current agreed hourly rate projected across the six calendar-month norms.'
        elif basis == 'monthly' and employee.get('gross_salary') is not None:
            wage_total = money(decimal(employee['gross_salary']) * 6)
            hours_total = Decimal(0)
            fallback_description = 'Current agreed monthly salary projected across six full calendar months.'
        else:
            wage_total = Decimal(0)
            hours_total = Decimal(0)
            fallback_description = 'No current agreed salary is available; average pay is zero pending review.'

    daily = money(wage_total / daily_denominator) if daily_denominator else Decimal(0)
    working_daily = money(wage_total / available_working_days) if available_working_days else Decimal(0)
    hourly = money(wage_total / hours_total) if hours_total else Decimal(0)
    return AveragePayBreakdown(
        RULE_VERSION, event.isoformat(), start.isoformat(), end.isoformat(), source_months,
        frozen_count, historical_count, wage_total, (end-start).days + 1, len(holidays),
        unpaid_absence_days, daily_denominator, daily, available_working_days,
        working_daily, hours_total, hourly, fallback, fallback_description,
    )
