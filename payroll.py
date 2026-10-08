"""Estonian accounting-bureau payroll for the 2026 rule set.

Rates and rules (sources, checked 2026-10-08):
- EMTA "Maksumäärad" (updated 26.03.2026): income tax 22%, basic exemption
  EUR 700/month on written application, social tax 33%, unemployment insurance
  1.6% employee / 0.8% employer, funded pension (II pillar) 2/4/6% or 0% when
  the person has not joined or has left the scheme.
  https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/maksumaarad
- Minimum wage: EUR 886/month and EUR 5.31/hour until 31.03.2026; EUR 946/month
  and EUR 5.67/hour from 01.04.2026 (Vabariigi Valitsuse 23.03.2026 määrus nr 36).
  For part-time work the monthly minimum is pro-rated by the work-time fraction.
- Social tax minimum obligation (sotsiaalmaksu miinimumkohustus): the employer
  pays social tax on at least the 2026 monthly base of EUR 886 (EUR 292.38) per
  employee (SMS § 2 lg 2, § 2^1; rahandusministri 15.03.2013 määrus nr 17).
  Exceptions are listed on EMTA "Sotsiaalmaks" (updated 20.07.2026), section
  "Erandjuhud, millal tööandja ei pea täitma minimaalse sotsiaalmaksu kohustust"
  (SMS § 2 lg 3 p 1 and lg 4):
  https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/sotsiaalmaks
  Board-member fees are outside the obligation because it applies to employees
  and officials ("töötajale või ametnikule", määrus nr 17 § 2 lg 1). When
  employment starts or ends during the month the minimum base is pro-rated by
  calendar days of employment (SMS § 2 lg 3; EMTA examples use base / days in
  month x days).
"""
from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from core_utils import audit, db_number, decimal, four_dp, money, new_id, utc_now
from database import Database, get_database
from ledger import LedgerService, PostingLine


class PayrollConflict(ValueError):
    """A payroll workflow conflicts with an existing record or state."""


AMOUNTS = ('gross', 'funded_pension', 'ui_employee', 'tax_free_minimum',
           'income_tax', 'net', 'withholding_total', 'social_tax', 'ui_employer', 'employer_cost',
           'social_tax_base', 'social_tax_minimum_topup')

PAY_BASES = ('monthly', 'hourly', 'board_fee')
INCOME_TAX_RATE = Decimal('0.22')
BASIC_EXEMPTION = Decimal('700')
SOCIAL_TAX_RATE = Decimal('0.33')
# Sotsiaalmaksu kuumäär 2026 (riigieelarve; EMTA Sotsiaalmaks / Maksumäärad).
SOCIAL_TAX_MONTHLY_BASE = Decimal('886')
UI_EMPLOYEE_RATE = Decimal('0.016')
UI_EMPLOYER_RATE = Decimal('0.008')
MAX_MONTHLY_HOURS = Decimal('744')

