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
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from core_utils import audit, db_number, decimal, four_dp, money, new_id, utc_now
from database import Database, get_database
from ledger import LedgerService, PostingLine
from payroll_components import FLAGS, ROLES, serialise
from payroll_rules import remaining_monthly_exemption, rules_for, settlement_date
from payroll_tax_settings import EmployeeTaxSettingsService, resolve as resolve_tax_settings
from payroll_tax_repository import monthly_exemption_used
from payroll_payday import payday_for_period
from employee_details import validate_details, birth_date_from_personal_code
from payroll_absences import PayrollAbsenceService
from payroll_absence_pay import employer_sick_benefit, unused_leave_compensation
from payroll_average import calculate_average_pay
import json


class PayrollConflict(ValueError):
    """A payroll workflow conflicts with an existing record or state."""


AMOUNTS = ('gross', 'funded_pension', 'ui_employee', 'tax_free_minimum',
           'income_tax', 'net', 'withholding_total', 'social_tax', 'ui_employer', 'employer_cost',
           'social_tax_base', 'social_tax_minimum_topup')

PAY_BASES = ('monthly', 'hourly', 'board_fee', 'income_line')
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
    applies_on = settlement_date(period)
    return rules_for(applies_on).minimum_wage(applies_on)


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


def calculate_pay(employee: dict, *, period: str | None = None, hours=None, components=(),
                  settlement_on: date | None = None, exemption_remaining: Decimal | None = None,
                  allow_zero_monthly=False) -> dict:
    """Calculate one employee's month. Hourly gross = hourly rate x hours entered on the run."""
    rules = rules_for(settlement_on or settlement_date(period or '2026-01'))
    basis = pay_basis(employee)
    board = basis == 'board_fee'
    if basis == 'hourly':
        gross = money(decimal(employee['hourly_rate']) * decimal(hours if hours is not None else employee.get('hours')))
    elif basis == 'income_line':
        # Services-contract remuneration consists entirely of explicit income lines.
        gross = Decimal(0)
    else:
        gross = money(employee['gross_salary'])
    bases = {key: gross for key in FLAGS}
    if board:
        bases['ui_employee'] = bases['ui_employer'] = Decimal(0)
    deductions = Decimal(0)
    for component in components:
        amount = money(component['amount'])
        if component['direction'] == 'deduction':
            deductions += amount
            continue
        gross += amount
        for key in FLAGS:
            if component[key]:
                bases[key] += amount
    if gross < 0 or (gross == 0 and basis != 'income_line' and not allow_zero_monthly) or any(value < 0 for value in bases.values()):
        raise ValueError('Payment components must leave positive gross and non-negative tax bases')
    pension = money(bases['funded_pension'] * decimal(employee['funded_pension_percent']) / 100)
    ui = money(bases['ui_employee'] * rules.ui_employee_rate) if employee.get('unemployment_applies', True) is not False and employee.get('unemployment_applies') != 0 else money(0)
    taxable = bases['income_tax'] - pension - ui
    # Record the basic exemption actually used: it cannot exceed the taxable amount.
    mode = employee.get('tax_free_mode') or ('maximum' if employee['apply_tax_free_minimum'] else 'none')
    allowance = decimal(employee['tax_free_amount']) if mode == 'limited' else rules.basic_exemption
    exemption = money(min(allowance, rules.basic_exemption, max(Decimal('0'), taxable)) if mode != 'none' else 0)
    if exemption_remaining is not None:
        exemption = min(exemption, money(exemption_remaining))
    income_tax = money(max(Decimal('0'), taxable - exemption) * rules.income_tax_rate)
    exemption_reason = ('board_member' if board else 'income_line' if basis == 'income_line'
                        else (employee.get('social_tax_minimum_exemption') or None))
    social_base = bases['social_tax']
    shortfall = Decimal(0)
    if exemption_reason is None:
        minimum_base = rules.social_tax_monthly_base
        if period:
            days, days_in_month = employed_days(employee, period)
            if days < days_in_month:
                minimum_base = money(rules.social_tax_monthly_base * days / days_in_month)
        shortfall = max(Decimal(0), minimum_base - bases['social_minimum'])
        social_base += shortfall
    social = money(social_base * rules.social_tax_rate)
    topup = social - money(bases['social_tax'] * rules.social_tax_rate)
    employer_ui = money(bases['ui_employer'] * rules.ui_employer_rate)
    withholding = pension + ui + income_tax + deductions
    if gross - withholding < 0:
        raise ValueError('Payment deductions cannot exceed net pay')
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


def declaration_due_date(period, payment_date=None):
    paid_on = date.fromisoformat(payment_date) if isinstance(payment_date, str) else payment_date
    year, month = (paid_on.year, paid_on.month) if paid_on else map(int, period.split('-'))
    due = date(year + (month == 12), 1 if month == 12 else month + 1, 10)
    from payroll_calendar import is_working_day
    while not is_working_day(due):
        due += timedelta(days=1)
    return due


