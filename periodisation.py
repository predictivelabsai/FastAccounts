"""Purchase periodisation without changing the original bill or posted lines.

Draft bills debit PERIODISED_PURCHASES at approval. Already posted bills gain an
explicit, balanced expense-to-deferred-cost reclassification on the bill date.
Each period then debits the selected expense account and credits deferred cost.
Input VAT remains deductible in full on the original bill; portions contain no
VAT or AP posting. Thus neither expenses, VAT nor the supplier liability double
count. Draft schedules reserve the cost but do not generate expense transfers.
"""
from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from core_utils import audit, decimal, four_dp, money, new_id, today as current_day
from database import get_database
from ledger import LedgerService, PostingLine
from periodisation_repository import PeriodisationRepository


class PeriodisationService:
    def __init__(self, db=None):
        self.db = db or get_database()
        self.ledger = LedgerService(self.db)

    @staticmethod
    def _progress(row):
        row['net_amount'] = money(row['net_amount'])
        row['vat_amount'] = money(row['vat_amount'])
        for period in row['periods']:
            period['net_amount'] = money(period['net_amount'])
            period['vat_amount'] = money(period['vat_amount'])
        row['posted_periods'] = sum(p['status'] == 'Posted' for p in row['periods'])
        row['posted_amount'] = sum((p['net_amount'] for p in row['periods'] if p['status'] == 'Posted'), Decimal('0.00'))
        row['pending_amount'] = sum((p['net_amount'] for p in row['periods'] if p['status'] == 'Pending'), Decimal('0.00'))
        row['cancelled_amount'] = sum((p['net_amount'] for p in row['periods'] if p['status'] == 'Cancelled'), Decimal('0.00'))
        return row

    def get(self, organisation_id, schedule_id):
        with self.db.transaction() as tx:
            return self._progress(PeriodisationRepository(tx, organisation_id).get(schedule_id))

    def list(self, organisation_id):
        with self.db.transaction() as tx:
            repo = PeriodisationRepository(tx, organisation_id)
            return [self._progress(repo.get(r['id'])) for r in repo.ids()]

    @staticmethod
    def _amount(value):
        try:
            raw = decimal(value)
            if not raw.is_finite() or abs(raw) >= 10 ** 16 or raw != four_dp(raw) or raw != money(raw) or raw <= 0:
                raise ValueError('Schedule amount must be positive, finite and in whole cents')
            return money(raw)
        except (InvalidOperation, TypeError):
            raise ValueError('Schedule amount must be positive, finite and in whole cents') from None

    def create(self, organisation_id, *, bill_id, expense_account_id, start_period,
               number_of_periods, actor, amount=None, split_rule='equal_first', status='Active', notes=''):
        start = date.fromisoformat(start_period)
        if isinstance(number_of_periods, bool) or not isinstance(number_of_periods, int) or not 1 <= number_of_periods <= 120:
            raise ValueError('Number of periods must be between 1 and 120')
        if split_rule not in {'equal_first', 'equal_last'} or status not in {'Draft', 'Active'}:
            raise ValueError('Invalid purchase schedule configuration')
        with self.db.transaction() as tx:
            repo = PeriodisationRepository(tx, organisation_id)
            org = repo.lock_organisation()
            bill = repo.bill(bill_id)
            if repo.for_bill(bill_id):
                raise ValueError('This bill already has a purchase schedule')
            if bill['document_type'] != 'bill' or bill['status'] not in {'Draft', 'In Review', 'Approved', 'Part Paid', 'Paid'}:
                raise ValueError('A valid purchase bill is required')
            if bill['currency'] != org['base_currency'] or decimal(bill['exchange_rate']) != 1:
                raise ValueError('Periodisation requires the organisation base currency')
            if not bill['lines'] or any(l['account_type'] != 'Expense' for l in bill['lines']):
                raise ValueError('Periodisation requires expense bill lines')
            if sum((money(l['recoverable_tax']) for l in bill['lines']), Decimal(0)) != money(bill['tax_total']):
                raise ValueError('Periodisation requires fully recoverable VAT or no VAT')
            account, deferred = repo.account(expense_account_id), repo.deferred_account()
            if not account or account['account_type'] != 'Expense' or not deferred or deferred['account_type'] != 'Asset':
                raise ValueError('Active expense and deferred accounts in this organisation are required')
            total = self._amount(bill['subtotal'] if amount is None else amount)
            if total != money(bill['subtotal']):
                raise ValueError('Schedule total must equal the bill net amount')
            # Whole cents, with the complete residual assigned deterministically.
            portion = (total / number_of_periods).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
            if portion <= 0:
                raise ValueError('Each purchase period must contain at least one penny or cent')
            portions = []
            for i in range(number_of_periods):
                month = start.year * 12 + start.month - 1 + i
                day = date(month // 12, month % 12 + 1, min(start.day, monthrange(month // 12, month % 12 + 1)[1]))
                if day.isoformat() < bill['bill_date']:
                    raise ValueError('Purchase periods cannot precede the bill date')
                self.ledger._validate_period(tx, organisation_id, day.isoformat())
                value = portion + (total - portion * number_of_periods if i == (0 if split_rule == 'equal_first' else number_of_periods - 1) else Decimal(0))
                portions.append((day.isoformat(), value))
            schedule_id = new_id()
            repo.save(schedule_id, dict(bill_id=bill_id, expense_account_id=expense_account_id,
                deferred_account_id=deferred['id'], start_period=start.isoformat(), net_amount=total,
                split_rule=split_rule, currency=bill['currency'], status=status, notes=notes.strip()), portions, actor)
            if bill['posting_batch_id']:
                original = repo.batch(bill['posting_batch_id'])
                if not original or original['status'] != 'Posted':
                    raise ValueError('The original bill posting must be unreversed')
                grouped = defaultdict(Decimal)
                for line in bill['lines']:
                    grouped[line['account_id']] += money(line['net_amount'])
                lines = [PostingLine(deferred['id'], debit=total)]
                lines.extend(PostingLine(a, credit=v) for a, v in grouped.items() if v)
                batch = self.ledger.post(organisation_id=organisation_id, voucher_type='purchase_deferral',
                    voucher_id=schedule_id, voucher_code='DEFER-' + bill['supplier_number'],
                    posting_date=bill['bill_date'], lines=lines, actor=actor, currency=bill['currency'], tx=tx)
                repo.funding(schedule_id, batch['id'])
            audit(tx, organisation_id, actor, 'periodisation.created', 'purchase_schedule', schedule_id)
            return self._progress(repo.get(schedule_id))

    def update(self, organisation_id, schedule_id, *, actor, status=None, notes=None):
        with self.db.transaction() as tx:
            repo = PeriodisationRepository(tx, organisation_id)
            repo.lock_organisation()
            schedule = repo.get(schedule_id)
            if schedule['status'] != 'Draft' or status not in {None, 'Active'}:
                raise ValueError('Only Draft purchase schedules can be activated or edited')
            repo.transition(schedule_id, status or 'Draft', schedule['notes'] if notes is None else notes.strip())
            audit(tx, organisation_id, actor, 'periodisation.updated', 'purchase_schedule', schedule_id)
            return self._progress(repo.get(schedule_id))

    def post_due(self, organisation_id, schedule_id, *, actor, as_at=None, period_id=None):
        day = date.fromisoformat(as_at or current_day()).isoformat()
        if day > current_day():
            raise ValueError('Purchase periods cannot be posted in advance')
        with self.db.transaction() as tx:
            repo = PeriodisationRepository(tx, organisation_id)
            repo.lock_organisation()
            schedule = repo.get(schedule_id)
            selected = [p for p in schedule['periods'] if period_id is None or p['id'] == period_id]
            if period_id and not selected:
                raise KeyError('Purchase period not found')
            if schedule['status'] == 'Completed' or (period_id and selected[0]['status'] == 'Posted'):
                return self._progress(schedule)
            if schedule['status'] != 'Active':
                raise ValueError('Only Active purchase schedules can post periods')
            bill = repo.bill(schedule['bill_id'])
            for batch_id in (bill['posting_batch_id'], schedule['funding_batch_id']):
                batch = repo.batch(batch_id) if batch_id else None
                if not batch or batch['status'] != 'Posted':
                    raise ValueError('Approve the bill and retain unreversed funding before posting periods')
            for period in selected:
                if period['status'] != 'Pending':
                    continue
                if period['period_date'] > day:
                    if period_id:
                        raise ValueError('Purchase period is not due')
                    continue
                amount = money(period['net_amount'])
                batch = self.ledger.post(organisation_id=organisation_id, voucher_type='purchase_period',
                    voucher_id=period['id'], voucher_code='PER-' + bill['supplier_number'] + '-' + period['period_date'],
                    posting_date=period['period_date'], currency=schedule['currency'], actor=actor, tx=tx,
                    lines=[PostingLine(schedule['expense_account_id'], debit=amount, source_line_type='purchase_period', source_line_id=period['id']),
                           PostingLine(schedule['deferred_account_id'], credit=amount, source_line_type='purchase_period', source_line_id=period['id'])])
                repo.posted(schedule_id, period['id'], batch['id'])
                audit(tx, organisation_id, actor, 'periodisation.posted', 'purchase_schedule_period', period['id'], {'posting_batch_id': batch['id']})
            result = repo.get(schedule_id)
            if all(p['status'] == 'Posted' for p in result['periods']):
                repo.transition(schedule_id, 'Completed', schedule['notes'])
                result = repo.get(schedule_id)
            return self._progress(result)

    def cancel(self, organisation_id, schedule_id, *, actor):
        with self.db.transaction() as tx:
            repo = PeriodisationRepository(tx, organisation_id)
            repo.lock_organisation()
            schedule = repo.get(schedule_id)
            if schedule['status'] == 'Cancelled':
                return self._progress(schedule)
            if schedule['status'] == 'Completed':
                raise ValueError('Completed purchase schedules cannot be cancelled')
            if any(p['status'] == 'Pending' and p['period_date'] <= current_day() for p in schedule['periods']):
                raise ValueError('Post due periods before cancelling future periods')
            repo.cancel_future(schedule_id, current_day())
            repo.transition(schedule_id, 'Cancelled', schedule['notes'])
            audit(tx, organisation_id, actor, 'periodisation.cancelled', 'purchase_schedule', schedule_id)
            return self._progress(repo.get(schedule_id))

    def run_due(self, organisation_id, *, today=None, actor='automation'):
        day = date.fromisoformat(today or current_day()).isoformat()
        results = []
        for schedule in self.list(organisation_id):
            if schedule['status'] != 'Active' or not any(p['status'] == 'Pending' and p['period_date'] <= day for p in schedule['periods']):
                continue
            try:
                result = self.post_due(organisation_id, schedule['id'], actor=actor, as_at=day)
                results.append({'schedule_id': schedule['id'], 'status': 'Posted', 'posted_periods': result['posted_periods']})
            except Exception:
                results.append({'schedule_id': schedule['id'], 'status': 'Failed', 'error_message': 'Purchase periodisation failed'})
        return results
