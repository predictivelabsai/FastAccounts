"""Payroll payout batches and immutable bank settlement postings."""
from datetime import date
from decimal import Decimal

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from database import Database, get_database
from ledger import LedgerService, PostingLine
from payroll_payday import payday
from payroll_rules import settlement_date

PAYOUT_TYPES = {'salary', 'advance', 'absence_pay', 'bonus', 'withholding'}


class PayoutService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    def _run(self, tx, organisation_id, run_id):
        run = tx.one('SELECT * FROM pay_runs WHERE organisation_id=? AND id=?', (organisation_id, run_id))
        if not run:
            raise KeyError('Pay run not found')
        if run['status'] != 'Approved':
            raise ValueError('Only approved pay runs can be paid')
        return run

    def _default_date(self, tx, organisation_id, period):
        rows = tx.rows('SELECT rule,day FROM organisation_payday_rules WHERE organisation_id=? AND start_date<=? ORDER BY start_date DESC LIMIT 1',
                       (organisation_id, period + '-31'))
        return payday(period, rows[0]['rule'], rows[0]['day']) if rows else settlement_date(period)

    def _outstanding(self, tx, organisation_id, run_id):
        items = tx.rows('SELECT i.employee_id,i.net,e.iban,e.bank_account_owner,e.name FROM pay_run_items i '
                        'JOIN employees e ON e.organisation_id=i.organisation_id AND e.id=i.employee_id '
                        'WHERE i.organisation_id=? AND i.pay_run_id=? ORDER BY i.employee_id', (organisation_id, run_id))
        for item in items:
            paid = tx.one("SELECT COALESCE(SUM(l.amount),0) amount FROM payroll_payout_lines l "
                           "JOIN payroll_payout_batches b ON b.organisation_id=l.organisation_id AND b.id=l.payout_batch_id "
                           "WHERE b.organisation_id=? AND b.pay_run_id=? AND b.status!='Cancelled' AND l.employee_id=?",
                           (organisation_id, run_id, item['employee_id']))
            item['unpaid'] = money(decimal(item['net']) - decimal(paid['amount']))
        return items

    def create(self, organisation_id, run_id, *, actor, payout_date=None, payout_type='salary', amounts=None, bank_account_id=None):
        if payout_type not in PAYOUT_TYPES:
            raise ValueError('Invalid payout type')
        with self.db.transaction() as tx:
            run = self._run(tx, organisation_id, run_id)
            chosen_date = date.fromisoformat(payout_date).isoformat() if payout_date else self._default_date(tx, organisation_id, run['period']).isoformat()
            outstanding = self._outstanding(tx, organisation_id, run_id)
            requested = amounts if amounts is not None else {row['employee_id']: str(row['unpaid']) for row in outstanding if row['unpaid'] > 0}
            known = {row['employee_id']: row for row in outstanding}
            if not requested:
                raise ValueError('No unpaid net remains for this run')
            batch_id, now = new_id(), utc_now()
            if bank_account_id and not tx.one('SELECT id FROM bank_accounts WHERE organisation_id=? AND id=? AND active=1', (organisation_id, bank_account_id)):
                raise KeyError('Bank account not found')
            tx.execute('INSERT INTO payroll_payout_batches(id,organisation_id,pay_run_id,payout_type,payout_date,bank_account_id,created_at) VALUES (?,?,?,?,?,?,?)',
                       (batch_id, organisation_id, run_id, payout_type, chosen_date, bank_account_id, now))
            for employee_id, raw_amount in requested.items():
                item = known.get(employee_id)
                if not item:
                    raise KeyError('Employee not found in pay run')
                amount = money(raw_amount)
                if amount <= 0:
                    raise ValueError('Payout amounts must be positive')
                if amount > item['unpaid']:
                    raise PayoutConflict('Payout exceeds the employee unpaid net amount')
                tx.execute('INSERT INTO payroll_payout_lines(id,organisation_id,payout_batch_id,employee_id,amount,iban,account_owner) VALUES (?,?,?,?,?,?,?)',
                           (new_id(), organisation_id, batch_id, employee_id, db_number(amount), item['iban'], item['bank_account_owner'] or item['name']))
            audit(tx, organisation_id, actor, 'payroll.payout.created', 'payroll_payout_batch', batch_id,
                  {'pay_run_id': run_id, 'payout_date': chosen_date})
            return self.get(organisation_id, batch_id, tx=tx)

    def mark_paid(self, organisation_id, batch_id, bank_account_id, *, actor):
        with self.db.transaction() as tx:
            batch = self._batch(tx, organisation_id, batch_id)
            if batch['status'] != 'Draft':
                raise PayoutConflict('Only draft payouts can be marked paid')
            bank = tx.one('SELECT * FROM bank_accounts WHERE organisation_id=? AND id=? AND active=1', (organisation_id, bank_account_id))
            if not bank:
                raise KeyError('Bank account not found')
            frozen = tx.one("SELECT account_id FROM pay_run_posting_accounts WHERE organisation_id=? AND pay_run_id=? AND role='PAYROLL_SALARY_PAYABLE'",
                            (organisation_id, batch['pay_run_id']))
            if not frozen:
                raise ValueError('The salary payable account is missing')
            amount = sum((money(line['amount']) for line in batch['lines']), Decimal(0))
            lines = [PostingLine(frozen['account_id'], debit=amount, memo='Payroll payout ' + batch['payout_date'], source_line_type='payroll_payout', source_line_id=batch_id),
                     PostingLine(bank['ledger_account_id'], credit=amount, memo='Payroll payout ' + batch['payout_date'], source_line_type='payroll_payout', source_line_id=batch_id)]
            posting = LedgerService(self.db).post(organisation_id=organisation_id, voucher_type='payroll_payout', voucher_id=batch_id,
                voucher_code='PAY-' + batch_id[:12], posting_date=batch['payout_date'], lines=lines, actor=actor, currency='EUR', tx=tx)
            paid_at = utc_now()
            tx.execute("UPDATE payroll_payout_batches SET status='Paid',bank_account_id=?,paid_at=?,paid_by=?,posted_batch_id=? WHERE organisation_id=? AND id=?",
                       (bank_account_id, paid_at, actor, posting['id'], organisation_id, batch_id))
            audit(tx, organisation_id, actor, 'payroll.payout.paid', 'payroll_payout_batch', batch_id, {'posted_batch_id': posting['id']})
            return self.get(organisation_id, batch_id, tx=tx)

    def cancel(self, organisation_id, batch_id, *, actor):
        with self.db.transaction() as tx:
            batch = self._batch(tx, organisation_id, batch_id)
            if batch['status'] == 'Cancelled':
                raise PayoutConflict('Payout is already cancelled')
            reversal_id = None
            if batch['status'] == 'Paid':
                reversal = LedgerService(self.db).reverse(batch['posted_batch_id'], reversal_date=date.today().isoformat(),
                                                            actor=actor, reason='Payroll payout cancelled', tx=tx)
                reversal_id = reversal['id']
            tx.execute("UPDATE payroll_payout_batches SET status='Cancelled',reversal_batch_id=? WHERE organisation_id=? AND id=?",
                       (reversal_id, organisation_id, batch_id))
            audit(tx, organisation_id, actor, 'payroll.payout.cancelled', 'payroll_payout_batch', batch_id,
                  {'reversal_batch_id': reversal_id})
            return self.get(organisation_id, batch_id, tx=tx)

    def _batch(self, tx, organisation_id, batch_id):
        batch = tx.one('SELECT * FROM payroll_payout_batches WHERE organisation_id=? AND id=?', (organisation_id, batch_id))
        if not batch:
            raise KeyError('Payout not found')
        batch['lines'] = tx.rows('SELECT * FROM payroll_payout_lines WHERE organisation_id=? AND payout_batch_id=? ORDER BY employee_id', (organisation_id, batch_id))
        return batch

    def get(self, organisation_id, batch_id, *, tx=None):
        if tx:
            return self._batch(tx, organisation_id, batch_id)
        with self.db.transaction() as current:
            return self._batch(current, organisation_id, batch_id)

    def list(self, organisation_id, *, run_id=None):
        query = 'SELECT id FROM payroll_payout_batches WHERE organisation_id=?'
        params = [organisation_id]
        if run_id:
            query += ' AND pay_run_id=?'; params.append(run_id)
        query += ' ORDER BY payout_date,id'
        return [self.get(organisation_id, row['id']) for row in self.db.rows(query, params)]


class PayoutConflict(ValueError):
    pass