# Per-employee reasons the employer pays social tax on actual pay only.
# Source for every entry: EMTA "Sotsiaalmaks" > "Erandjuhud, millal tööandja ei
# pea täitma minimaalse sotsiaalmaksu kohustust" (SMS § 2 lg 3 p 1, lg 4), except
# multiple_employers (rahandusministri 15.03.2013 määrus nr 17 § 5).
SOCIAL_TAX_MINIMUM_EXEMPTIONS = {
    'state_pension': 'SMS § 2 lg 4 p 6: riikliku pensioni saaja',
    'reduced_work_ability': 'SMS § 2 lg 4 p 6: osaline või puuduv töövõime (töövõimetoetuse seadus)',
    'child_care': 'SMS § 2 lg 4: kasvatab alla 3-aastast last või vähemalt kolme alla 19-aastast last',
    'student': 'SMS § 2 lg 4: õpilane või üliõpilane',
    'previously_unemployed': 'SMS § 2 lg 4 p 5: vähemalt 6 kuud töötuna arvel 12 kuu jooksul enne tööle asumist '
                             '(kehtib 12 kuud tööle asumisest)',
    'shortened_working_time': 'SMS § 2 lg 4: lühendatud tööaeg (7–17-aastased töötajad, haridustöötajad)',
    'local_council_member': 'SMS § 2 lg 4: kohaliku omavalitsuse volikogu liige',
    'ship_crew': 'SMS § 2 lg 4: laevapere liige (TuMS § 13 lg 5 või 6 tingimustele vastav laev)',
    'foreign_service_spouse': 'SMS § 2 lg 4: välisteenistuse seaduse § 67 alusel abikaasa- ja elukaaslase tasu saaja',
    'long_term_sick_leave_work': 'SMS § 2 lg 3 p 1: töötab pikaajalise haiguslehe alusel',
    'absent_whole_month': 'SMS § 2 lg 3 p 1: terve kuu eemal (puhkus v.a tasustamata puhkus kokkuleppel, '
                          'töövõimetus, streik, ajateenistus, töötajate esindamine)',
    'multiple_employers': 'Määrus nr 17 § 5: mitu tööandjat ja maksuvaba tulu arvestab teine tööandja, '
                          'kes kannab miinimumkohustuse',
}


# English catalogue keys (web/locales/*.json "workspace") for UI and payslip labels.
SOCIAL_TAX_MINIMUM_EXEMPTION_LABELS = {
    'state_pension': 'State pension recipient',
    'reduced_work_ability': 'Partial or no work ability',
    'child_care': 'Raising a child under 3 or three or more children under 19',
    'student': 'Pupil or student',
    'previously_unemployed': 'Registered unemployed for 6+ months before hiring',
    'shortened_working_time': 'Shortened working time (minors aged 7–17, teachers)',
    'local_council_member': 'Local council member',
    'ship_crew': 'Ship crew member',
    'foreign_service_spouse': 'Foreign-service spouse allowance',
    'long_term_sick_leave_work': 'Working on long-term sick leave',
    'absent_whole_month': 'Absent for the whole month (leave, sickness, strike, service)',
    'multiple_employers': 'Another employer applies the basic exemption',
    'board_member': 'Board member – no minimum obligation',
}

def minimum_wage(period: str) -> tuple[Decimal, Decimal]:
    """Monthly and hourly minimum wage (Vabariigi Valitsuse määrus nr 36, 23.03.2026)."""
    return (Decimal('886'), Decimal('5.31')) if period < '2026-04' else (Decimal('946'), Decimal('5.67'))


def pay_basis(employee: dict) -> str:
    basis = employee.get('pay_basis')
    if basis:
        return basis
    return 'board_fee' if employee.get('board_member') else 'monthly'


def _parse_date(value):
    if value in (None, ''):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Employment dates must be YYYY-MM-DD and the end cannot precede the start')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError('Employment dates must be YYYY-MM-DD and the end cannot precede the start') from exc


def employed_days(employee: dict, period: str) -> tuple[int, int]:
    """Calendar days employed in the period and the number of days in that month."""
    year, month = map(int, period.split('-'))
    days_in_month = calendar.monthrange(year, month)[1]
    first, last = date(year, month, 1), date(year, month, days_in_month)
    start = max(_parse_date(employee.get('employment_start_date')) or first, first)
    end = min(_parse_date(employee.get('employment_end_date')) or last, last)
    return max(0, (end - start).days + 1), days_in_month


def _fte(value) -> Decimal:
    return decimal(1 if value in (None, '') else value)


