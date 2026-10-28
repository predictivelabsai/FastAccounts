"""Frozen taxable calculations and accounting lifecycle for absence-pay payouts."""
import json
from datetime import date
from decimal import Decimal

from core_utils import audit, db_number, decimal, new_id, utc_now
from ledger import LedgerService, PostingLine
from payroll import PayrollService, calculate_pay
from payroll_absence_pay import vacation_payout_date
from payroll_rules import remaining_monthly_exemption, rules_for
from payroll_tax_repository import monthly_exemption_used
from payroll_tax_settings import resolve


class AbsencePayoutService:
    def __init__(self, db):
        self.db = db

    def pending(self, organisation_id):
        return self.db.rows("SELECT p.*,e.name employee_name FROM payroll_absence_pay p "
                            "JOIN employees e ON e.organisation_id=p.organisation_id AND e.id=p.employee_id "
                            "WHERE p.organisation_id=? AND p.status='pending' ORDER BY p.payment_date,e.name,p.id",
                            (organisation_id,))

    def drafts(self, organisation_id):
        return self.db.rows("SELECT * FROM payroll_absence_payout_batches WHERE organisation_id=? "
                            "AND status='Draft' ORDER BY payout_date,id", (organisation_id,))

    def create(self, organisation_id, absence_pay_ids, *, actor, payout_date=None):
        if not absence_pay_ids or len(set(absence_pay_ids)) != len(absence_pay_ids):
            raise ValueError('Select one or more distinct absence-pay records')
        with self.db.transaction() as tx:
            rows = []
            for record_id in absence_pay_ids:
                row = tx.one("SELECT p.*,e.*,a.start_date AS leave_start FROM payroll_absence_pay p "
                             "JOIN payroll_absences a ON a.organisation_id=p.organisation_id AND a.id=p.absence_id JOIN employees e "
                             "ON e.organisation_id=p.organisation_id AND e.id=p.employee_id "
                             "WHERE p.organisation_id=? AND p.id=? AND p.status='pending'",
                             (organisation_id, record_id))
                if not row:
                    raise KeyError('Pending absence pay not found')
                rows.append(row)
            date_value = date.fromisoformat(payout_date) if payout_date else min(
                (vacation_payout_date(date.fromisoformat(row['leave_start'])) for row in rows))
            if date_value.isoformat() != (payout_date or date_value.isoformat()):
                raise ValueError('Payout date must use YYYY-MM-DD')
            batch_id, now = new_id(), utc_now()
            tx.execute("INSERT INTO payroll_absence_payout_batches(id,organisation_id,payout_date,created_at) VALUES (?,?,?,?)",
                       (batch_id, organisation_id, date_value.isoformat(), now))
            self._attach(tx, organisation_id, batch_id, rows, date_value, actor)
            return self.get(organisation_id, batch_id, tx=tx)

    def add(self, organisation_id, batch_id, absence_pay_ids, *, actor):
        if not absence_pay_ids or len(set(absence_pay_ids)) != len(absence_pay_ids):
            raise ValueError('Select one or more distinct absence-pay records')
        with self.db.transaction() as tx:
            batch = self._batch(tx, organisation_id, batch_id)
            if batch['status'] != 'Draft':
                raise ValueError('Absence pay can only be added to a draft payout')
            rows = []
            for record_id in absence_pay_ids:
                row = tx.one("SELECT p.*,e.* FROM payroll_absence_pay p JOIN employees e "
                             "ON e.organisation_id=p.organisation_id AND e.id=p.employee_id "
                             "WHERE p.organisation_id=? AND p.id=? AND p.status='pending'",
                             (organisation_id, record_id))
                if not row:
                    raise KeyError('Pending absence pay not found')
                rows.append(row)
            self._attach(tx, organisation_id, batch_id, rows, date.fromisoformat(batch['payout_date']), actor)
            return self.get(organisation_id, batch_id, tx=tx)

    def _attach(self, tx, organisation_id, batch_id, rows, payout_date, actor):
        used_by_employee = {}
        existing = tx.rows("SELECT employee_id,calculation_json FROM payroll_absence_pay "
                            "WHERE organisation_id=? AND absence_payout_batch_id=? AND status='in_payout'",
                            (organisation_id, batch_id))
        for row in existing:
            calc = json.loads(row['calculation_json'])
            if row['employee_id'] not in used_by_employee:
                used_by_employee[row['employee_id']] = monthly_exemption_used(
                    tx, organisation_id, row['employee_id'], payout_date.strftime('%Y-%m'))
            used_by_employee[row['employee_id']] += decimal(calc.get('tax_free_minimum', '0'))
        for row in rows:
            if tx.dialect == 'postgres':
                tx.execute('UPDATE employees SET active=active WHERE organisation_id=? AND id=?',
                           (organisation_id, row['employee_id']))
            election = resolve(tx, organisation_id, row | {'id': row['employee_id']}, payout_date)
            used = used_by_employee.get(row['employee_id'])
            if used is None:
                used = monthly_exemption_used(tx, organisation_id, row['employee_id'], payout_date.strftime('%Y-%m'))
            cap = remaining_monthly_exemption(election['tax_free_mode'], election['tax_free_amount'],
                                              rules_for(payout_date).basic_exemption, used)
            employee = row | election | {'gross_salary': row['gross'], 'pay_basis': 'monthly',
                                         'social_tax_minimum_exemption': row.get('social_tax_minimum_exemption')}
            calc = calculate_pay(employee, period=payout_date.strftime('%Y-%m'), settlement_on=payout_date,
                                 exemption_remaining=cap)
            used_by_employee[row['employee_id']] = used + decimal(calc['tax_free_minimum'])
            frozen = {key: db_number(value) if isinstance(value, Decimal) else value for key, value in calc.items()}
            frozen.update({key: election.get(key) for key in ('tax_free_mode','tax_free_amount','funded_pension_percent','unemployment_applies')})
            frozen.update(employee_name=row['name'], employee_personal_id=row.get('personal_id'), pay_basis='monthly')
            changed = tx.execute("UPDATE payroll_absence_pay SET status='in_payout',absence_payout_batch_id=?,payment_date=?,payment_month=?,calculation_json=?,updated_at=? "
                                 "WHERE organisation_id=? AND id=? AND status='pending'",
                                 (batch_id, payout_date.isoformat(), payout_date.strftime('%Y-%m'),
                                  json.dumps(frozen, sort_keys=True), utc_now(), organisation_id, row['id']))
            if changed.rowcount != 1:
                raise ValueError('Absence pay was already added to a payout')
        audit(tx, organisation_id, actor, 'payroll.absence_payout.updated', 'payroll_absence_payout_batch', batch_id,
              {'absence_pay_ids': [row['id'] for row in rows]})

    def approve(self, organisation_id, batch_id, *, actor):
        with self.db.transaction() as tx:
            batch = self._batch(tx, organisation_id, batch_id)
            if batch['status'] != 'Draft' or not batch['lines']:
                raise ValueError('Only a non-empty draft absence payout can be approved')
            claimed = tx.execute("UPDATE payroll_absence_payout_batches SET status='Approved',approved_at=?,approved_by=? "
                                 "WHERE organisation_id=? AND id=? AND status='Draft'",
                                 (utc_now(), actor, organisation_id, batch_id))
            if claimed.rowcount != 1:
                raise ValueError('Absence payout is no longer a draft')
            from payroll_tsd_breakdown import freeze_tsd_breakdown
            for line in batch['lines']:
                frozen = line['calculation']
                freeze_tsd_breakdown(tx, organisation_id, 'absence_pay', line['id'],
                                     item=frozen | {'tsd_payment_type': 10, 'pay_basis': 'monthly'},
                                     components=[], context=frozen, payout_batch_id=batch_id)
            payroll = PayrollService(self.db)
            accounts = {role: payroll._posting_account(tx, organisation_id, role) for role in
                        ('PAYROLL_SALARY','PAYROLL_SALARY_PAYABLE','PAYROLL_INCOME_WITHHELD',
                         'PAYROLL_PENSION_WITHHELD','PAYROLL_UI_ACCRUED','PAYROLL_SOCIAL',
                         'PAYROLL_SOCIAL_ACCRUED','PAYROLL_UI')}
            keys = {'gross':'PAYROLL_SALARY','income_tax':'PAYROLL_INCOME_WITHHELD',
                    'funded_pension':'PAYROLL_PENSION_WITHHELD','ui_employee':'PAYROLL_UI_ACCRUED',
                    'social_tax':'PAYROLL_SOCIAL','ui_employer':'PAYROLL_UI'}
            totals = {key: sum((decimal(line['calculation'].get(key, 0)) for line in batch['lines']), Decimal(0)) for key in keys}
            lines = []
            memo = 'Absence pay ' + batch['payout_date']
            for key, role in keys.items():
                amount = totals[key]
                if amount:
                    debit = key in ('gross','social_tax','ui_employer')
                    lines.append(PostingLine(accounts[role]['id'], debit=amount if debit else 0,
                                             credit=0 if debit else amount, memo=memo,
                                             source_line_type='payroll_absence_payout', source_line_id=batch_id))
            if totals['gross']:
                lines.append(PostingLine(accounts['PAYROLL_SALARY_PAYABLE']['id'], credit=totals['gross'],
                                         memo=memo, source_line_type='payroll_absence_payout', source_line_id=batch_id))
            payable_credit = sum((totals[key] for key in ('income_tax','funded_pension','ui_employee')), Decimal(0))
            if payable_credit:
                lines.append(PostingLine(accounts['PAYROLL_SALARY_PAYABLE']['id'], debit=payable_credit,
                                         memo=memo, source_line_type='payroll_absence_payout', source_line_id=batch_id))
            employer_social = totals['social_tax'] + totals['ui_employer']
            if employer_social:
                lines.append(PostingLine(accounts['PAYROLL_SOCIAL_ACCRUED']['id'], credit=totals['social_tax'], memo=memo,
                                         source_line_type='payroll_absence_payout', source_line_id=batch_id))
                lines.append(PostingLine(accounts['PAYROLL_UI_ACCRUED']['id'], credit=totals['ui_employer'], memo=memo,
                                         source_line_type='payroll_absence_payout', source_line_id=batch_id))
            # Employee withholdings are credited by their dedicated liability roles.
            posting = LedgerService(self.db).post(organisation_id=organisation_id, voucher_type='payroll_absence_payout',
                voucher_id=batch_id, voucher_code='ABP-' + batch_id[:12], posting_date=batch['payout_date'],
                lines=lines, actor=actor, currency='EUR', tx=tx)
            tx.execute("UPDATE payroll_absence_payout_batches SET posted_batch_id=? WHERE organisation_id=? AND id=?",
                       (posting['id'], organisation_id, batch_id))
            audit(tx, organisation_id, actor, 'payroll.absence_payout.approved', 'payroll_absence_payout_batch', batch_id,
                  {'posted_batch_id': posting['id']})
            return self.get(organisation_id, batch_id, tx=tx)

    def paid(self, organisation_id, batch_id, bank_account_id, *, actor):
        with self.db.transaction() as tx:
            batch = self._batch(tx, organisation_id, batch_id)
            if batch['status'] != 'Approved':
                raise ValueError('Only approved absence payouts can be marked paid')
            claimed = tx.execute("UPDATE payroll_absence_payout_batches SET status='Paid',bank_account_id=?,paid_at=?,paid_by=? "
                                 "WHERE organisation_id=? AND id=? AND status='Approved'",
                                 (bank_account_id, utc_now(), actor, organisation_id, batch_id))
            if claimed.rowcount != 1:
                raise ValueError('Absence payout is no longer approved')
            bank = tx.one('SELECT * FROM bank_accounts WHERE organisation_id=? AND id=? AND active=1', (organisation_id, bank_account_id))
            payable = PayrollService._posting_account(tx, organisation_id, 'PAYROLL_SALARY_PAYABLE')
            if not bank:
                raise KeyError('Bank account not found')
            amount = sum((decimal(line['calculation']['net']) for line in batch['lines']), Decimal(0))
            posting = LedgerService(self.db).post(organisation_id=organisation_id, voucher_type='payroll_absence_payout_payment',
                voucher_id=batch_id, voucher_code='ABPP-' + batch_id[:11], posting_date=batch['payout_date'],
                lines=[PostingLine(payable['id'], debit=amount, memo='Absence pay paid', source_line_type='payroll_absence_payout', source_line_id=batch_id),
                       PostingLine(bank['ledger_account_id'], credit=amount, memo='Absence pay paid', source_line_type='payroll_absence_payout', source_line_id=batch_id)],
                actor=actor, currency='EUR', tx=tx)
            tx.execute("UPDATE payroll_absence_payout_batches SET paid_batch_id=? WHERE organisation_id=? AND id=?",
                       (posting['id'], organisation_id, batch_id))
            tx.execute("UPDATE payroll_absence_pay SET status='paid' WHERE organisation_id=? AND absence_payout_batch_id=?",
                       (organisation_id, batch_id))
            return self.get(organisation_id, batch_id, tx=tx)

    def cancel(self, organisation_id, batch_id, *, actor):
        with self.db.transaction() as tx:
            batch = self._batch(tx, organisation_id, batch_id)
            if batch['status'] == 'Cancelled':
                raise ValueError('Absence payout is already cancelled')
            claimed = tx.execute("UPDATE payroll_absence_payout_batches SET status='Cancelled' WHERE organisation_id=? AND id=? AND status=?",
                                 (organisation_id, batch_id, batch['status']))
            if claimed.rowcount != 1:
                raise ValueError('Absence payout changed during cancellation')
            reversals = []
            for posting_id in (batch.get('posted_batch_id'), batch.get('paid_batch_id')):
                if posting_id:
                    reversals.append(LedgerService(self.db).reverse(posting_id, reversal_date=date.today().isoformat(),
                        actor=actor, reason='Absence payout cancelled', tx=tx)['id'])
            tx.execute("UPDATE payroll_absence_payout_batches SET status='Cancelled',reversal_batch_id=? WHERE organisation_id=? AND id=?",
                       (reversals[-1] if reversals else None, organisation_id, batch_id))
            tx.execute("UPDATE payroll_absence_pay SET status='pending',absence_payout_batch_id=NULL WHERE organisation_id=? AND absence_payout_batch_id=?",
                       (organisation_id, batch_id))
            audit(tx, organisation_id, actor, 'payroll.absence_payout.cancelled', 'payroll_absence_payout_batch', batch_id,
                  {'reversal_batch_ids': reversals})
            return self.get(organisation_id, batch_id, tx=tx)

    def _batch(self, tx, organisation_id, batch_id):
        row = tx.one('SELECT * FROM payroll_absence_payout_batches WHERE organisation_id=? AND id=?', (organisation_id, batch_id))
        if not row:
            raise KeyError('Absence payout not found')
        row['lines'] = tx.rows('SELECT p.*,e.name employee_name FROM payroll_absence_pay p JOIN employees e '
                               'ON e.organisation_id=p.organisation_id AND e.id=p.employee_id '
                               'WHERE p.organisation_id=? AND p.absence_payout_batch_id=? ORDER BY e.name,p.id',
                               (organisation_id, batch_id))
        for line in row['lines']:
            line['calculation'] = json.loads(line.pop('calculation_json'))
        return row

    def get(self, organisation_id, batch_id, *, tx=None):
        if tx:
            return self._batch(tx, organisation_id, batch_id)
        with self.db.transaction() as current:
            return self._batch(current, organisation_id, batch_id)