class PayrollService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    @staticmethod
    def _absence_component_lines(tx, organisation_id, employee, period, absences):
        """Build draft-only statutory absence components with frozen calculation details."""
        from datetime import date

        employee_id = employee.get('employee_id') or employee['id']
        live_employee = tx.one('SELECT * FROM employees WHERE organisation_id=? AND id=?',
                               (organisation_id, employee_id))
        if live_employee:
            employee = employee | live_employee | {'id': employee_id}
        year, month = map(int, period.split('-'))
        first, last = date(year, month, 1), date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        absence_rows = tx.rows('SELECT absence_type,start_date,end_date FROM payroll_absences '
                               'WHERE organisation_id=? AND employee_id=?',
                               (organisation_id, employee['id']))
        settings = {r['absence_type']: bool(r['paid_salary']) for r in tx.rows(
            'SELECT absence_type,paid_salary FROM payroll_absence_type_settings WHERE organisation_id=?',
            (organisation_id,))}
        for row in absence_rows:
            row['wage_paid'] = (row['absence_type'] == 'permitted_absence' and settings.get('permitted_absence', False)
                                or row['absence_type'] not in ('permitted_absence', 'unpaid_leave', 'truancy'))
        approved = tx.rows("SELECT i.*,r.period,r.status FROM pay_run_items i JOIN pay_runs r "
                           "ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id "
                           "WHERE i.organisation_id=? AND i.employee_id=? AND r.status='Approved'",
                           (organisation_id, employee['id']))
        for item in approved:
            item['components'] = tx.rows('SELECT direction,amount,is_wage FROM pay_item_components '
                                         'WHERE organisation_id=? AND item_id=?',
                                         (organisation_id, item['id']))
        history = tx.rows("SELECT h.earning_month AS period,h.wage_total,h.unpaid_absence_days FROM payroll_historical_earnings h "
                          "WHERE h.organisation_id=? AND h.employee_id=? AND h.status='Approved' "
                          "AND NOT EXISTS (SELECT 1 FROM pay_runs r WHERE r.organisation_id=h.organisation_id "
                          "AND r.period=h.earning_month AND r.status='Approved')",
                          (organisation_id, employee['id']))
        components = []
        for absence in absences:
            if absence['absence_type'] != 'sick_leave':
                continue
            start = max(first, date.fromisoformat(absence['start_date']))
            end = min(last, date.fromisoformat(absence['end_date']))
            if start > end:
                continue
            avg = calculate_average_pay(employee, date.fromisoformat(absence['start_date']),
                                        approved_items=approved, historical_earnings=history,
                                        absences=absence_rows)
            breakdown = employer_sick_benefit(avg.average_daily_pay,
                date.fromisoformat(absence['start_date']), start, end)
            breakdown['average'] = avg.as_dict()
            if Decimal(breakdown['amount']) > 0:
                components.append(('employer_sick_pay', Decimal(breakdown['amount']), breakdown))

        employment_end = employee.get('employment_end_date')
        if employment_end and first <= date.fromisoformat(employment_end) <= last:
            end_date = date.fromisoformat(employment_end)
            entitlements = tx.rows('SELECT effective_from,days_per_year FROM payroll_leave_entitlements '
                                   'WHERE organisation_id=? AND employee_id=? AND effective_from<=? ORDER BY effective_from',
                                   (organisation_id, employee['id'], end_date.isoformat()))
            applicable = entitlements[-1] if entitlements else None
            entitlement = Decimal(str(applicable['days_per_year'])) if applicable else Decimal(0)
            taken = Decimal(0)
            for absence in absence_rows:
                if (absence['absence_type'] == 'annual_leave' and absence['start_date'][:4] == str(year)
                        and absence['start_date'] <= end_date.isoformat()):
                    taken += Decimal(str(PayrollAbsenceService._counts(absence['absence_type'],
                        absence['start_date'], min(absence['end_date'], end_date.isoformat()))['leave_days']))
            opening_row = tx.one('SELECT unused_days,extended_unused_days FROM payroll_leave_openings '
                                 'WHERE organisation_id=? AND employee_id=? AND cutover_date<=? AND reviewed_at IS NOT NULL '
                                 'ORDER BY cutover_date DESC LIMIT 1',
                                 (organisation_id, employee['id'], end_date.isoformat()))
            opening = (Decimal(str(opening_row['unused_days'])) + Decimal(str(opening_row['extended_unused_days']))) if opening_row else Decimal(0)
            remaining = max(Decimal(0), Decimal(str(opening)) + entitlement - taken)
            if remaining:
                avg = calculate_average_pay(employee, end_date, approved_items=approved,
                    historical_earnings=history, absences=absence_rows)
                amount = unused_leave_compensation(remaining, avg.average_daily_pay)
                breakdown = {'employment_end_date': end_date.isoformat(), 'entitlement_days': str(entitlement),
                    'opening_unused_days': str(opening), 'taken_annual_leave_days': str(taken),
                    'remaining_leave_days': str(remaining), 'average_daily_pay': str(avg.average_daily_pay),
                    'amount': str(amount), 'average': avg.as_dict(), 'balance_method': 'annual entitlement minus taken leave plus opening unused days'}
                components.append(('unused_leave', amount, breakdown))
        return components

    @staticmethod
    def _save_absence_components(tx, organisation_id, item_id, generated, position):
        for preset, amount, breakdown in generated:
            ptype = tx.one('SELECT * FROM pay_component_types WHERE organisation_id=? AND preset_key=?',
                           (organisation_id, preset))
            if not ptype:
                continue
            fields = ('id','organisation_id','item_id','type_id','position','name','amount','direction',
                      'income_tax','social_tax','ui_employee','ui_employer','funded_pension','social_minimum',
                      'liability_role','is_wage','breakdown_json','is_generated')
            values = (new_id(), organisation_id, item_id, ptype['id'], position, ptype['name'],
                db_number(amount), ptype['direction'], ptype['income_tax'], ptype['social_tax'],
                ptype['ui_employee'], ptype['ui_employer'], ptype['funded_pension'], ptype['social_minimum'],
                ptype['liability_role'], ptype.get('is_wage', 0), json.dumps(breakdown, sort_keys=True), 1)
            tx.execute('INSERT INTO pay_item_components('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')', values)

    def pushes(self, organisation_id, run_id):
        from push_service import PushService
        return PushService(self.db).list(organisation_id, pay_run_id=run_id)

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
            raise ValueError('Pay basis must be monthly, hourly, board fee or income line')
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
            elif basis == 'income_line':
                data['gross_salary'], data['hourly_rate'] = None, None
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
        data['social_tax_minimum_exemption'] = None if basis in ('board_fee', 'income_line') else reason
        start, end = _parse_date(data.get('employment_start_date')), _parse_date(data.get('employment_end_date'))
        if start and end and end < start:
            raise ValueError('Employment dates must be YYYY-MM-DD and the end cannot precede the start')
        data['employment_start_date'] = start.isoformat() if start else None
        data['employment_end_date'] = end.isoformat() if end else None
        return validate_details(data)

    def employees(self, organisation_id):
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            return [self._serialize_employee(row) for row in tx.rows(
                'SELECT * FROM employees WHERE organisation_id=? ORDER BY name,id', (organisation_id,))]

    @staticmethod
    def _serialize_employee(row):
        row['date_of_birth'] = row.get('date_of_birth') or birth_date_from_personal_code(row.get('personal_id'))
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
        period = changes.pop('tax_settings_period', None)
        if period is not None:
            if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', period):
                raise ValueError('Payroll periods must use YYYY-MM')
            rules_for(settlement_date(period))
        fields = ('name', 'email', 'personal_id', 'gross_salary', 'funded_pension_percent',
                  'apply_tax_free_minimum', 'board_member', 'active', 'pay_basis', 'fte', 'hourly_rate',
                  'social_tax_minimum_exemption', 'employment_start_date', 'employment_end_date',
                  'phone', 'iban', 'bank_account_owner', 'address', 'date_of_birth')
        if set(changes) - set(fields):
            raise ValueError('Unknown employee field')
        # Keep the legacy board_member flag and the pay basis in step when only one is sent.
        if 'pay_basis' in changes and 'board_member' not in changes and changes['pay_basis'] in PAY_BASES:
            changes['board_member'] = changes['pay_basis'] == 'board_fee'
        if tx is None:
            with self.db.transaction() as owned_tx:
                return self._save_employee_tx(
                    owned_tx, organisation_id, actor, employee_id, fields, changes, period
                )
        return self._save_employee_tx(tx, organisation_id, actor, employee_id, fields, changes, period)

    def _save_employee_tx(self, tx, organisation_id, actor, employee_id, fields, changes, period=None):
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
            previous_active = bool(data['active'])
            legacy_changes = {k: v for k, v in changes.items() if data.get(k) != v}
            data.update(changes)
        else:
            data = dict(email=None, personal_id=None, apply_tax_free_minimum=False, board_member=False, active=True)
            data.update(changes)
            data.setdefault('funded_pension_percent', 0 if data['board_member'] else 2)
            legacy_changes = changes
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
        EmployeeTaxSettingsService(self.db).legacy_write(
            tx, organisation_id, data | {'id': record_id}, legacy_changes, actor=actor,
            period=period, creating=not employee_id)
        audit(tx, organisation_id, actor, 'payroll.employee.updated' if employee_id else 'payroll.employee.created', 'employee', record_id)
        if employee_id and previous_active != bool(data['active']):
            audit(tx, organisation_id, actor, 'payroll.employee.unarchived' if data['active'] else 'payroll.employee.archived', 'employee', record_id)
        return self._serialize_employee(tx.one('SELECT * FROM employees WHERE organisation_id=? AND id=?', (organisation_id, record_id)))

    def delete_employee(self, organisation_id, employee_id, *, actor):
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            # Serialise with run creation and employee updates before checking history.
            changed = tx.execute('UPDATE employees SET active=active WHERE organisation_id=? AND id=?', (organisation_id, employee_id))
            if changed.rowcount != 1:
                raise KeyError('Employee not found')
            if tx.one('SELECT id FROM pay_run_items WHERE organisation_id=? AND employee_id=?', (organisation_id, employee_id)):
                raise PayrollConflict('This employee has been included in a pay run. Archive the employee instead.')
            tx.execute('DELETE FROM employee_tax_settings WHERE organisation_id=? AND employee_id=?', (organisation_id, employee_id))
            tx.execute('DELETE FROM employees WHERE organisation_id=? AND id=?', (organisation_id, employee_id))
            audit(tx, organisation_id, actor, 'payroll.employee.deleted', 'employee', employee_id)

    def _run(self, tx, organisation_id, run_id):
        run = tx.one('SELECT * FROM pay_runs WHERE organisation_id=? AND id=?', (organisation_id, run_id))
        if not run:
            raise KeyError('Pay run not found')
        if 'settlement_date' in run:
            payout = tx.one("SELECT payout_date FROM payroll_payout_batches WHERE organisation_id=? AND pay_run_id=? "
                            "AND payout_type='salary' AND status!='Cancelled' ORDER BY payout_date,id LIMIT 1",
                            (organisation_id, run_id))
            payday_date = payday_for_period(tx, organisation_id, run['period'])
            run['payment_date'] = settlement_date(run['period'],
                salary_payout_date=payout['payout_date'] if payout else None,
                payday_rule_date=run['settlement_date'] or payday_date).isoformat()
        else:
            run['payment_date'] = settlement_date(run['period']).isoformat()
        run['items'] = tx.rows('SELECT * FROM pay_run_items WHERE organisation_id=? AND pay_run_id=? ORDER BY employee_name,id', (organisation_id, run_id))
        for item in run['items']:
            item['components'] = [serialise(row) for row in tx.rows(
                'SELECT c.*,t.preset_key FROM pay_item_components c JOIN pay_component_types t '
                'ON t.organisation_id=c.organisation_id AND t.id=c.type_id '
                'WHERE c.organisation_id=? AND c.item_id=? ORDER BY c.position,c.id', (organisation_id, item['id']))]
            for component in item['components']:
                if component.get('breakdown_json'):
                    component['breakdown'] = json.loads(component.pop('breakdown_json'))
            for key in (*AMOUNTS, 'gross_salary', 'funded_pension_percent'):
                item[key] = db_number(money(item[key]))
            item['minimum_wage'] = None if item.get('minimum_wage') is None else db_number(money(item['minimum_wage']))
            item['hours'] = None if item.get('hours') is None else db_number(money(item['hours']))
            item['hourly_rate'] = _rate(item.get('hourly_rate'))
            item['fte'] = _fraction(item.get('fte'))
            item['board_member'] = bool(item['board_member'])
        for key in ('total_gross', 'total_net', 'total_employer_cost'):
            run[key] = db_number(money(run[key]))
        due_date = declaration_due_date(run['period'], run['payment_date'])
        run['declaration_due_date'] = due_date.isoformat()
        settlement = tx.one('SELECT posted_batch_id FROM pay_run_settlements WHERE organisation_id=? AND pay_run_id=?', (organisation_id, run_id))
        prepared = tx.one("SELECT id FROM sync_runs WHERE organisation_id=? AND provider='emta' AND object_type='tsd' AND direction='export' AND cursor_before=?", (organisation_id, run_id))
        run['declaration_state'] = 'settled' if settlement else 'prepared' if prepared else 'none'
        run['declaration_batch_id'] = settlement['posted_batch_id'] if settlement else None
        run['declaration_overdue'] = run['status'] == 'Approved' and run['declaration_state'] != 'settled' and due_date < date.today()
        return run

    def runs(self, organisation_id):
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            return [self._run(tx, organisation_id, row['id']) for row in tx.rows(
                'SELECT id FROM pay_runs WHERE organisation_id=? ORDER BY period DESC,id', (organisation_id,))]

    def component_types(self, organisation_id):
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            return [serialise(row) for row in tx.rows('SELECT * FROM pay_component_types WHERE organisation_id=? ORDER BY name,id', (organisation_id,))]

    def save_component_type(self, organisation_id, *, actor, type_id=None, **changes):
        if self.db.dialect == 'postgres':
            metadata_ready = bool(self.db.one("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='pay_component_types' AND column_name='is_wage'"))
        else:
            metadata_ready = 'is_wage' in {row['name'] for row in self.db.rows('PRAGMA table_info(pay_component_types)')}
        has_tsd = ('tsd_payment_type' in {row['name'] for row in self.db.rows('PRAGMA table_info(pay_component_types)')}
                   if self.db.dialect != 'postgres' else bool(self.db.one("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='pay_component_types' AND column_name='tsd_payment_type'")))
        fields = ('name', 'direction', *FLAGS, 'liability_role') + (('is_wage', 'active') if metadata_ready else ()) + (('tsd_payment_type',) if has_tsd else ())
        if set(changes) - set(fields):
            raise ValueError('Unknown payment component field')
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            if type_id:
                data = tx.one('SELECT * FROM pay_component_types WHERE organisation_id=? AND id=?', (organisation_id, type_id))
                if not data:
                    raise KeyError('Payment type not found')
            else:
                data = dict(name='', direction='income', liability_role='PAYROLL_DEDUCTION', tsd_payment_type=10,
                            is_wage=True, active=True, **{key: False for key in FLAGS})
            data.update(changes)
            self._component_values(data)
            type_id = type_id or new_id()
            tx.execute('INSERT INTO pay_component_types(id,organisation_id,' + ','.join(fields) + ') VALUES (' +
                       ','.join('?' for _ in range(len(fields)+2)) + ') ON CONFLICT(id) DO UPDATE SET ' +
                       ','.join(f'{field}=excluded.{field}' for field in fields),
                       (type_id, organisation_id, *(data[field] for field in fields)))
            audit(tx, organisation_id, actor, 'payroll.component_type.saved', 'pay_component_type', type_id)
            return serialise(tx.one('SELECT * FROM pay_component_types WHERE organisation_id=? AND id=?', (organisation_id, type_id)))

    @staticmethod
    def _component_values(data):
        if not isinstance(data.get('name'), str) or not data['name'].strip() or len(data['name']) > 180:
            raise ValueError('Payment name must contain 1 to 180 characters')
        data['name'] = data['name'].strip()
        if data.get('direction') not in ('income', 'deduction'):
            raise ValueError('Payment direction must be income or deduction')
        if data.get('liability_role') not in ROLES or not data['liability_role'].startswith(('PAYROLL_BAILIFF', 'PAYROLL_DEDUCTION')):
            raise ValueError('Choose a payroll deduction liability role')
        for key in FLAGS:
            if type(data.get(key)) not in (bool, int) or data[key] not in (0, 1):
                raise ValueError('Payment levy flags must be booleans')
            data[key] = int(data[key])
        for key in ('is_wage', 'active'):
            if type(data.get(key)) not in (bool, int) or data[key] not in (0, 1):
                raise ValueError('Payment type metadata must be boolean')
            data[key] = int(data[key])
        if 'tsd_payment_type' in data and (type(data['tsd_payment_type']) is not int or data['tsd_payment_type'] not in (10,11,12,13,14,15,16,17,21,24,32,33)):
            raise ValueError('Choose a supported TSD payment type')
        # All flags remain editable snapshots. They affect income lines only;
        # deduction lines are explicitly net withholdings, never tax relief.
        return data

    def update_item(self, organisation_id, run_id, item_id, *, actor, hours=None, components=None, gross_salary=None, tx=None):
        if tx is None:
            with self.db.transaction() as owned_tx:
                return self.update_item(organisation_id, run_id, item_id, actor=actor, hours=hours, components=components, gross_salary=gross_salary, tx=owned_tx)
        claimed = tx.execute("UPDATE pay_runs SET notes=notes WHERE organisation_id=? AND id=? AND status='Draft'", (organisation_id, run_id))
        run = self._run(tx, organisation_id, run_id)
        if claimed.rowcount != 1:
            raise PayrollConflict('Only draft pay runs can be edited')
        item = next((item for item in run['items'] if item['id'] == item_id), None)
        if not item:
            raise KeyError('Pay run item not found')
        is_adjustable = run.get('kind', 'regular') in {'correction', 'supplementary'}
        component_overrides = {}
        if gross_salary is not None:
            if item['pay_basis'] not in ('monthly', 'board_fee'):
                raise ValueError('Gross salary can be edited only for monthly or board fee employees')
            try:
                gross = decimal(gross_salary)
                if not gross.is_finite() or gross < 0 or (gross == 0 and not is_adjustable) or gross > Decimal('9999999999.99'):
                    raise ValueError('Gross salary must be positive and fit NUMERIC(12,2)')
                if money(gross) <= 0 and not is_adjustable:
                    raise ValueError('Gross salary must be at least 0.01')
            except InvalidOperation as exc:
                raise ValueError('Invalid gross salary') from exc
            item['gross_salary'] = db_number(money(gross))
        if hours is not None and item['pay_basis'] != 'hourly':
            raise ValueError('Hours can be edited only for hourly employees')
        worked = self._hours(dict(id=item_id, name=item['employee_name']), {item_id: hours if hours is not None else item['hours']}) if item['pay_basis'] == 'hourly' else None
        if tx.dialect == 'postgres':
            component_columns = {row['column_name'] for row in tx.rows(
                "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='pay_item_components'")}
        else:
            component_columns = {row['name'] for row in tx.rows('PRAGMA table_info(pay_item_components)')}
        generated_column_ready = 'is_generated' in component_columns
        breakdown_column_ready = 'breakdown_json' in component_columns
        if components is not None:
            if len(components) > 100:
                raise ValueError('At most 100 payment lines are allowed per employee')
            if generated_column_ready:
                tx.execute('DELETE FROM pay_item_components WHERE organisation_id=? AND item_id=? AND is_generated=1',
                           (organisation_id, item_id))
                tx.execute('DELETE FROM pay_item_components WHERE organisation_id=? AND item_id=? AND is_generated=0',
                           (organisation_id, item_id))
            elif breakdown_column_ready:
                tx.execute('DELETE FROM pay_item_components WHERE organisation_id=? AND item_id=? AND breakdown_json IS NOT NULL',
                           (organisation_id, item_id))
                tx.execute('DELETE FROM pay_item_components WHERE organisation_id=? AND item_id=? AND breakdown_json IS NULL',
                           (organisation_id, item_id))
            else:
                tx.execute('DELETE FROM pay_item_components WHERE organisation_id=? AND item_id=?',
                           (organisation_id, item_id))
            for position, line in enumerate(components):
                allowed = {'type_id', 'name', 'amount', 'direction', 'liability_role', 'is_generated', *FLAGS}
                if set(line) - allowed:
                    raise ValueError('Unknown payment component field')
                data = tx.one('SELECT * FROM pay_component_types WHERE organisation_id=? AND id=?', (organisation_id, line.get('type_id')))
                if not data:
                    raise KeyError('Payment type not found')
                if line.get('is_generated'):
                    if data.get('preset_key') == 'unused_leave':
                        component_overrides['unused_leave'] = decimal(line['amount'])
                    continue
                data.setdefault('is_wage', True)
                data.setdefault('active', True)
                data.update(line)
                if data.get('preset_key') == 'unused_leave':
                    component_overrides[data['preset_key']] = decimal(data['amount'])
                self._component_values(data)
                try:
                    amount = decimal(data.get('amount'))
                    if not amount.is_finite() or not amount or abs(amount) > Decimal('9999999999.99') or amount != money(amount) or (data['direction'] == 'deduction' and amount < 0):
                        raise ValueError('Enter a non-zero payment amount with at most two decimals')
                    if data.get('preset_key') == 'unused_leave' and amount <= 0:
                        raise ValueError('Unused-leave compensation must remain positive')
                except InvalidOperation as exc:
                    raise ValueError('Enter a non-zero payment amount with at most two decimals') from exc
                if tx.dialect == 'postgres':
                    metadata_ready = bool(tx.one("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='pay_item_components' AND column_name='is_wage'"))
                else:
                    metadata_ready = 'is_wage' in {row['name'] for row in tx.rows('PRAGMA table_info(pay_item_components)')}
                if tx.dialect == 'postgres':
                    has_tsd = bool(tx.one("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='pay_item_components' AND column_name='tsd_payment_type'"))
                else:
                    has_tsd = 'tsd_payment_type' in {row['name'] for row in tx.rows('PRAGMA table_info(pay_item_components)')}
                fields = ('id', 'organisation_id', 'item_id', 'type_id', 'position', 'name', 'amount', 'direction', *FLAGS, 'liability_role') + (('is_wage',) if metadata_ready else ()) + (('tsd_payment_type',) if has_tsd else ())
                values = (new_id(), organisation_id, item_id, data['id'], position, data['name'], db_number(amount), data['direction'], *(data[key] for key in FLAGS), data['liability_role']) + ((data['is_wage'],) if metadata_ready else ()) + ((data.get('tsd_payment_type', 10),) if has_tsd else ())
                tx.execute('INSERT INTO pay_item_components(' + ','.join(fields) + ') VALUES (' + ','.join('?' for _ in fields) + ')', values)
        if generated_column_ready:
            tx.execute('DELETE FROM pay_item_components WHERE organisation_id=? AND item_id=? AND is_generated=1',
                       (organisation_id, item_id))
        elif breakdown_column_ready:
            tx.execute('DELETE FROM pay_item_components WHERE organisation_id=? AND item_id=? AND breakdown_json IS NOT NULL',
                       (organisation_id, item_id))
        if tx.dialect == 'postgres':
            absence_schema_ready = bool(tx.one("SELECT 1 FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='payroll_absence_run_items'"))
        else:
            absence_schema_ready = bool(tx.one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='payroll_absence_run_items'"))
        if absence_schema_ready:
            frozen_absences = tx.rows('SELECT a.* FROM payroll_absence_run_items x JOIN payroll_absences a '
                'ON a.organisation_id=x.organisation_id AND a.id=x.absence_id '
                'WHERE x.organisation_id=? AND x.pay_run_id=? AND x.employee_id=?',
                (organisation_id, run_id, item['employee_id']))
            generated = self._absence_component_lines(tx, organisation_id, item, run['period'], frozen_absences)
        else:
            generated = []
        for index, (preset, amount, breakdown) in enumerate(generated):
            if preset in component_overrides:
                override = money(component_overrides[preset])
                generated[index] = (preset, override, breakdown | {'accountant_override': db_number(override)})
        next_position = tx.scalar('SELECT COALESCE(MAX(position),-1)+1 FROM pay_item_components WHERE organisation_id=? AND item_id=?',
                                  (organisation_id, item_id)) or 0
        self._save_absence_components(tx, organisation_id, item_id, generated, next_position)
        lines = tx.rows('SELECT * FROM pay_item_components WHERE organisation_id=? AND item_id=? ORDER BY position', (organisation_id, item_id))
        context = tx.one('SELECT * FROM pay_item_context WHERE organisation_id=? AND item_id=?', (organisation_id, item_id))
        if not context:
            raise ValueError('Pay run calculation snapshot is missing')
        has_settlement_date = 'settlement_date' in run
        pay_date = date.fromisoformat(run['settlement_date']) if run.get('settlement_date') else settlement_date(run['period'])
        used_exemption = (monthly_exemption_used(tx, organisation_id, item['employee_id'], pay_date.strftime('%Y-%m'))
                          if has_settlement_date else Decimal('0'))
        exemption_cap = remaining_monthly_exemption(
            context.get('tax_free_mode') or ('maximum' if context.get('apply_tax_free_minimum') else 'none'),
            context.get('tax_free_amount'), rules_for(pay_date).basic_exemption, used_exemption)
        amounts = calculate_pay(item | context, period=run['period'], hours=worked, components=lines,
                                settlement_on=pay_date, exemption_remaining=exemption_cap,
                                allow_zero_monthly=(item['pay_basis'] == 'monthly' and
                                    (item.get('worked_days') == 0 or is_adjustable and money(item['gross_salary']) == 0)))
        if amounts['gross'] > Decimal('9999999999.99') or any(amounts[key] > Decimal('9999999999.99') for key in AMOUNTS if key != 'employer_cost'):
            raise ValueError('Payment totals exceed the supported amount')
        monthly_minimum, hourly_minimum = minimum_wage(run['period'])
        required = Decimal(0)
        if item['pay_basis'] == 'monthly':
            required = money(item.get('minimum_wage') or monthly_minimum * _fte(item.get('fte')))
        elif item['pay_basis'] == 'hourly':
            required = money(decimal(item.get('minimum_wage') or hourly_minimum) * worked)
        if amounts['gross'] < required and not is_adjustable:
            raise ValueError('Payment components must preserve the minimum wage')
        tx.execute('UPDATE pay_run_items SET ' + ','.join(f'{key}=?' for key in AMOUNTS) + ',hours=?,gross_salary=? WHERE organisation_id=? AND id=?',
                   (*(db_number(amounts[key]) for key in AMOUNTS), None if worked is None else db_number(worked), item['gross_salary'], organisation_id, item_id))
        refreshed = self._run(tx, organisation_id, run_id)
        totals = [sum((money(row[key]) for row in refreshed['items']), Decimal(0)) for key in ('gross', 'net', 'employer_cost')]
        tx.execute('UPDATE pay_runs SET total_gross=?,total_net=?,total_employer_cost=? WHERE organisation_id=? AND id=?',
                   (*(db_number(value) for value in totals), organisation_id, run_id))
        audit(tx, organisation_id, actor, 'payroll.item.updated', 'pay_run_item', item_id)
        return self._run(tx, organisation_id, run_id)

    def posting_mappings(self, organisation_id):
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            return [dict(role=role, account_code=self._posting_account(tx, organisation_id, role)['code']) for role in ROLES]

    def save_posting_mapping(self, organisation_id, role, account_code, *, actor):
        if role not in ROLES:
            raise ValueError('Unknown payroll posting role')
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            account = tx.one('SELECT * FROM accounts WHERE organisation_id=? AND code=? AND active=1', (organisation_id, account_code))
            expected = 'Expense' if role in ('PAYROLL_SALARY', 'PAYROLL_SOCIAL', 'PAYROLL_UI', 'PAYROLL_VACATION_RESERVE_EXPENSE') else 'Liability'
            if not account or account['account_type'] != expected:
                raise ValueError('Choose an active account of the required payroll account type')
            provider, now = 'payroll:' + role.lower(), utc_now()
            # A provider key per role permits shared target codes (social tax/pension).
            mapping = tx.one('SELECT id FROM account_mappings WHERE organisation_id=? AND provider=?', (organisation_id, provider))
            if mapping:
                tx.execute("UPDATE account_mappings SET local_account_code=?,external_account_code=?,status='Confirmed',updated_at=? WHERE organisation_id=? AND id=?", (account_code, account_code, now, organisation_id, mapping['id']))
            else:
                tx.execute("INSERT INTO account_mappings(id,organisation_id,provider,local_account_code,external_account_code,status,created_at,updated_at) VALUES (?,?,?,?,?,'Confirmed',?,?)", (new_id(), organisation_id, provider, account_code, account_code, now, now))
            audit(tx, organisation_id, actor, 'payroll.mapping.saved', 'account', account['id'], {'role': role})

    @staticmethod
    def _posting_account(tx, organisation_id, role):
        mapping = tx.one("SELECT local_account_code FROM account_mappings WHERE organisation_id=? AND provider=? AND status='Confirmed'", (organisation_id, 'payroll:' + role.lower()))
        if mapping:
            account = tx.one('SELECT * FROM accounts WHERE organisation_id=? AND code=? AND active=1', (organisation_id, mapping['local_account_code']))
        else:
            account = tx.one('SELECT * FROM accounts WHERE organisation_id=? AND system_role=? AND active=1', (organisation_id, role))
        if not account:
            raise ValueError('A payroll posting account is missing or inactive')
        expected = 'Expense' if role in ('PAYROLL_SALARY', 'PAYROLL_SOCIAL', 'PAYROLL_UI', 'PAYROLL_VACATION_RESERVE_EXPENSE') else 'Liability'
        if account['account_type'] != expected:
            raise ValueError('Choose an active account of the required payroll account type')
        return account

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

    def create_run(self, organisation_id, *, period, actor, hours=None, show_leave_balance=False, tx=None):
        if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', period):
            raise ValueError('Payroll periods must use YYYY-MM')
        if tx is None:
            with self.db.transaction() as owned_tx:
                return self.create_run(organisation_id, period=period, actor=actor, hours=hours,
                                       show_leave_balance=show_leave_balance, tx=owned_tx)
        self._organisation(tx, organisation_id)
        pay_date = settlement_date(period, payday_rule_date=payday_for_period(tx, organisation_id, period))
        rules_for(pay_date)
        run_id = new_id()
        result = tx.execute("INSERT INTO pay_runs(id,organisation_id,period,total_gross,total_net,total_employer_cost,created_by,created_at,settlement_date,show_leave_balance) VALUES (?,?,?,0,0,0,?,?,?,?) ON CONFLICT DO NOTHING", (run_id, organisation_id, period, actor, utc_now(), pay_date.isoformat(), int(bool(show_leave_balance))))
        if result.rowcount != 1:
            raise PayrollConflict(f'A pay run already exists for {period}')
        employees = [e for e in tx.rows('SELECT * FROM employees WHERE organisation_id=? AND active=1 ORDER BY id', (organisation_id,))
                     if employed_days(e, period)[0] > 0]
        if not employees:
            raise ValueError('A pay run requires at least one active employee')
        monthly_minimum, hourly_minimum = minimum_wage(period)
        totals = dict(gross=Decimal(0), net=Decimal(0), employer_cost=Decimal(0))
        columns = ('id', 'pay_run_id', 'organisation_id', 'employee_id', 'employee_name', 'employee_personal_id', 'gross_salary',
                   'board_member', 'funded_pension_percent', 'pay_basis', 'tsd_payment_type', 'fte', 'hourly_rate', 'hours',
                   'minimum_wage', 'social_tax_minimum_exemption', *AMOUNTS,
                   'worked_days', 'norm_days', 'absence_working_days')
        for employee in employees:
            election = resolve_tax_settings(tx, organisation_id, employee, pay_date)
            employee = employee | election
            employee_for_average = employee
            basis, fte, worked, required = pay_basis(employee), _fte(employee.get('fte')), None, None
            if basis == 'monthly':
                # Part-time: the monthly minimum wage is pro-rated by the work-time fraction.
                agreement_minimum = money(monthly_minimum * fte)
                if money(employee['gross_salary']) < agreement_minimum:
                    suffix = f" (EUR {monthly_minimum:.2f} × {_fraction(fte)})" if fte != 1 else ''
                    raise ValueError(f"{employee['name']}: gross salary must be at least EUR {agreement_minimum:.2f}{suffix}")
            elif basis == 'hourly':
                required = hourly_minimum
                if decimal(employee['hourly_rate']) < hourly_minimum:
                    raise ValueError(f"{employee['name']}: hourly rate must be at least EUR {hourly_minimum:.2f}")
                worked = self._hours(employee, hours)
            absence_snapshot = PayrollAbsenceService(self.db).freeze_for_run(
                tx, organisation_id, employee['id'], run_id, period)
            worked_days = norm_days_snapshot = None
            if basis == 'monthly':
                norm_days_snapshot = absence_snapshot['norm_days']
                worked_days = absence_snapshot['worked_days']
                employee = employee | {'gross_salary': db_number(money(
                    decimal(employee['gross_salary']) * Decimal(worked_days) / Decimal(norm_days_snapshot)
                    if norm_days_snapshot else Decimal(0)))}
                required = money(agreement_minimum * Decimal(worked_days) / Decimal(norm_days_snapshot)
                                 if norm_days_snapshot else Decimal(0))
            generated = self._absence_component_lines(tx, organisation_id, employee_for_average, period,
                                                       absence_snapshot['absences'])
            generated_lines = []
            for preset, amount, _ in generated:
                ptype = tx.one('SELECT * FROM pay_component_types WHERE organisation_id=? AND preset_key=?',
                               (organisation_id, preset))
                if ptype:
                    generated_lines.append(ptype | {'amount': db_number(amount), 'direction': ptype['direction']})
            used_exemption = monthly_exemption_used(tx, organisation_id, employee['id'], pay_date.strftime('%Y-%m'))
            exemption_cap = remaining_monthly_exemption(
                election['tax_free_mode'], election.get('tax_free_amount'),
                rules_for(pay_date).basic_exemption, used_exemption)
            amounts = calculate_pay(employee, period=period, hours=worked, components=generated_lines, settlement_on=pay_date,
                                    exemption_remaining=exemption_cap,
                                    allow_zero_monthly=basis == 'monthly' and worked_days == 0)
            item_id = new_id()
            values = (item_id, run_id, organisation_id, employee['id'], employee['name'], employee.get('personal_id'),
                      db_number(amounts['gross'] if basis in ('hourly', 'income_line') else money(employee['gross_salary'])),
                      int(basis == 'board_fee'), db_number(decimal(employee['funded_pension_percent'])), basis,
                      {'monthly': 10, 'hourly': 10, 'board_fee': 21, 'income_line': 17}[basis],
                      db_number(four_dp(fte)), None if basis != 'hourly' else db_number(four_dp(employee['hourly_rate'])),
                      None if worked is None else db_number(worked), None if required is None else db_number(money(required)),
                      amounts['social_tax_minimum_exemption'])
            tx.execute('INSERT INTO pay_run_items('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',
                       values+tuple(db_number(amounts[k]) for k in AMOUNTS)+
                       (worked_days, norm_days_snapshot, absence_snapshot['absence_working_days']))
            self._save_absence_components(tx, organisation_id, item_id, generated, 0)
            context_fields = ('tax_free_mode', 'tax_free_amount', 'unemployment_applies',
                              'tax_free_setting_id', 'pension_setting_id', 'unemployment_setting_id')
            tx.execute('INSERT INTO pay_item_context(organisation_id,item_id,apply_tax_free_minimum,employment_start_date,employment_end_date,' + ','.join(context_fields) + ') VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (organisation_id, item_id, int(employee['apply_tax_free_minimum']), employee.get('employment_start_date'), employee.get('employment_end_date')) + tuple(election[k] for k in context_fields))
            for key in totals:
                totals[key] += amounts[key]
        tx.execute('UPDATE pay_runs SET total_gross=?,total_net=?,total_employer_cost=? WHERE organisation_id=? AND id=?', tuple(db_number(totals[k]) for k in totals)+(organisation_id, run_id))
        audit(tx, organisation_id, actor, 'payroll.drafted', 'pay_run', run_id, {'period': period})
        return self._run(tx, organisation_id, run_id)

    def create_correction(self, organisation_id, original_run_id, *, actor):
        """Create an editable copy of an approved regular payroll run."""
        with self.db.transaction() as tx:
            locked = tx.execute("UPDATE pay_runs SET notes=notes WHERE organisation_id=? AND id=? AND status='Approved'",
                                (organisation_id, original_run_id))
            if locked.rowcount != 1:
                raise KeyError('Pay run not found')
            original = tx.one('SELECT * FROM pay_runs WHERE organisation_id=? AND id=?',
                              (organisation_id, original_run_id))
            if not original:
                raise KeyError('Pay run not found')
            if original.get('kind', 'regular') != 'regular' or original['status'] != 'Approved':
                raise PayrollConflict('Corrections require an approved regular pay run')
            existing = tx.one("SELECT id FROM pay_runs WHERE organisation_id=? AND original_run_id=? AND kind='correction' AND status='Draft'",
                              (organisation_id, original_run_id))
            if existing:
                raise PayrollConflict('A draft correction already exists for this pay run')
            run_id = new_id()
            tx.execute("INSERT INTO pay_runs(id,organisation_id,period,total_gross,total_net,total_employer_cost,created_by,created_at,settlement_date,show_leave_balance,kind,original_run_id) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?, 'correction',?)",
                       (run_id, organisation_id, original['period'], 0, 0, 0, actor, utc_now(),
                        original.get('settlement_date'), original.get('show_leave_balance', 0), original_run_id))
            for source in tx.rows('SELECT * FROM pay_run_items WHERE organisation_id=? AND pay_run_id=? ORDER BY employee_id',
                                  (organisation_id, original_run_id)):
                item_id = new_id()
                values = dict(source)
                values.update(id=item_id, pay_run_id=run_id)
                self._insert_copied_row(tx, 'pay_run_items', values)
                for table, key in (('pay_item_context', 'item_id'), ('pay_item_components', 'item_id')):
                    for child in tx.rows(f'SELECT * FROM {table} WHERE organisation_id=? AND item_id=?',
                                         (organisation_id, source['id'])):
                        copied = dict(child)
                        copied[key] = item_id
                        if 'id' in copied:
                            copied['id'] = new_id()
                        self._insert_copied_row(tx, table, copied)
            tx.execute('UPDATE pay_runs SET total_gross=?,total_net=?,total_employer_cost=? WHERE organisation_id=? AND id=?',
                       (original['total_gross'], original['total_net'], original['total_employer_cost'], organisation_id, run_id))
            audit(tx, organisation_id, actor, 'payroll.correction.drafted', 'pay_run', run_id,
                  {'original_run_id': original_run_id})
            return self._run(tx, organisation_id, run_id)

    def create_supplementary(self, organisation_id, original_run_id, employee_ids, *, actor):
        """Create a blank supplementary run for selected employees in an approved period."""
        with self.db.transaction() as tx:
            original = tx.one('SELECT * FROM pay_runs WHERE organisation_id=? AND id=?',
                              (organisation_id, original_run_id))
            if not original:
                raise KeyError('Pay run not found')
            if original['status'] != 'Approved' or original.get('kind', 'regular') != 'regular':
                raise PayrollConflict('Supplementary runs require an approved regular pay run')
            source_items = {row['employee_id']: row for row in tx.rows(
                'SELECT * FROM pay_run_items WHERE organisation_id=? AND pay_run_id=?',
                (organisation_id, original_run_id))}
            selected = list(dict.fromkeys(employee_ids))
            if not selected or set(selected) - source_items.keys():
                raise ValueError('Choose employees included in the approved pay run')
            run_id = new_id()
            tx.execute("INSERT INTO pay_runs(id,organisation_id,period,total_gross,total_net,total_employer_cost,created_by,created_at,settlement_date,show_leave_balance,kind,original_run_id) "
                       "VALUES (?,?,?,0,0,0,?,?,?,?, 'supplementary',?)",
                       (run_id, organisation_id, original['period'], actor, utc_now(),
                        original.get('settlement_date'), original.get('show_leave_balance', 0), original_run_id))
            for employee_id in selected:
                source = source_items[employee_id]
                item_id = new_id()
                values = dict(source)
                values.update(id=item_id, pay_run_id=run_id, gross_salary=0)
                values.update({key: 0 for key in AMOUNTS})
                self._insert_copied_row(tx, 'pay_run_items', values)
                for context in tx.rows('SELECT * FROM pay_item_context WHERE organisation_id=? AND item_id=?',
                                       (organisation_id, source['id'])):
                    copied = dict(context)
                    copied['item_id'] = item_id
                    self._insert_copied_row(tx, 'pay_item_context', copied)
            audit(tx, organisation_id, actor, 'payroll.supplementary.drafted', 'pay_run', run_id,
                  {'original_run_id': original_run_id, 'employee_ids': selected})
            return self._run(tx, organisation_id, run_id)

    @staticmethod
    def _insert_copied_row(tx, table, values):
        columns = tuple(values)
        tx.execute(f'INSERT INTO {table} (' + ','.join(columns) + ') VALUES (' +
                   ','.join('?' for _ in columns) + ')', tuple(values[column] for column in columns))

    def approve(self, organisation_id, run_id, *, actor):
        from web import i18n
        with self.db.transaction() as tx:
            # Use the same employee lock order as election writes before a
            # draft's source rows become protected by approval.
            for row in tx.rows('SELECT employee_id FROM pay_run_items WHERE organisation_id=? AND pay_run_id=? ORDER BY employee_id',
                               (organisation_id, run_id)):
                tx.execute('UPDATE employees SET active=active WHERE organisation_id=? AND id=?',
                           (organisation_id, row['employee_id']))
            # Conditional write serializes concurrent approvals on SQLite and PostgreSQL.
            claimed = tx.execute("UPDATE pay_runs SET status='Approved',approved_at=? WHERE organisation_id=? AND id=? AND status='Draft'", (utc_now(), organisation_id, run_id))
            run = self._run(tx, organisation_id, run_id)
            if claimed.rowcount != 1:
                raise PayrollConflict('Pay run is already approved')
            correction = run.get('kind', 'regular') == 'correction'
            if correction:
                original_id = run.get('original_run_id')
                original = tx.one("SELECT * FROM pay_runs WHERE organisation_id=? AND id=? AND status='Approved' AND kind='regular'",
                                  (organisation_id, original_id))
                if not original:
                    raise PayrollConflict('The approved original pay run is unavailable')
                prior = tx.one("SELECT id FROM pay_runs WHERE organisation_id=? AND original_run_id=? AND kind='correction' AND status='Approved' AND id<>? ORDER BY approved_at DESC,id DESC LIMIT 1",
                               (organisation_id, original_id, run_id))
                baseline_run = self._run(tx, organisation_id, prior['id'] if prior else original_id)
                baseline = {item['employee_id']: item for item in baseline_run['items']}
                if set(baseline) != {item['employee_id'] for item in run['items']}:
                    raise PayrollConflict('Correction employees must match the original pay run')
                deltas = {key: sum((decimal(item[key]) - decimal(baseline[item['employee_id']][key])
                                    for item in run['items']), Decimal(0)) for key in AMOUNTS}
                if any(money(item['gross']) < 0 for item in run['items']):
                    raise ValueError('Correction gross pay cannot be negative')
            if not correction and any(money(item['gross']) <= 0 and not (item['pay_basis'] == 'monthly' and item.get('worked_days') == 0)
                   for item in run['items']):
                raise ValueError('Every employee requires positive gross pay before approval')
            from payroll_tsd_breakdown import calculate_tsd_breakdown, freeze_tsd_breakdown
            from payroll_tsd_breakdown import LINE_FIELDS
            from payroll_tsd_types import payment_type
            for item in run['items']:
                context = tx.one('SELECT * FROM pay_item_context WHERE organisation_id=? AND item_id=?',
                                 (organisation_id, item['id']))
                if not context:
                    raise ValueError('Pay run calculation snapshot is missing')
                if correction:
                    current_lines = calculate_tsd_breakdown(item=item, components=item['components'], context=context)
                    prior_rows = tx.rows(
                        "SELECT l.* FROM pay_item_tsd_lines l JOIN pay_run_items i "
                        "ON i.organisation_id=l.organisation_id AND i.id=l.source_id "
                        "JOIN pay_runs p ON p.organisation_id=i.organisation_id AND p.id=i.pay_run_id "
                        "WHERE p.organisation_id=? AND i.employee_id=? AND "
                        "(p.id=? OR (p.original_run_id=? AND p.kind='correction' AND p.status='Approved'))",
                        (organisation_id, item['employee_id'], original_id, original_id))
                    previous = {}
                    for row in prior_rows:
                        record = previous.setdefault(row['payment_type'], {
                            'payment_type': row['payment_type'], 'payment_type_name': row['payment_type_name']})
                        for field in LINE_FIELDS[1:]:
                            record[field] = record.get(field, Decimal(0)) + decimal(row[field])
                    current_by_type = {row['payment_type']: row for row in current_lines}
                    delta_lines = []
                    for code in sorted(set(previous) | set(current_by_type)):
                        current_line = current_by_type.get(code, {'payment_type': code, 'amount': Decimal(0),
                            **{field: Decimal(0) for field in LINE_FIELDS[2:]}})
                        previous_line = previous.get(code, {'payment_type': code, 'amount': Decimal(0),
                            **{field: Decimal(0) for field in LINE_FIELDS[2:]}})
                        delta = {'payment_type': code,
                                 'payment_type_name': payment_type(code).name}
                        for field in LINE_FIELDS[1:]:
                            delta[field] = decimal(current_line.get(field, 0)) - decimal(previous_line.get(field, 0))
                        delta_lines.append(delta)
                    freeze_tsd_breakdown(tx, organisation_id, 'pay_run_item', item['id'],
                        item=item, components=item['components'], context=context, records=delta_lines)
                else:
                    freeze_tsd_breakdown(tx, organisation_id, 'pay_run_item', item['id'],
                                         item=item, components=item['components'], context=context)
            snapshot_totals = {k: sum((decimal(i[k]) for i in run['items']), Decimal(0)) for k in AMOUNTS}
            totals = deltas if correction else snapshot_totals
            memo = f"Payroll correction {run['period']}" if correction else f"Payroll {run['period']}"
            # The social tax minimum shortfall is an employer cost on the existing social-tax
            # accounts, posted as its own line so the top-up is visible in the ledger.
            topup = totals['social_tax_minimum_topup']
            topup_memo = f"{i18n.t('workspace.Social tax minimum top-up', 'et')} {run['period']}"
            deductions = {role: sum((money(c['amount']) for item in run['items'] for c in item['components']
                                    if c['direction'] == 'deduction' and c['liability_role'] == role), Decimal(0))
                          for role in ('PAYROLL_BAILIFF', 'PAYROLL_DEDUCTION')}
            if correction:
                deductions = {role: sum((money(c['amount']) for item in run['items'] for c in item['components']
                    if c['direction'] == 'deduction' and c['liability_role'] == role), Decimal(0)) -
                    sum((money(c['amount']) for item in baseline_run['items'] for c in item['components']
                    if c['direction'] == 'deduction' and c['liability_role'] == role), Decimal(0))
                    for role in ('PAYROLL_BAILIFF', 'PAYROLL_DEDUCTION')}
            postings = [('PAYROLL_SALARY', totals['gross'], True, memo),
                        ('PAYROLL_SALARY_PAYABLE', totals['gross'], False, memo),
                        ('PAYROLL_SALARY_PAYABLE', totals['withholding_total'], True, memo),
                        ('PAYROLL_INCOME_WITHHELD', totals['income_tax'], False, memo),
                        ('PAYROLL_PENSION_WITHHELD', totals['funded_pension'], False, memo),
                        ('PAYROLL_UI_ACCRUED', totals['ui_employee'], False, memo),
                        *((role, value, False, memo) for role, value in deductions.items()),
                        ('PAYROLL_SOCIAL', totals['social_tax']-topup, True, memo),
                        ('PAYROLL_SOCIAL_ACCRUED', totals['social_tax']-topup, False, memo),
                        ('PAYROLL_SOCIAL', topup, True, topup_memo),
                        ('PAYROLL_SOCIAL_ACCRUED', topup, False, topup_memo),
                        ('PAYROLL_UI', totals['ui_employer'], True, memo),
                        ('PAYROLL_UI_ACCRUED', totals['ui_employer'], False, memo)]
            accounts = {role: self._posting_account(tx, organisation_id, role) for role in ROLES}
            for role, account in accounts.items():
                tx.execute('INSERT INTO pay_run_posting_accounts(organisation_id,pay_run_id,role,account_id) VALUES (?,?,?,?)',
                           (organisation_id, run_id, role, account['id']))
            source_id = original_id if correction else run_id
            lines = [PostingLine(accounts[role]['id'], debit=value if debit else Decimal(0), credit=Decimal(0) if debit else value,
                                 memo=line_memo, source_line_type='pay_run', source_line_id=source_id)
                     for role, value, debit, line_memo in postings if value]
            if correction:
                lines = [PostingLine(line.account_id,
                    debit=abs(line.debit or line.credit) if (line.debit > 0 or line.credit < 0) else Decimal(0),
                    credit=abs(line.credit or line.debit) if (line.credit > 0 or line.debit < 0) else Decimal(0),
                    memo=line.memo, source_line_type=line.source_line_type, source_line_id=line.source_line_id)
                    for line in lines]
            year, month = map(int, run['period'].split('-'))
            batch = LedgerService(self.db).post(organisation_id=organisation_id, voucher_type='payroll', voucher_id=run_id,
                voucher_code=f"PAY-{run['period']}{'-COR' if correction else ''}", posting_date=f"{run['period']}-{calendar.monthrange(year,month)[1]}",
                lines=lines, actor=actor, currency='EUR', tx=tx)
            tx.execute('UPDATE pay_runs SET posted_batch_id=?,total_gross=?,total_net=?,total_employer_cost=? WHERE organisation_id=? AND id=?',
                       (batch['id'], db_number(snapshot_totals['gross']), db_number(snapshot_totals['net']), db_number(snapshot_totals['employer_cost']), organisation_id, run_id))
            audit(tx, organisation_id, actor, 'payroll.approved', 'pay_run', run_id, {'posted_batch_id': batch['id']})
            return self._run(tx, organisation_id, run_id)

    def settle_declaration(self, organisation_id, run_id, *, actor):
        """Explicit bureau reclassification, dated the following month's 10th.

        Debit the frozen accrual accounts, even if mappings have since changed.
        This records a liability reclassification, not a bank payment or submission.
        """
        with self.db.transaction() as tx:
            run = self._run(tx, organisation_id, run_id)
            self._organisation(tx, organisation_id)
            if run['status'] != 'Approved':
                raise PayrollConflict('Only approved pay runs can be settled')
            claimed = tx.execute('INSERT INTO pay_run_settlements(organisation_id,pay_run_id) VALUES (?,?) ON CONFLICT DO NOTHING', (organisation_id, run_id))
            if claimed.rowcount != 1:
                raise PayrollConflict('The declaration has already been settled')
            totals = {key: sum((money(item[key]) for item in run['items']), Decimal(0)) for key in AMOUNTS}
            frozen = {row['role']: row['account_id'] for row in tx.rows('SELECT * FROM pay_run_posting_accounts WHERE organisation_id=? AND pay_run_id=?', (organisation_id, run_id))}
            # Historical runs used combined liabilities. Debit their original accounts;
            # never re-post or rewrite an existing salary batch during migration.
            legacy = not frozen
            original = {row['system_role']: row['account_id'] for row in tx.rows(
                'SELECT a.system_role,g.account_id FROM gl_entries g JOIN accounts a ON a.organisation_id=g.organisation_id AND a.id=g.account_id WHERE g.organisation_id=? AND g.posting_batch_id=? AND g.credit>0', (organisation_id, run['posted_batch_id']))}
            pairs = [('PAYROLL_SOCIAL_ACCRUED', 'PAYROLL_SOCIAL_PAYABLE', totals['social_tax']),
                     ('PAYROLL_INCOME_WITHHELD', 'PAYROLL_INCOME_PAYABLE', totals['income_tax']),
                     ('PAYROLL_UI_ACCRUED', 'PAYROLL_UI_PAYABLE', totals['ui_employee']+totals['ui_employer']),
                     ('PAYROLL_PENSION_WITHHELD', 'PAYROLL_SOCIAL_PAYABLE', totals['funded_pension'])]
            if not any(value for _, _, value in pairs):
                # A fully exempt payment can have no tax liability to move.
                # Record the explicit action without fabricating zero ledger lines.
                audit(tx, organisation_id, actor, 'payroll.declaration.settled', 'pay_run', run_id,
                      {'posted_batch_id': None, 'no_liabilities': True})
                return self._run(tx, organisation_id, run_id)
            lines = []
            memo = 'TSD ' + run['period']
            for accrued, payable, value in pairs:
                if not value:
                    continue
                if legacy:
                    sources = ([(original.get('PAYROLL_EMPLOYER_TAX'), totals['ui_employer']), (original.get('PAYROLL_WITHHOLDING'), totals['ui_employee'])]
                               if accrued == 'PAYROLL_UI_ACCRUED' else
                               [(original.get({'PAYROLL_SOCIAL_ACCRUED': 'PAYROLL_EMPLOYER_TAX', 'PAYROLL_INCOME_WITHHELD': 'PAYROLL_INCOME_TAX', 'PAYROLL_PENSION_WITHHELD': 'PAYROLL_WITHHOLDING'}[accrued]), value)])
                else:
                    sources = [(frozen.get(accrued), value)]
                for account_id, amount in sources:
                    if amount:
                        if not account_id:
                            raise ValueError('The original payroll accrual account is missing')
                        lines.append(PostingLine(account_id, debit=amount, memo=memo, source_line_type='pay_run', source_line_id=run_id))
                target = self._posting_account(tx, organisation_id, payable)
                lines.append(PostingLine(target['id'], credit=value, memo=memo, source_line_type='pay_run', source_line_id=run_id))
            batch = LedgerService(self.db).post(organisation_id=organisation_id, voucher_type='payroll_tsd', voucher_id=run_id,
                voucher_code='TSD-' + run['period'], posting_date=declaration_due_date(run['period'], run['payment_date']).isoformat(),
                lines=lines, actor=actor, currency='EUR', tx=tx)
            tx.execute('UPDATE pay_run_settlements SET posted_batch_id=? WHERE organisation_id=? AND pay_run_id=?', (batch['id'], organisation_id, run_id))
            audit(tx, organisation_id, actor, 'payroll.declaration.settled', 'pay_run', run_id, {'posted_batch_id': batch['id']})
            return self._run(tx, organisation_id, run_id)

    def delete_run(self, organisation_id, run_id, *, actor):
        with self.db.transaction() as tx:
            claimed = tx.execute("UPDATE pay_runs SET notes=notes WHERE organisation_id=? AND id=? AND status='Draft'", (organisation_id, run_id))
            self._run(tx, organisation_id, run_id)
            if claimed.rowcount != 1:
                raise PayrollConflict('Only draft pay runs can be deleted')
            tx.execute('DELETE FROM payroll_absence_run_items WHERE organisation_id=? AND pay_run_id=?', (organisation_id, run_id))
            for table in ('pay_item_components', 'pay_item_context'):
                tx.execute(f'DELETE FROM {table} WHERE organisation_id=? AND item_id IN (SELECT id FROM pay_run_items WHERE organisation_id=? AND pay_run_id=?)', (organisation_id, organisation_id, run_id))
            tx.execute('DELETE FROM pay_run_items WHERE organisation_id=? AND pay_run_id=?', (organisation_id, run_id))
            tx.execute('DELETE FROM pay_runs WHERE organisation_id=? AND id=?', (organisation_id, run_id))
            audit(tx, organisation_id, actor, 'payroll.deleted', 'pay_run', run_id)

    def payslips_pdf(self, organisation_id, run_id):
        from documents import payroll_pdf
        with self.db.transaction() as tx:
            run = self._run(tx, organisation_id, run_id)
            org = self._organisation(tx, organisation_id)
            for item in run['items']:
                item['absences'] = tx.rows(
                    'SELECT a.absence_type,a.start_date,a.end_date,x.calendar_days,x.leave_days,x.working_days '
                    'FROM payroll_absence_run_items x JOIN payroll_absences a '
                    'ON a.organisation_id=x.organisation_id AND a.id=x.absence_id '
                    'WHERE x.organisation_id=? AND x.pay_run_id=? AND x.employee_id=? ORDER BY a.start_date,a.id',
                    (organisation_id, run_id, item['employee_id']))
        if run.get('show_leave_balance'):
            from payroll_leave_service import PayrollLeaveLiabilityService
            period = run['period']
            year, month = map(int, period.split('-'))
            as_at = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
            balances = {row['employee_id']: row['remaining_days'] for row in
                        PayrollLeaveLiabilityService(self.db).report(organisation_id, as_at)['employees']}
            for item in run['items']:
                item['remaining_leave_days'] = balances.get(item['employee_id'], '0')
        return payroll_pdf(org, run)

    def workbook_xlsx(self, organisation_id, run_id):
        from excel_export import pay_run_workbook
        with self.db.transaction() as tx:
            run = self._run(tx, organisation_id, run_id)
            org = self._organisation(tx, organisation_id)
            journal_lines = None
            if run.get('posted_batch_id'):
                journal_lines = tx.rows(
                    'SELECT a.code account_code,a.name account_name,g.memo,g.debit,g.credit '
                    'FROM gl_entries g JOIN accounts a ON a.id=g.account_id AND a.organisation_id=g.organisation_id '
                    'WHERE g.organisation_id=? AND g.posting_batch_id=? ORDER BY g.line_number',
                    (organisation_id, run['posted_batch_id']),
                )
        return pay_run_workbook(org, run, run['items'], journal_lines)