def calculate_pay(employee: dict, *, period: str | None = None, hours=None) -> dict:
    """Calculate one employee's month. Hourly gross = hourly rate x hours entered on the run."""
    basis = pay_basis(employee)
    board = basis == 'board_fee'
    if basis == 'hourly':
        gross = money(decimal(employee['hourly_rate']) * decimal(hours if hours is not None else employee.get('hours')))
    else:
        gross = money(employee['gross_salary'])
    pension = money(gross * decimal(employee['funded_pension_percent']) / 100)
    ui = money(0 if board else gross * UI_EMPLOYEE_RATE)
    taxable = gross - pension - ui
    # Record the basic exemption actually used: it cannot exceed the taxable amount.
    exemption = money(min(BASIC_EXEMPTION, max(Decimal('0'), taxable)) if employee['apply_tax_free_minimum'] else 0)
    income_tax = money(max(Decimal('0'), taxable - exemption) * INCOME_TAX_RATE)
    exemption_reason = 'board_member' if board else (employee.get('social_tax_minimum_exemption') or None)
    social_base = gross
    if exemption_reason is None:
        minimum_base = SOCIAL_TAX_MONTHLY_BASE
        if period:
            days, days_in_month = employed_days(employee, period)
            if days < days_in_month:
                minimum_base = money(SOCIAL_TAX_MONTHLY_BASE * days / days_in_month)
        social_base = max(gross, minimum_base)
    social = money(social_base * SOCIAL_TAX_RATE)
    topup = social - money(gross * SOCIAL_TAX_RATE)
    employer_ui = money(0 if board else gross * UI_EMPLOYER_RATE)
    withholding = pension + ui + income_tax
    return dict(gross=gross, funded_pension=pension, ui_employee=ui,
                tax_free_minimum=exemption, income_tax=income_tax, net=gross-withholding,
                withholding_total=withholding, social_tax=social, ui_employer=employer_ui,
                employer_cost=gross+social+employer_ui, social_tax_base=money(social_base),
                social_tax_minimum_topup=topup, social_tax_minimum_exemption=exemption_reason)


def _rate(value) -> str | None:
    if value is None:
        return None
    precise = four_dp(value)
    return db_number(money(precise) if precise == money(precise) else precise)


def _fraction(value) -> str:
    text = db_number(four_dp(_fte(value)))
    return text.rstrip('0').rstrip('.') if '.' in text else text


