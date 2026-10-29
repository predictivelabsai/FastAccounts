"""Tenant-scoped payroll report calculations and XLSX serialisation."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
import json

from core_utils import db_number, decimal, money
from database import get_database
from payroll_calendar import is_working_day, norm_hours


class PayrollReportsService:
    def __init__(self, db=None):
        self.db = db or get_database()

    def _approved(self, tx, organisation_id, start, end):
        return tx.rows(
            "SELECT r.id run_id,r.period,r.status,i.* FROM pay_runs r JOIN pay_run_items i "
            "ON i.organisation_id=r.organisation_id AND i.pay_run_id=r.id "
            "WHERE r.organisation_id=? AND r.status='Approved' AND r.period BETWEEN ? AND ? "
            "ORDER BY r.period,i.employee_name,i.id", (organisation_id, start, end))

    def annual_summary(self, organisation_id, year):
        start, end = f'{int(year):04d}-01', f'{int(year):04d}-12'
        with self.db.transaction() as tx:
            rows = self._approved(tx, organisation_id, start, end)
            components = tx.rows(
                "SELECT i.employee_id,r.period,c.name,c.amount,c.direction,c.palk_row "
                "FROM pay_runs r JOIN pay_run_items i ON i.organisation_id=r.organisation_id AND i.pay_run_id=r.id "
                "JOIN pay_item_components c ON c.organisation_id=i.organisation_id AND c.item_id=i.id "
                "WHERE r.organisation_id=? AND r.status='Approved' AND r.period BETWEEN ? AND ?",
                (organisation_id, start, end))
        result = {}
        for row in rows:
            emp = result.setdefault(row['employee_id'], {'employee_id': row['employee_id'], 'employee_name': row['employee_name'], 'months': {}, 'taxes': Decimal(0), 'employer_taxes': Decimal(0), 'net': Decimal(0), 'gross_total': Decimal(0)})
            month = emp['months'].setdefault(row['period'], {'gross': Decimal(0), 'taxes': Decimal(0), 'employer_taxes': Decimal(0), 'net': Decimal(0), 'types': {}})
            gross = money(row['gross']); taxes = money(row['income_tax']) + money(row['funded_pension']) + money(row['ui_employee'])
            employer_taxes = money(row['social_tax']) + money(row['ui_employer'])
            base_pay = money(row.get('gross_salary') or 0) if row.get('pay_basis') != 'hourly' else money(decimal(row.get('hourly_rate') or 0) * decimal(row.get('hours') or 0))
            month.update(gross=month['gross'] + gross, taxes=month['taxes'] + taxes,
                         employer_taxes=month['employer_taxes'] + employer_taxes, net=month['net'] + money(row['net']))
            month['types']['Base pay'] = month['types'].get('Base pay', Decimal(0)) + base_pay
            emp['taxes'] += taxes; emp['employer_taxes'] += employer_taxes
            emp['net'] += money(row['net']); emp['gross_total'] += gross
        for c in components:
            emp = result.get(c['employee_id'])
            if emp and c['direction'] == 'income':
                month = emp['months'].setdefault(c['period'], {'gross': Decimal(0), 'taxes': Decimal(0), 'employer_taxes': Decimal(0), 'net': Decimal(0), 'types': {}})
                month['types'][c['name']] = month['types'].get(c['name'], Decimal(0)) + money(c['amount'])
        return [_serialise_employee(row) for row in result.values()]

    def average_pay(self, organisation_id, period, months=6):
        if months not in (6, 9, 12):
            raise ValueError('Choose 6, 9 or 12 months')
        year, month = map(int, period.split('-'))
        end_index = year * 12 + month - 1
        start_index = end_index - months + 1
        start_year, start_month = divmod(start_index, 12)
        start = f'{start_year:04d}-{start_month + 1:02d}'
        with self.db.transaction() as tx:
            rows = self._approved(tx, organisation_id, start, period)
            employees = tx.rows('SELECT id,name FROM employees WHERE organisation_id=? ORDER BY name,id', (organisation_id,))
            employee_details = tx.rows('SELECT * FROM employees WHERE organisation_id=?', (organisation_id,))
        by_emp = defaultdict(list)
        for r in rows: by_emp[r['employee_id']].append(r)
        from payroll_average import calculate_average_pay
        details = {row['id']: row for row in employee_details}
        result = []
        for employee in employees:
            items = by_emp[employee['id']]
            total = sum((money(r['gross']) for r in items), Decimal(0))
            average = calculate_average_pay(details[employee['id']], f'{period}-01',
                approved_items=[dict(r, wage_total=r['gross']) for r in items])
            result.append({'employee_id': employee['id'], 'employee_name': employee['name'], 'period': period,
                'months': months, 'gross_total': db_number(total),
                'average_monthly_gross': db_number(money(total / Decimal(months))),
                'average_daily_pay': db_number(average.average_daily_pay),
                'average_working_day_pay': db_number(average.average_working_day_pay),
                'average_hourly_pay': db_number(average.average_hourly_pay)})
        return result

    def statistics_palk(self, organisation_id, period):
        with self.db.transaction() as tx:
            rows = self._approved(tx, organisation_id, period, period)
            components = tx.rows("SELECT c.palk_designation,c.amount,c.direction,c.name,i.fte,i.pay_basis,i.employee_id "
                "FROM pay_runs r JOIN pay_run_items i ON i.organisation_id=r.organisation_id AND i.pay_run_id=r.id "
                "JOIN pay_item_components c ON c.organisation_id=i.organisation_id AND c.item_id=i.id "
                "WHERE r.organisation_id=? AND r.status='Approved' AND r.period=?", (organisation_id, period))
        result = {str(n): {'full_time': Decimal(0), 'part_time': Decimal(0)} for n in (1,2,3,5,6,7,8,9,10,12,13,15,16,17,18)}
        employees = {}
        for row in rows:
            key = 'full_time' if decimal(row.get('fte') or 1) >= 1 else 'part_time'
            employees[row['employee_id']] = key
            if key in ('full_time','part_time'):
                base = money(row.get('gross_salary') or 0) if row.get('pay_basis') != 'hourly' else money(decimal(row.get('hourly_rate') or 0) * decimal(row.get('hours') or 0))
                result['5'][key] += base
                result['12'][key] += money(row['social_tax'])
                result['13'][key] += money(row['ui_employer'])
        unmapped = {}
        for c in components:
            if c['direction'] != 'income': continue
            if c['palk_designation'] is None:
                name = c.get('name', 'Unknown component')
                unmapped[name] = unmapped.get(name, Decimal(0)) + money(c['amount'])
                continue
            key = employees.get(c['employee_id'])
            if key and str(c['palk_designation']) in result:
                result[str(c['palk_designation'])][key] += money(c['amount'])
        for row in rows:
            key = employees[row['employee_id']]
            result['1'][key] += Decimal(1) / Decimal(1000)
            result['2'][key] += decimal(row.get('fte') or 1) / Decimal(1000)
            if row.get('pay_basis') == 'hourly':
                hours = decimal(row.get('hours') or 0)
            elif row.get('worked_days') is not None and row.get('norm_days'):
                hours = Decimal(norm_hours(*map(int, period.split('-')))) * decimal(row['worked_days']) / decimal(row['norm_days'])
            else:
                hours = Decimal(norm_hours(*map(int, period.split('-')))) * decimal(row.get('fte') or 1)
            result['3'][key] += hours / Decimal(1000)
        return {'period': period, 'due_date': _due_date(period), 'rows': {k: {n: db_number(v.quantize(Decimal('.01'))) for n,v in vals.items()} for k,vals in result.items()}, 'unmapped_types': [{'name': name, 'amount': db_number(money(amount))} for name, amount in sorted(unmapped.items())], 'warning': bool(unmapped)}

    def yearly_headcount(self, organisation_id, year):
        with self.db.transaction() as tx:
            snapshots = []
            for month in range(1,13):
                period = f'{int(year):04d}-{month:02d}'
                rows = tx.rows("SELECT i.employee_id,i.fte FROM pay_runs r JOIN pay_run_items i ON i.organisation_id=r.organisation_id AND i.pay_run_id=r.id WHERE r.organisation_id=? AND r.period=? AND r.status='Approved'", (organisation_id, period))
                if not rows:
                    rows = tx.rows("SELECT id employee_id,fte FROM employees WHERE organisation_id=? AND active=1 AND (employment_start_date IS NULL OR employment_start_date<=?) AND (employment_end_date IS NULL OR employment_end_date>=?)", (organisation_id, period+'-31', period+'-01'))
                snapshots.append((len(rows), sum((decimal(r.get('fte') or 1) for r in rows), Decimal(0))))
        return {'year': int(year), 'average_headcount': db_number(Decimal(sum(n for n,_ in snapshots))/Decimal(12)),
                'average_fte': db_number(sum((fte for _,fte in snapshots), Decimal(0))/Decimal(12)), 'months': [{'headcount': n, 'fte': db_number(fte)} for n,fte in snapshots]}

    def pay_list(self, organisation_id, start, end):
        with self.db.transaction() as tx:
            rows = self._approved(tx, organisation_id, start, end)
            paid = {(r['pay_run_id'], r['employee_id']) for r in tx.rows("SELECT b.pay_run_id,l.employee_id FROM payroll_payout_batches b JOIN payroll_payout_lines l ON l.organisation_id=b.organisation_id AND l.payout_batch_id=b.id WHERE b.organisation_id=? AND b.status='Paid' AND b.payout_type='salary'", (organisation_id,))}
        return [{'period': r['period'], 'employee_id': r['employee_id'], 'employee_name': r['employee_name'], 'gross': db_number(money(r['gross'])), 'net': db_number(money(r['net'])), 'status': 'Paid' if (r['run_id'],r['employee_id']) in paid else 'Unpaid'} for r in rows]

    @staticmethod
    def workbook(title, rows):
        from openpyxl import Workbook
        from io import BytesIO
        book = Workbook(); sheet = book.active; sheet.title = title[:31]
        if rows:
            headers = list(rows[0]); sheet.append(headers)
            for row in rows: sheet.append([json.dumps(row.get(k), ensure_ascii=False, sort_keys=True) if isinstance(row.get(k), (dict,list)) else row.get(k) for k in headers])
        buf = BytesIO(); book.save(buf); return buf.getvalue()


def _serialise_employee(row):
    row['taxes'] = db_number(money(row['taxes'])); row['employer_taxes'] = db_number(money(row['employer_taxes']))
    row['net'] = db_number(money(row['net'])); row['gross_total'] = db_number(money(row['gross_total']))
    row['months'] = {k: {**{n: db_number(money(v)) for n,v in m.items() if n != 'types'}, 'types': {t: db_number(money(v)) for t,v in m['types'].items()}} for k,m in row['months'].items()}
    return row


def _due_date(period):
    year, month = map(int, period.split('-'))
    due = date(year + (month == 12), month % 12 + 1, 18)
    while not is_working_day(due):
        due += timedelta(days=1)
    return due.isoformat()
