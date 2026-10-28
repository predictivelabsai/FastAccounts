"""Payroll payout batches and immutable bank settlement postings."""
from datetime import date
from decimal import Decimal

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from database import Database, get_database
from ledger import LedgerService, PostingLine
from payroll_payday import payday_for_period
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
        return payday_for_period(tx, organisation_id, period) or settlement_date(period)

    def _outstanding(self, tx, organisation_id, run_id):
        items = tx.rows('SELECT i.employee_id,COALESCE(i.payout_net_delta,i.net) net,e.iban,e.bank_account_owner,e.name FROM pay_run_items i '
                        'JOIN employees e ON e.organisation_id=i.organisation_id AND e.id=i.employee_id '
                        'WHERE i.organisation_id=? AND i.pay_run_id=? ORDER BY i.employee_id', (organisation_id, run_id))
        for item in items:
            paid = tx.one("SELECT COALESCE(SUM(l.amount),0) amount FROM payroll_payout_lines l "
                           "JOIN payroll_payout_batches b ON b.organisation_id=l.organisation_id AND b.id=l.payout_batch_id "
                           "WHERE b.organisation_id=? AND b.pay_run_id=? AND b.status!='Cancelled' AND l.employee_id=?",
                           (organisation_id, run_id, item['employee_id']))
            offsets = tx.one("SELECT COALESCE(SUM(o.amount),0) amount FROM payroll_receivable_offsets o "
                             "JOIN payroll_payout_batches b ON b.organisation_id=o.organisation_id AND b.id=o.payout_batch_id "
                             "WHERE b.organisation_id=? AND b.pay_run_id=? AND b.status!='Cancelled' "
                             "AND o.employee_id=? AND o.status IN ('Proposed','Posted')",
                             (organisation_id, run_id, item['employee_id']))
            item['unpaid'] = money(decimal(item['net']) - decimal(paid['amount']) - decimal(offsets['amount']))
        return items

    def create(self, organisation_id, run_id, *, actor, payout_date=None, payout_type='salary', amounts=None, bank_account_id=None):
        if payout_type not in PAYOUT_TYPES:
            raise ValueError('Invalid payout type')
        with self.db.transaction() as tx:
            tx.execute('UPDATE pay_runs SET settlement_date=settlement_date WHERE organisation_id=? AND id=?', (organisation_id, run_id))
            run = self._run(tx, organisation_id, run_id)
            chosen_date = date.fromisoformat(payout_date).isoformat() if payout_date else self._default_date(tx, organisation_id, run['period']).isoformat()
            frozen_date = date.fromisoformat(run.get('settlement_date') or self._default_date(tx, organisation_id, run['period']).isoformat())
            if payout_type == 'salary' and run.get('kind', 'regular') == 'regular' and chosen_date[:7] != frozen_date.isoformat()[:7]:
                raise PayoutConflict('The payout month differs from the frozen payroll calculation month; a correction is required')
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
                line_id = new_id()
                tx.execute('INSERT INTO payroll_payout_lines(id,organisation_id,payout_batch_id,employee_id,amount,requested_amount,iban,account_owner) VALUES (?,?,?,?,?,?,?,?)',
                           (line_id, organisation_id, batch_id, employee_id, db_number(amount), db_number(amount), item['iban'], item['bank_account_owner'] or item['name']))
                remaining = tx.rows("SELECT r.id,r.remaining_amount,COALESCE((SELECT SUM(o.amount) FROM payroll_receivable_offsets o "
                                    "WHERE o.organisation_id=r.organisation_id AND o.receivable_id=r.id AND o.status='Proposed'),0) reserved "
                                    "FROM payroll_employee_receivables r WHERE r.organisation_id=? AND r.employee_id=? AND r.status='Open' "
                                    "ORDER BY r.created_at,r.id", (organisation_id, employee_id)) if payout_type == 'salary' else []
                available = amount
                for receivable_row in remaining:
                    free = money(decimal(receivable_row['remaining_amount']) - decimal(receivable_row['reserved']))
                    offset = min(available, free)
                    if offset <= 0:
                        continue
                    tx.execute("INSERT INTO payroll_receivable_offsets(id,organisation_id,receivable_id,payout_batch_id,employee_id,amount,created_at,created_by) "
                               "VALUES (?,?,?,?,?,?,?,?)",
                               (new_id(), organisation_id, receivable_row['id'], batch_id, employee_id,
                                db_number(offset), now, actor))
                    available -= offset
                    if available <= 0:
                        break
            audit(tx, organisation_id, actor, 'payroll.payout.created', 'payroll_payout_batch', batch_id,
                  {'pay_run_id': run_id, 'payout_date': chosen_date})
            return self.get(organisation_id, batch_id, tx=tx)

    def mark_paid(self, organisation_id, batch_id, bank_account_id, *, actor):
        with self.db.transaction() as tx:
            batch = self._batch(tx, organisation_id, batch_id)
            if batch['status'] != 'Draft':
                raise PayoutConflict('Only draft payouts can be marked paid')
            claimed = tx.execute("UPDATE payroll_payout_batches SET status='Paid' WHERE organisation_id=? AND id=? AND status='Draft'",
                                 (organisation_id, batch_id))
            if claimed.rowcount != 1:
                raise PayoutConflict('Only draft payouts can be marked paid')
            positive_lines = [line for line in batch['lines'] if money(line['amount']) > 0]
            if not positive_lines:
                tx.execute("UPDATE payroll_payout_batches SET paid_at=?,paid_by=? WHERE organisation_id=? AND id=?",
                           (utc_now(), actor, organisation_id, batch_id))
                audit(tx, organisation_id, actor, 'payroll.payout.offset_settled', 'payroll_payout_batch', batch_id)
                return self.get(organisation_id, batch_id, tx=tx)
            bank = tx.one('SELECT * FROM bank_accounts WHERE organisation_id=? AND id=? AND active=1', (organisation_id, bank_account_id))
            if not bank:
                raise KeyError('Bank account not found')
            frozen = tx.one("SELECT account_id FROM pay_run_posting_accounts WHERE organisation_id=? AND pay_run_id=? AND role='PAYROLL_SALARY_PAYABLE'",
                            (organisation_id, batch['pay_run_id']))
            if not frozen:
                from payroll import PayrollService
                frozen = PayrollService._posting_account(tx, organisation_id, 'PAYROLL_SALARY_PAYABLE')
            if not frozen:
                raise ValueError('The salary payable account is missing')
            amount = sum((money(line['amount']) for line in positive_lines), Decimal(0))
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
            claimed = tx.execute("UPDATE payroll_payout_batches SET status='Cancelled' WHERE organisation_id=? AND id=? AND status!='Cancelled'",
                                 (organisation_id, batch_id))
            if claimed.rowcount != 1:
                raise PayoutConflict('Payout is already cancelled')
            tx.execute("UPDATE payroll_receivable_offsets SET status='Cancelled' WHERE organisation_id=? AND payout_batch_id=? AND status='Proposed'",
                       (organisation_id, batch_id))
            reversal_id = None
            if batch['status'] == 'Paid':
                if batch.get('posted_batch_id'):
                    reversal = LedgerService(self.db).reverse(batch['posted_batch_id'], reversal_date=date.today().isoformat(),
                                                                actor=actor, reason='Payroll payout cancelled', tx=tx)
                    reversal_id = reversal['id']
                for offset in tx.rows("SELECT * FROM payroll_receivable_offsets WHERE organisation_id=? AND payout_batch_id=? AND status='Posted'",
                                      (organisation_id, batch_id)):
                    if offset['posting_batch_id']:
                        LedgerService(self.db).reverse(offset['posting_batch_id'], reversal_date=date.today().isoformat(),
                                                       actor=actor, reason='Payroll receivable offset cancelled', tx=tx)
                    tx.execute("UPDATE payroll_employee_receivables SET remaining_amount=remaining_amount+?,status='Open' WHERE organisation_id=? AND id=?",
                               (offset['amount'], organisation_id, offset['receivable_id']))
                    tx.execute("UPDATE payroll_receivable_offsets SET status='Cancelled' WHERE organisation_id=? AND id=?",
                               (organisation_id, offset['id']))
            tx.execute("UPDATE payroll_payout_batches SET status='Cancelled',reversal_batch_id=? WHERE organisation_id=? AND id=?",
                       (reversal_id, organisation_id, batch_id))
            audit(tx, organisation_id, actor, 'payroll.payout.cancelled', 'payroll_payout_batch', batch_id,
                  {'reversal_batch_id': reversal_id})
            return self.get(organisation_id, batch_id, tx=tx)

    def open_receivables(self, organisation_id):
        return self.db.rows("SELECT r.id,r.employee_id,e.name,r.source_run_id,r.amount,r.remaining_amount,r.created_at "
                            "FROM payroll_employee_receivables r JOIN employees e ON e.organisation_id=r.organisation_id AND e.id=r.employee_id "
                            "WHERE r.organisation_id=? AND r.status='Open' AND r.remaining_amount>0 ORDER BY r.created_at,r.id",
                            (organisation_id,))

    def confirm_offsets(self, organisation_id, batch_id, *, actor):
        with self.db.transaction() as tx:
            batch = self._batch(tx, organisation_id, batch_id)
            if batch['status'] != 'Draft':
                raise PayoutConflict('Only draft payouts can confirm receivable offsets')
            offsets = tx.rows("SELECT o.*,r.remaining_amount FROM payroll_receivable_offsets o "
                              "JOIN payroll_employee_receivables r ON r.organisation_id=o.organisation_id AND r.id=o.receivable_id "
                              "WHERE o.organisation_id=? AND o.payout_batch_id=? AND o.status='Proposed' ORDER BY o.created_at,o.id",
                              (organisation_id, batch_id))
            if not offsets:
                return self.get(organisation_id, batch_id, tx=tx)
            from payroll import PayrollService
            payable = PayrollService._posting_account(tx, organisation_id, 'PAYROLL_SALARY_PAYABLE')
            receivable = PayrollService._posting_account(tx, organisation_id, 'PAYROLL_EMPLOYEE_RECEIVABLE')
            by_employee = {line['employee_id']: line for line in batch['lines']}
            total = Decimal(0)
            reductions = {}
            for offset in offsets:
                amount = money(offset['amount'])
                line = by_employee.get(offset['employee_id'])
                reductions[offset['employee_id']] = reductions.get(offset['employee_id'], Decimal(0)) + amount
                if not line or reductions[offset['employee_id']] > money(line.get('requested_amount') or line['amount']):
                    raise PayoutConflict('Receivable offset exceeds the payout line')
                tx.execute("UPDATE payroll_employee_receivables SET remaining_amount=?,status=? WHERE organisation_id=? AND id=?",
                           (db_number(money(decimal(offset['remaining_amount']) - amount)),
                            'Settled' if money(decimal(offset['remaining_amount']) - amount) == 0 else 'Open',
                            organisation_id, offset['receivable_id']))
                total += amount
            for employee_id, reduction in reductions.items():
                line = by_employee[employee_id]
                if reduction > money(line['amount']):
                    raise PayoutConflict('Receivable offset exceeds the payout line')
                cash_amount = money(decimal(line['amount']) - reduction)
                if cash_amount:
                    tx.execute("UPDATE payroll_payout_lines SET amount=? WHERE organisation_id=? AND id=?",
                               (db_number(cash_amount), organisation_id, line['id']))
                else:
                    tx.execute("DELETE FROM payroll_payout_lines WHERE organisation_id=? AND id=?",
                               (organisation_id, line['id']))
            posting = LedgerService(self.db).post(
                organisation_id=organisation_id, voucher_type='payroll_receivable_offset', voucher_id=batch_id,
                voucher_code='PRO-' + batch_id[:12], posting_date=batch['payout_date'],
                lines=[PostingLine(payable['id'], debit=total, memo='Employee payroll receivable offset',
                                   source_line_type='payroll_receivable_offset', source_line_id=batch_id),
                       PostingLine(receivable['id'], credit=total, memo='Employee payroll receivable offset',
                                   source_line_type='payroll_receivable_offset', source_line_id=batch_id)],
                actor=actor, currency='EUR', tx=tx)
            tx.execute("UPDATE payroll_receivable_offsets SET status='Posted',confirmed_at=?,confirmed_by=?,posting_batch_id=? "
                       "WHERE organisation_id=? AND payout_batch_id=? AND status='Proposed'",
                       (utc_now(), actor, posting['id'], organisation_id, batch_id))
            audit(tx, organisation_id, actor, 'payroll.receivable_offsets.confirmed', 'payroll_payout_batch', batch_id,
                  {'amount': db_number(total), 'posting_batch_id': posting['id']})
            return self.get(organisation_id, batch_id, tx=tx)

    def _batch(self, tx, organisation_id, batch_id):
        batch = tx.one('SELECT * FROM payroll_payout_batches WHERE organisation_id=? AND id=?', (organisation_id, batch_id))
        if not batch:
            raise KeyError('Payout not found')
        batch['lines'] = tx.rows('SELECT * FROM payroll_payout_lines WHERE organisation_id=? AND payout_batch_id=? ORDER BY employee_id', (organisation_id, batch_id))
        batch['offsets'] = tx.rows('SELECT * FROM payroll_receivable_offsets WHERE organisation_id=? AND payout_batch_id=? ORDER BY created_at,id', (organisation_id, batch_id))
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

    def summary(self, organisation_id, *, run_id=None):
        with self.db.transaction() as tx:
            self._org(tx, organisation_id)
            query = "SELECT id,period,total_net FROM pay_runs WHERE organisation_id=? AND status='Approved'"
            params = [organisation_id]
            if run_id:
                query += ' AND id=?'; params.append(run_id)
            query += ' ORDER BY period DESC,id'
            runs = tx.rows(query, params)
            result = []
            for run in runs:
                items = self._outstanding(tx, organisation_id, run['id'])
                safe_items = []
                for item in items:
                    paid = tx.one("SELECT COALESCE(SUM(l.amount),0) amount FROM payroll_payout_lines l "
                                  "JOIN payroll_payout_batches b ON b.organisation_id=l.organisation_id AND b.id=l.payout_batch_id "
                                  "WHERE b.organisation_id=? AND b.pay_run_id=? AND b.status='Paid' AND l.employee_id=?",
                                  (organisation_id, run['id'], item['employee_id']))
                    offsets = tx.one("SELECT COALESCE(SUM(o.amount),0) amount FROM payroll_receivable_offsets o "
                                     "JOIN payroll_payout_batches b ON b.organisation_id=o.organisation_id AND b.id=o.payout_batch_id "
                                     "WHERE b.organisation_id=? AND b.pay_run_id=? AND b.status='Paid' AND o.employee_id=? AND o.status='Posted'",
                                     (organisation_id, run['id'], item['employee_id']))
                    item['paid'] = money(decimal(paid['amount']) + decimal(offsets['amount']))
                    item['pending'] = money(decimal(item['net']) - item['unpaid'] - item['paid'])
                    item['net'] = money(item['net'])
                    safe_items.append({key: item[key] for key in
                                       ('employee_id', 'name', 'net', 'paid', 'pending', 'unpaid')})
                result.append({
                    'pay_run_id': run['id'], 'period': run['period'],
                    'net': db_number(sum((money(item['net']) for item in items), Decimal('0'))),
                    'paid': db_number(sum((item['paid'] for item in items), Decimal('0'))),
                    'pending': db_number(sum((item['pending'] for item in items), Decimal('0'))),
                    'unpaid': db_number(sum((item['unpaid'] for item in items), Decimal('0'))),
                    'employees': safe_items,
                })
            return result

    @staticmethod
    def _org(tx, organisation_id):
        if not tx.one('SELECT id FROM organisations WHERE id=?', (organisation_id,)):
            raise KeyError('Organisation not found')


class PayoutConflict(ValueError):
    pass
