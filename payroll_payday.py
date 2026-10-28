"""Pure company payday rule resolution for Estonian payroll."""
from calendar import monthrange
from datetime import date, timedelta

from payroll_calendar import is_working_day
from core_utils import audit, new_id

RULES = frozenset({'next_month_day', 'current_month_day', 'next_month_first_working_day'})


def payday(period: str, rule: str, day: int | None = None) -> date:
    year, month = map(int, period.split('-'))
    if month not in range(1, 13):
        raise ValueError('Invalid payroll period')
    if rule not in RULES:
        raise ValueError('Invalid payday rule')
    if rule == 'next_month_first_working_day':
        if day is not None:
            raise ValueError('First-working-day rule does not use a payday day')
        target_month = month + 1
        target_year = year
        if target_month == 13:
            target_year, target_month = year + 1, 1
        result = date(target_year, target_month, 1)
        while not is_working_day(result):
            result += timedelta(days=1)
        return result
    if day is None or not 1 <= day <= 31:
        raise ValueError('Payday day must be between 1 and 31')
    if rule == 'next_month_day':
        month += 1
        if month == 13:
            year, month = year + 1, 1
    result = date(year, month, min(day, monthrange(year, month)[1]))
    while not is_working_day(result):
        result -= timedelta(days=1)
    return result


def payday_for_period(tx, organisation_id: str, period: str) -> date | None:
    row = tx.one('SELECT rule,day FROM organisation_payday_rules WHERE organisation_id=? AND start_date<=? ORDER BY start_date DESC LIMIT 1',
                 (organisation_id, period + '-31'))
    return payday(period, row['rule'], row['day']) if row else None


class PaydaySettingsService:
    def __init__(self, db):
        self.db = db

    def get(self, organisation_id: str) -> dict:
        with self.db.transaction() as tx:
            settings = tx.one('SELECT payroll_start_date FROM organisation_payroll_settings WHERE organisation_id=?', (organisation_id,))
            if not settings:
                tx.one('SELECT id FROM organisations WHERE id=?', (organisation_id,)) or self._missing()
                settings = {'payroll_start_date': None}
            history = tx.rows('SELECT id,start_date,rule,day FROM organisation_payday_rules WHERE organisation_id=? ORDER BY start_date', (organisation_id,))
            return {'payroll_start_date': settings['payroll_start_date'], 'rules': history}

    def save(self, organisation_id: str, *, start_date: str | None, rule_start_date: str,
             rule: str, day: int | None, actor: str) -> dict:
        date.fromisoformat(rule_start_date)
        if start_date is not None:
            date.fromisoformat(start_date)
        if rule not in RULES or ((rule == 'next_month_first_working_day') != (day is None)):
            raise ValueError('Invalid payday rule')
        if day is not None and not 1 <= day <= 31:
            raise ValueError('Payday day must be between 1 and 31')
        with self.db.transaction() as tx:
            tx.one('SELECT id FROM organisations WHERE id=?', (organisation_id,)) or self._missing()
            tx.execute('INSERT INTO organisation_payroll_settings(organisation_id,payroll_start_date) VALUES (?,?) '
                       'ON CONFLICT(organisation_id) DO UPDATE SET payroll_start_date=excluded.payroll_start_date',
                       (organisation_id, start_date))
            existing = tx.one('SELECT id FROM organisation_payday_rules WHERE organisation_id=? AND start_date=?', (organisation_id, rule_start_date))
            if existing:
                tx.execute('UPDATE organisation_payday_rules SET rule=?,day=? WHERE organisation_id=? AND id=?',
                           (rule, day, organisation_id, existing['id']))
                rule_id = existing['id']
            else:
                rule_id = new_id()
                tx.execute('INSERT INTO organisation_payday_rules(id,organisation_id,start_date,rule,day) VALUES (?,?,?,?,?)',
                           (rule_id, organisation_id, rule_start_date, rule, day))
            audit(tx, organisation_id, actor, 'payroll.payday_rule.saved', 'organisation_payday_rule', rule_id)
        return self.get(organisation_id)

    @staticmethod
    def _missing():
        raise ValueError('Organisation not found')