class PayrollService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    def _organisation(self, tx, organisation_id):
        org = tx.one('SELECT * FROM organisations WHERE id=?', (organisation_id,))
        if not org:
            raise KeyError('Organisation not found')
        if org['country_code'] != 'EE' or org['base_currency'] != 'EUR':
            raise ValueError('Payroll demo requires an Estonian organisation with EUR books')
        return org

    @staticmethod
    def _employee_values(values):
        data = dict(values)
        if not isinstance(data.get('name'), str) or not data['name'].strip() or len(data['name']) > 180:
            raise ValueError('Employee name must contain 1 to 180 characters')
        data['name'] = data['name'].strip()
        for field in ('board_member', 'active', 'apply_tax_free_minimum'):
            if data[field] not in (True, False, 0, 1):
                raise ValueError(f'{field} must be a boolean')
            data[field] = int(data[field])
        basis = data.get('pay_basis') or ('board_fee' if data['board_member'] else 'monthly')
        if basis not in PAY_BASES:
            raise ValueError('Pay basis must be monthly, hourly or board fee')
        if (basis == 'board_fee') != bool(data['board_member']):
            raise ValueError('Board members must use the board fee pay basis')
        data['pay_basis'] = basis
        if data.get('funded_pension_percent') is None:
            raise ValueError('Salary and pension percentage cannot be null')
        try:
            pension = decimal(data['funded_pension_percent'])
            if pension not in {0, 2, 4, 6}:
                raise ValueError('Funded pension must be 0, 2, 4 or 6 percent')
            data['funded_pension_percent'] = db_number(pension)
            fte = _fte(data.get('fte'))
            if not fte.is_finite() or fte <= 0 or fte > 1 or fte != four_dp(fte):
                raise ValueError('Work-time fraction (FTE) must be greater than 0 and at most 1')
            data['fte'] = db_number(four_dp(fte))
            if basis == 'hourly':
                rate = None if data.get('hourly_rate') in (None, '') else decimal(data['hourly_rate'])
                if rate is None or not rate.is_finite() or rate <= 0 or rate != four_dp(rate) or rate > Decimal('99999999.9999'):
                    raise ValueError('Hourly rate must be positive for hourly employees')
                data['hourly_rate'], data['gross_salary'] = db_number(four_dp(rate)), None
            else:
                if data.get('gross_salary') is None:
                    raise ValueError('Monthly salary or board fee must be positive')
                gross = decimal(data['gross_salary'])
                if not gross.is_finite() or gross <= 0 or gross > Decimal('9999999999.99'):
                    raise ValueError('Gross salary must be positive and fit NUMERIC(12,2)')
                if money(gross) <= 0:
                    raise ValueError('Gross salary must be at least 0.01')
                data['gross_salary'], data['hourly_rate'] = db_number(money(gross)), None
        except InvalidOperation as exc:
            raise ValueError('Invalid salary or pension percentage') from exc
        reason = data.get('social_tax_minimum_exemption') or None
        if reason is not None and reason not in SOCIAL_TAX_MINIMUM_EXEMPTIONS:
            raise ValueError('Unknown social tax minimum exemption')
        if reason == 'multiple_employers' and data['apply_tax_free_minimum']:
            raise ValueError('The multiple-employers exemption applies only when another employer applies the basic exemption')
        # Board-member fees never carry the minimum obligation, so no reason is stored.
        data['social_tax_minimum_exemption'] = None if basis == 'board_fee' else reason
        start, end = _parse_date(data.get('employment_start_date')), _parse_date(data.get('employment_end_date'))
        if start and end and end < start:
            raise ValueError('Employment dates must be YYYY-MM-DD and the end cannot precede the start')
        data['employment_start_date'] = start.isoformat() if start else None
        data['employment_end_date'] = end.isoformat() if end else None
        return data

    def employees(self, organisation_id):
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            return [self._serialize_employee(row) for row in tx.rows(
                'SELECT * FROM employees WHERE organisation_id=? ORDER BY name,id', (organisation_id,))]

    @staticmethod
    def _serialize_employee(row):
        row['gross_salary'] = None if row.get('gross_salary') is None else db_number(money(row['gross_salary']))
        row['funded_pension_percent'] = db_number(money(row['funded_pension_percent']))
        row['hourly_rate'] = _rate(row.get('hourly_rate'))
        row['fte'] = _fraction(row.get('fte'))
        row['pay_basis'] = pay_basis(row)
        for key in ('board_member', 'active', 'apply_tax_free_minimum'):
            row[key] = bool(row[key])
        return row

    def save_employee(self, organisation_id, *, actor, employee_id=None, tx=None, **changes):
        import sqlite3
        from psycopg.errors import UniqueViolation
        try:
            return self._save_employee(
                organisation_id, actor=actor, employee_id=employee_id, tx=tx, **changes
            )
        except (sqlite3.IntegrityError, UniqueViolation) as exc:
            if 'employees.organisation_id, employees.name' in str(exc) or getattr(exc, 'sqlstate', '') == '23505':
                raise PayrollConflict('An employee with this name already exists') from exc
            raise

    def _save_employee(self, organisation_id, *, actor, employee_id=None, tx=None, **changes):
        fields = ('name', 'email', 'personal_id', 'gross_salary', 'funded_pension_percent',
                  'apply_tax_free_minimum', 'board_member', 'active', 'pay_basis', 'fte', 'hourly_rate',
                  'social_tax_minimum_exemption', 'employment_start_date', 'employment_end_date')
        if set(changes) - set(fields):
            raise ValueError('Unknown employee field')
        # Keep the legacy board_member flag and the pay basis in step when only one is sent.
        if 'pay_basis' in changes and 'board_member' not in changes and changes['pay_basis'] in PAY_BASES:
            changes['board_member'] = changes['pay_basis'] == 'board_fee'
        if tx is None:
            with self.db.transaction() as owned_tx:
                return self._save_employee_tx(
                    owned_tx, organisation_id, actor, employee_id, fields, changes
                )
        return self._save_employee_tx(tx, organisation_id, actor, employee_id, fields, changes)

    def _save_employee_tx(self, tx, organisation_id, actor, employee_id, fields, changes):
        self._organisation(tx, organisation_id)
        if employee_id:
            data = tx.one('SELECT * FROM employees WHERE organisation_id=? AND id=?', (organisation_id, employee_id))
            if not data:
                raise KeyError('Employee not found')
            if 'board_member' in changes and 'pay_basis' not in changes:
                if changes['board_member'] in (True, 1):
                    changes['pay_basis'] = 'board_fee'
                elif data.get('pay_basis') == 'board_fee':
                    changes['pay_basis'] = 'monthly'
            data.update(changes)
        else:
            data = dict(email=None, personal_id=None, apply_tax_free_minimum=False, board_member=False, active=True)
            data.update(changes)
            data.setdefault('funded_pension_percent', 0 if data['board_member'] else 2)
        data = self._employee_values(data)
        record_id = employee_id or new_id()
        if employee_id:
            result = tx.execute('UPDATE employees SET '+','.join(f'{f}=?' for f in fields)+
                                ' WHERE organisation_id=? AND id=?',
                                tuple(data.get(f) for f in fields)+(organisation_id, record_id))
        else:
            result = tx.execute('INSERT INTO employees(id,organisation_id,created_at,'+','.join(fields)+') '
                                'VALUES ('+','.join('?' for _ in range(len(fields)+3))+') '
                                'ON CONFLICT(organisation_id,name) DO NOTHING',
                                (record_id, organisation_id, utc_now())+tuple(data.get(f) for f in fields))
        if result.rowcount != 1:
            raise PayrollConflict('An employee with this name already exists')
        audit(tx, organisation_id, actor, 'payroll.employee.updated' if employee_id else 'payroll.employee.created', 'employee', record_id)
        return self._serialize_employee(tx.one('SELECT * FROM employees WHERE organisation_id=? AND id=?', (organisation_id, record_id)))

    def _run(self, tx, organisation_id, run_id):
        run = tx.one('SELECT * FROM pay_runs WHERE organisation_id=? AND id=?', (organisation_id, run_id))
        if not run:
            raise KeyError('Pay run not found')
        run['items'] = tx.rows('SELECT * FROM pay_run_items WHERE organisation_id=? AND pay_run_id=? ORDER BY employee_name,id', (organisation_id, run_id))
        for item in run['items']:
            for key in (*AMOUNTS, 'gross_salary', 'funded_pension_percent'):
                item[key] = db_number(money(item[key]))
            item['minimum_wage'] = None if item.get('minimum_wage') is None else db_number(money(item['minimum_wage']))
            item['hours'] = None if item.get('hours') is None else db_number(money(item['hours']))
            item['hourly_rate'] = _rate(item.get('hourly_rate'))
            item['fte'] = _fraction(item.get('fte'))
            item['board_member'] = bool(item['board_member'])
        for key in ('total_gross', 'total_net', 'total_employer_cost'):
            run[key] = db_number(money(run[key]))
        return run

    def runs(self, organisation_id):
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            return [self._run(tx, organisation_id, row['id']) for row in tx.rows(
                'SELECT id FROM pay_runs WHERE organisation_id=? ORDER BY period DESC,id', (organisation_id,))]

    @staticmethod
    def _hours(employee, hours):
        value = (hours or {}).get(employee['id'])
        if value in (None, ''):
            raise ValueError(f"{employee['name']}: enter hours worked")
        try:
            value = decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"{employee['name']}: hours must be a positive number with at most two decimals") from exc
        if not value.is_finite() or value <= 0 or value > MAX_MONTHLY_HOURS or value != money(value):
            raise ValueError(f"{employee['name']}: hours must be a positive number with at most two decimals")
        return money(value)

    def create_run(self, organisation_id, *, period, actor, hours=None):
        if not re.fullmatch(r'2026-(0[1-9]|1[0-2])', period):
            raise ValueError('Payroll demo supports monthly periods YYYY-MM in 2026 only')
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            run_id = new_id()
            result = tx.execute("INSERT INTO pay_runs(id,organisation_id,period,total_gross,total_net,total_employer_cost,created_by,created_at) VALUES (?,?,?,0,0,0,?,?) ON CONFLICT(organisation_id,period) DO NOTHING", (run_id, organisation_id, period, actor, utc_now()))
            if result.rowcount != 1:
                raise PayrollConflict(f'A pay run already exists for {period}')
            employees = [e for e in tx.rows('SELECT * FROM employees WHERE organisation_id=? AND active=1 ORDER BY name,id', (organisation_id,))
                         if employed_days(e, period)[0] > 0]
            if not employees:
                raise ValueError('A pay run requires at least one active employee')
            monthly_minimum, hourly_minimum = minimum_wage(period)
            totals = dict(gross=Decimal(0), net=Decimal(0), employer_cost=Decimal(0))
            columns = ('id', 'pay_run_id', 'organisation_id', 'employee_id', 'employee_name', 'gross_salary',
                       'board_member', 'funded_pension_percent', 'pay_basis', 'fte', 'hourly_rate', 'hours',
                       'minimum_wage', 'social_tax_minimum_exemption', *AMOUNTS)
            for employee in employees:
                basis, fte, worked, required = pay_basis(employee), _fte(employee.get('fte')), None, None
                if basis == 'monthly':
                    # Part-time: the monthly minimum wage is pro-rated by the work-time fraction.
                    required = money(monthly_minimum * fte)
                    if money(employee['gross_salary']) < required:
                        suffix = f" (EUR {monthly_minimum:.2f} × {_fraction(fte)})" if fte != 1 else ''
                        raise ValueError(f"{employee['name']}: gross salary must be at least EUR {required:.2f}{suffix}")
                elif basis == 'hourly':
                    required = hourly_minimum
                    if decimal(employee['hourly_rate']) < hourly_minimum:
                        raise ValueError(f"{employee['name']}: hourly rate must be at least EUR {hourly_minimum:.2f}")
                    worked = self._hours(employee, hours)
                amounts = calculate_pay(employee, period=period, hours=worked)
                values = (new_id(), run_id, organisation_id, employee['id'], employee['name'],
                          db_number(amounts['gross'] if basis == 'hourly' else money(employee['gross_salary'])),
                          int(basis == 'board_fee'), db_number(decimal(employee['funded_pension_percent'])), basis,
                          db_number(four_dp(fte)), None if basis != 'hourly' else db_number(four_dp(employee['hourly_rate'])),
                          None if worked is None else db_number(worked), None if required is None else db_number(money(required)),
                          amounts['social_tax_minimum_exemption'])
                tx.execute('INSERT INTO pay_run_items('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',
                           values+tuple(db_number(amounts[k]) for k in AMOUNTS))
                for key in totals:
                    totals[key] += amounts[key]
            tx.execute('UPDATE pay_runs SET total_gross=?,total_net=?,total_employer_cost=? WHERE organisation_id=? AND id=?', tuple(db_number(totals[k]) for k in totals)+(organisation_id, run_id))
            audit(tx, organisation_id, actor, 'payroll.drafted', 'pay_run', run_id, {'period': period})
            return self._run(tx, organisation_id, run_id)

    def approve(self, organisation_id, run_id, *, actor):
        from web import i18n
        with self.db.transaction() as tx:
            # Conditional write serializes concurrent approvals on SQLite and PostgreSQL.
            claimed = tx.execute("UPDATE pay_runs SET status='Approved',approved_at=? WHERE organisation_id=? AND id=? AND status='Draft'", (utc_now(), organisation_id, run_id))
            run = self._run(tx, organisation_id, run_id)
            if claimed.rowcount != 1:
                raise PayrollConflict('Pay run is already approved')
            totals = {k: sum((decimal(i[k]) for i in run['items']), Decimal(0)) for k in AMOUNTS}
            memo = f"Payroll {run['period']}"
            # The social tax minimum shortfall is an employer cost on the existing social-tax
            # accounts, posted as its own line so the top-up is visible in the ledger.
            topup = totals['social_tax_minimum_topup']
            topup_memo = f"{i18n.t('workspace.Social tax minimum top-up', 'et')} {run['period']}"
            postings = [('PAYROLL_SALARY', totals['gross'], True, memo),
                        ('PAYROLL_SOCIAL', totals['social_tax']-topup, True, memo),
                        ('PAYROLL_SOCIAL', topup, True, topup_memo),
                        ('PAYROLL_UI', totals['ui_employer'], True, memo), ('PAYROLL_NET', totals['net'], False, memo),
                        ('PAYROLL_INCOME_TAX', totals['income_tax'], False, memo),
                        ('PAYROLL_WITHHOLDING', totals['funded_pension']+totals['ui_employee'], False, memo),
                        ('PAYROLL_EMPLOYER_TAX', totals['social_tax']-topup+totals['ui_employer'], False, memo),
                        ('PAYROLL_EMPLOYER_TAX', topup, False, topup_memo)]
            lines = []
            for role, value, debit, line_memo in postings:
                if not value:
                    continue
                account = tx.one('SELECT id FROM accounts WHERE organisation_id=? AND system_role=? AND active=1', (organisation_id, role))
                if not account:
                    raise ValueError(f'Chart of accounts is missing {role}')
                lines.append(PostingLine(account['id'], debit=value if debit else Decimal(0), credit=Decimal(0) if debit else value,
                                         memo=line_memo, source_line_type='pay_run', source_line_id=run_id))
            year, month = map(int, run['period'].split('-'))
            batch = LedgerService(self.db).post(organisation_id=organisation_id, voucher_type='payroll', voucher_id=run_id,
                voucher_code=f"PAY-{run['period']}", posting_date=f"{run['period']}-{calendar.monthrange(year,month)[1]}",
                lines=lines, actor=actor, currency='EUR', tx=tx)
            tx.execute('UPDATE pay_runs SET posted_batch_id=?,total_gross=?,total_net=?,total_employer_cost=? WHERE organisation_id=? AND id=?',
                       (batch['id'], db_number(totals['gross']), db_number(totals['net']), db_number(totals['employer_cost']), organisation_id, run_id))
            audit(tx, organisation_id, actor, 'payroll.approved', 'pay_run', run_id, {'posted_batch_id': batch['id']})
            return self._run(tx, organisation_id, run_id)

    def delete_run(self, organisation_id, run_id, *, actor):
        with self.db.transaction() as tx:
            claimed = tx.execute("UPDATE pay_runs SET notes=notes WHERE organisation_id=? AND id=? AND status='Draft'", (organisation_id, run_id))
            self._run(tx, organisation_id, run_id)
            if claimed.rowcount != 1:
                raise PayrollConflict('Only draft pay runs can be deleted')
            tx.execute('DELETE FROM pay_run_items WHERE organisation_id=? AND pay_run_id=?', (organisation_id, run_id))
            tx.execute('DELETE FROM pay_runs WHERE organisation_id=? AND id=?', (organisation_id, run_id))
            audit(tx, organisation_id, actor, 'payroll.deleted', 'pay_run', run_id)

    def payslips_pdf(self, organisation_id, run_id):
        from documents import payroll_pdf
        with self.db.transaction() as tx:
            run = self._run(tx, organisation_id, run_id)
            org = self._organisation(tx, organisation_id)
        return payroll_pdf(org, run)
