"""Estonian accounting-bureau payroll for the 2026 demo rule set."""
from __future__ import annotations

import calendar
import re
from decimal import Decimal, InvalidOperation

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from database import Database, get_database
from ledger import LedgerService, PostingLine


class PayrollConflict(ValueError):
    """A payroll workflow conflicts with an existing record or state."""


AMOUNTS = ('gross', 'funded_pension', 'ui_employee', 'tax_free_minimum',
           'income_tax', 'net', 'withholding_total', 'social_tax', 'ui_employer', 'employer_cost')


def calculate_pay(employee: dict) -> dict:
    gross = money(employee['gross_salary'])
    pension = money(gross * decimal(employee['funded_pension_percent']) / 100)
    ui = money(0 if employee['board_member'] else gross * Decimal('0.016'))
    exemption = money(700 if employee['apply_tax_free_minimum'] else 0)
    income_tax = money(max(Decimal('0'), gross - pension - ui - exemption) * Decimal('0.22'))
    social = money(gross * Decimal('0.33'))
    employer_ui = money(0 if employee['board_member'] else gross * Decimal('0.008'))
    withholding = pension + ui + income_tax
    return dict(gross=gross, funded_pension=pension, ui_employee=ui,
                tax_free_minimum=exemption, income_tax=income_tax, net=gross-withholding,
                withholding_total=withholding, social_tax=social, ui_employer=employer_ui,
                employer_cost=gross+social+employer_ui)


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
        if data.get('gross_salary') is None or data.get('funded_pension_percent') is None:
            raise ValueError('Salary and pension percentage cannot be null')
        try:
            gross = decimal(data['gross_salary'])
            pension = decimal(data['funded_pension_percent'])
            if not gross.is_finite() or gross <= 0 or gross > Decimal('9999999999.99'):
                raise ValueError('Gross salary must be positive and fit NUMERIC(12,2)')
            if pension not in ({0, 2, 4, 6} if data['board_member'] else {2, 4, 6}):
                raise ValueError('Funded pension must be 2, 4 or 6 percent (also 0 for board members)')
            data['gross_salary'] = db_number(money(gross))
            if money(gross) <= 0:
                raise ValueError('Gross salary must be at least 0.01')
            data['funded_pension_percent'] = db_number(pension)
        except InvalidOperation as exc:
            raise ValueError('Invalid salary or pension percentage') from exc
        return data

    def employees(self, organisation_id):
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            return [self._serialize_employee(row) for row in tx.rows(
                'SELECT * FROM employees WHERE organisation_id=? ORDER BY name,id', (organisation_id,))]

    @staticmethod
    def _serialize_employee(row):
        for key in ('gross_salary', 'funded_pension_percent'):
            row[key] = db_number(money(row[key]))
        for key in ('board_member', 'active', 'apply_tax_free_minimum'):
            row[key] = bool(row[key])
        return row

    def save_employee(self, organisation_id, *, actor, employee_id=None, **changes):
        import sqlite3
        from psycopg.errors import UniqueViolation
        try:
            return self._save_employee(organisation_id, actor=actor, employee_id=employee_id, **changes)
        except (sqlite3.IntegrityError, UniqueViolation) as exc:
            if 'employees.organisation_id, employees.name' in str(exc) or getattr(exc, 'sqlstate', '') == '23505':
                raise PayrollConflict('An employee with this name already exists') from exc
            raise

    def _save_employee(self, organisation_id, *, actor, employee_id=None, **changes):
        fields = ('name', 'email', 'personal_id', 'gross_salary', 'funded_pension_percent',
                  'apply_tax_free_minimum', 'board_member', 'active')
        if set(changes) - set(fields):
            raise ValueError('Unknown employee field')
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            if employee_id:
                data = tx.one('SELECT * FROM employees WHERE organisation_id=? AND id=?', (organisation_id, employee_id))
                if not data:
                    raise KeyError('Employee not found')
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
                                    'VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organisation_id,name) DO NOTHING',
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
            item['board_member'] = bool(item['board_member'])
        for key in ('total_gross', 'total_net', 'total_employer_cost'):
            run[key] = db_number(money(run[key]))
        return run

    def runs(self, organisation_id):
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            return [self._run(tx, organisation_id, row['id']) for row in tx.rows(
                'SELECT id FROM pay_runs WHERE organisation_id=? ORDER BY period DESC,id', (organisation_id,))]

    def create_run(self, organisation_id, *, period, actor):
        if not re.fullmatch(r'2026-(0[1-9]|1[0-2])', period):
            raise ValueError('Payroll demo supports monthly periods YYYY-MM in 2026 only')
        with self.db.transaction() as tx:
            self._organisation(tx, organisation_id)
            run_id = new_id()
            result = tx.execute("INSERT INTO pay_runs(id,organisation_id,period,total_gross,total_net,total_employer_cost,created_by,created_at) VALUES (?,?,?,0,0,0,?,?) ON CONFLICT(organisation_id,period) DO NOTHING", (run_id, organisation_id, period, actor, utc_now()))
            if result.rowcount != 1:
                raise PayrollConflict(f'A pay run already exists for {period}')
            employees = tx.rows('SELECT * FROM employees WHERE organisation_id=? AND active=1 ORDER BY name,id', (organisation_id,))
            if not employees:
                raise ValueError('A pay run requires at least one active employee')
            minimum = Decimal('886') if period < '2026-04' else Decimal('946')
            totals = dict(gross=Decimal(0), net=Decimal(0), employer_cost=Decimal(0))
            for employee in employees:
                if not employee['board_member'] and money(employee['gross_salary']) < minimum:
                    raise ValueError(f"{employee['name']}: gross salary must be at least EUR {minimum:.2f} for {period}")
                amounts = calculate_pay(employee)
                tx.execute('INSERT INTO pay_run_items(id,pay_run_id,organisation_id,employee_id,employee_name,gross_salary,board_member,funded_pension_percent,'+','.join(AMOUNTS)+') VALUES ('+','.join('?' for _ in range(18))+')',
                           (new_id(), run_id, organisation_id, employee['id'], employee['name'], db_number(money(employee['gross_salary'])), employee['board_member'], db_number(decimal(employee['funded_pension_percent'])))+tuple(db_number(amounts[k]) for k in AMOUNTS))
                for key in totals:
                    totals[key] += amounts[key]
            tx.execute('UPDATE pay_runs SET total_gross=?,total_net=?,total_employer_cost=? WHERE organisation_id=? AND id=?', tuple(db_number(totals[k]) for k in totals)+(organisation_id, run_id))
            audit(tx, organisation_id, actor, 'payroll.drafted', 'pay_run', run_id, {'period': period})
            return self._run(tx, organisation_id, run_id)

    def approve(self, organisation_id, run_id, *, actor):
        with self.db.transaction() as tx:
            # Conditional write serializes concurrent approvals on SQLite and PostgreSQL.
            claimed = tx.execute("UPDATE pay_runs SET status='Approved',approved_at=? WHERE organisation_id=? AND id=? AND status='Draft'", (utc_now(), organisation_id, run_id))
            run = self._run(tx, organisation_id, run_id)
            if claimed.rowcount != 1:
                raise PayrollConflict('Pay run is already approved')
            totals = {k: sum((decimal(i[k]) for i in run['items']), Decimal(0)) for k in AMOUNTS}
            postings = [('PAYROLL_SALARY', totals['gross'], True), ('PAYROLL_SOCIAL', totals['social_tax'], True),
                        ('PAYROLL_UI', totals['ui_employer'], True), ('PAYROLL_NET', totals['net'], False),
                        ('PAYROLL_INCOME_TAX', totals['income_tax'], False),
                        ('PAYROLL_WITHHOLDING', totals['funded_pension']+totals['ui_employee'], False),
                        ('PAYROLL_EMPLOYER_TAX', totals['social_tax']+totals['ui_employer'], False)]
            lines = []
            for role, value, debit in postings:
                if not value:
                    continue
                account = tx.one('SELECT id FROM accounts WHERE organisation_id=? AND system_role=? AND active=1', (organisation_id, role))
                if not account:
                    raise ValueError(f'Chart of accounts is missing {role}')
                lines.append(PostingLine(account['id'], debit=value if debit else Decimal(0), credit=Decimal(0) if debit else value,
                                         memo=f"Payroll {run['period']}", source_line_type='pay_run', source_line_id=run_id))
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
