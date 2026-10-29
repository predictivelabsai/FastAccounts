"""Payroll payout batches and immutable bank settlement postings."""
from datetime import date
from decimal import Decimal

from core_utils import audit, db_number, decimal, money, new_id, utc_now
from database import Database, get_database
from ledger import LedgerService, PostingLine
from payroll_payday import payday_for_period
from payroll_rules import settlement_date
from payroll_rules import remaining_monthly_exemption, rules_for
from payroll_tax_repository import monthly_exemption_used
from payroll import calculate_pay
from payroll_tsd_types import payment_type

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
                           "WHERE b.organisation_id=? AND b.pay_run_id=? AND b.status!='Cancelled' AND l.employee_id=? "
                           "AND (b.payout_type!='advance' OR b.status='Paid')",
                           (organisation_id, run_id, item['employee_id']))
            offsets = tx.one("SELECT COALESCE(SUM(o.amount),0) amount FROM payroll_receivable_offsets o "
                             "JOIN payroll_payout_batches b ON b.organisation_id=o.organisation_id AND b.id=o.payout_batch_id "
                             "WHERE b.organisation_id=? AND b.pay_run_id=? AND b.status!='Cancelled' "
                             "AND o.employee_id=? AND o.status IN ('Proposed','Posted')",
                             (organisation_id, run_id, item['employee_id']))
            item['unpaid'] = money(decimal(item['net']) - decimal(paid['amount']) - decimal(offsets['amount']))
        return items

    def _recalculate_later_correction(self, tx, organisation_id, run, payout_date):
        if run.get('kind') != 'correction' or payout_date[:7] == (run.get('settlement_date') or run['period'] + '-01')[:7]:
            return {}
        existing = tx.one("SELECT payout_date FROM payroll_payout_batches WHERE organisation_id=? AND pay_run_id=? "
                          "AND payout_type='salary' AND status!='Cancelled' ORDER BY payout_date,id LIMIT 1",
                          (organisation_id, run['id']))
        if existing and existing['payout_date'][:7] != payout_date[:7]:
            raise PayoutConflict('All later-month correction payouts must use the same payment month')
        previous = tx.one("SELECT id FROM pay_runs WHERE organisation_id=? AND original_run_id=? AND kind='correction' "
                          "AND status='Approved' AND id<>? ORDER BY approved_at DESC,id DESC LIMIT 1",
                          (organisation_id, run['original_run_id'], run['id']))
        baseline_id = previous['id'] if previous else run['original_run_id']
        baseline = {row['employee_id']: row for row in tx.rows(
            'SELECT * FROM pay_run_items WHERE organisation_id=? AND pay_run_id=?',
            (organisation_id, baseline_id))}
        from datetime import date
        recalculated = {}
        pay_date = date.fromisoformat(payout_date)
        rules = rules_for(pay_date)
        for item in tx.rows('SELECT * FROM pay_run_items WHERE organisation_id=? AND pay_run_id=? ORDER BY employee_id',
                            (organisation_id, run['id'])):
            prior = baseline.get(item['employee_id'])
            if not prior:
                raise PayoutConflict('Correction employees do not match the original run')
            gross_delta = money(decimal(item['gross']) - decimal(prior['gross']))
            if gross_delta <= 0:
                continue
            context = tx.one('SELECT * FROM pay_item_context WHERE organisation_id=? AND item_id=?',
                             (organisation_id, item['id']))
            if not context:
                raise PayoutConflict('Correction tax calculation snapshot is missing')
            mode = context.get('tax_free_mode') or ('maximum' if context.get('apply_tax_free_minimum') else 'none')
            used = monthly_exemption_used(tx, organisation_id, item['employee_id'], payout_date[:7])
            remaining = remaining_monthly_exemption(mode, context.get('tax_free_amount'),
                                                     rules.basic_exemption, used)
            employee = {
                'gross_salary': str(gross_delta), 'funded_pension_percent': item['funded_pension_percent'],
                'board_member': bool(item['board_member']), 'pay_basis': item['pay_basis'],
                'apply_tax_free_minimum': bool(context.get('apply_tax_free_minimum')),
                'tax_free_mode': mode, 'tax_free_amount': context.get('tax_free_amount'),
                'unemployment_applies': context.get('unemployment_applies'),
                'social_tax_minimum_exemption': item.get('social_tax_minimum_exemption'),
                'employment_start_date': context.get('employment_start_date'),
                'employment_end_date': context.get('employment_end_date'),
            }
            hours = None
            if employee['pay_basis'] == 'hourly':
                employee['hourly_rate'] = item['hourly_rate']
                hours = gross_delta / decimal(item['hourly_rate'])
            amounts = calculate_pay(employee, period=run['period'], hours=hours,
                                    settlement_on=pay_date, exemption_remaining=remaining)
            tx.execute('UPDATE pay_run_items SET payout_net_delta=? WHERE organisation_id=? AND id=?',
                       (db_number(amounts['net']), organisation_id, item['id']))
            tsd_item = item | amounts | {'gross': gross_delta, 'gross_salary': gross_delta}
            from payroll_tsd_breakdown import calculate_tsd_breakdown
            contract_lines = tx.rows('SELECT * FROM payroll_contract_run_lines WHERE organisation_id=? AND pay_run_item_id=?',
                                     (organisation_id, item['id'])) if tx.table_exists('payroll_contract_run_lines') else []
            records = calculate_tsd_breakdown(item=tsd_item, components=[], context=context,
                                              contract_lines=contract_lines)
            previous_net = money(decimal(item['net']) - decimal(prior['net']))
            adjustments = {
                'PAYROLL_SALARY_PAYABLE': money(amounts['net'] - previous_net),
                'PAYROLL_INCOME_WITHHELD': money(amounts['income_tax'] - (decimal(item['income_tax']) - decimal(prior['income_tax']))),
                'PAYROLL_PENSION_WITHHELD': money(amounts['funded_pension'] - (decimal(item['funded_pension']) - decimal(prior['funded_pension']))),
                'PAYROLL_UI_ACCRUED': money(amounts['ui_employee'] + amounts['ui_employer'] -
                    (decimal(item['ui_employee']) + decimal(item['ui_employer']) -
                     decimal(prior['ui_employee']) - decimal(prior['ui_employer']))),
                'PAYROLL_SOCIAL_ACCRUED': money(amounts['social_tax'] - (decimal(item['social_tax']) - decimal(prior['social_tax']))),
                'PAYROLL_SOCIAL': money(-amounts['social_tax'] + (decimal(item['social_tax']) - decimal(prior['social_tax']))),
                'PAYROLL_UI': money(-amounts['ui_employer'] + (decimal(item['ui_employer']) - decimal(prior['ui_employer']))),
            }
            recalculated[item['id']] = {'records': records, 'adjustments': adjustments}
        return recalculated

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
            if payout_type == 'withholding':
                return self._create_withholding(tx, organisation_id, run, chosen_date, actor,
                                                amounts=amounts, bank_account_id=bank_account_id)
            payout_tsd = self._recalculate_later_correction(tx, organisation_id, run, chosen_date) if payout_type == 'salary' else {}
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
            adjustment_values = {}
            for item_id, payout_data in payout_tsd.items():
                for role, amount in payout_data['adjustments'].items():
                    adjustment_values[role] = money(adjustment_values.get(role, Decimal(0)) + amount)
                for record in payout_data['records']:
                    tx.execute('INSERT INTO payroll_payout_tsd_lines(id,organisation_id,payout_batch_id,pay_run_item_id,payment_type,payment_type_name,amount,social_tax_base,social_tax,social_tax_minimum_topup,ui_employee_base,ui_employee,ui_employer_base,ui_employer,ii_pillar_base,ii_pillar,exemption_610,taxable_amount,income_tax) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               (f'{batch_id}:{item_id}:{record["payment_type"]}', organisation_id, batch_id,
                                item_id, record['payment_type'], payment_type(record['payment_type']).name,
                                *(db_number(record[field]) for field in ('amount','social_tax_base','social_tax','social_tax_minimum_topup',
                                  'ui_employee_base','ui_employee','ui_employer_base','ui_employer','ii_pillar_base','ii_pillar',
                                  'exemption_610','taxable_amount','income_tax'))))
            if any(adjustment_values.values()):
                frozen_accounts = {row['role']: row['account_id'] for row in tx.rows(
                    'SELECT role,account_id FROM pay_run_posting_accounts WHERE organisation_id=? AND pay_run_id=?',
                    (organisation_id, run_id))}
                adjustment_lines = []
                for role, signed_credit in adjustment_values.items():
                    if not signed_credit:
                        continue
                    adjustment_lines.append(PostingLine(frozen_accounts[role], debit=abs(signed_credit) if signed_credit < 0 else Decimal(0),
                        credit=signed_credit if signed_credit > 0 else Decimal(0), memo='Later-month payroll correction tax adjustment',
                        source_line_type='payroll_payout', source_line_id=batch_id))
                LedgerService(self.db).post(organisation_id=organisation_id,
                    voucher_type='payroll_correction_tax_adjustment', voucher_id=batch_id,
                    voucher_code='PAY-ADJ-' + batch_id[:12], posting_date=chosen_date,
                    lines=adjustment_lines, actor=actor, currency='EUR', tx=tx)
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

    def _create_withholding(self, tx, organisation_id, run, chosen_date, actor, *, amounts=None, bank_account_id=None):
        rows = tx.rows('SELECT l.recipient_id,r.name recipient_name,r.iban,r.reference_number,r.default_description,'
            'e.name employee_name,l.amount,l.description,a.payment_description '
            'FROM payroll_withholding_run_lines l JOIN payroll_withholding_recipients r '
            'ON r.organisation_id=l.organisation_id AND r.id=l.recipient_id '
            'JOIN employees e ON e.organisation_id=l.organisation_id AND e.id=l.employee_id '
            'LEFT JOIN payroll_withholding_agreements a ON a.organisation_id=l.organisation_id AND a.id=l.agreement_id '
            'WHERE l.organisation_id=? AND l.pay_run_id=? AND l.amount>0 '
            'ORDER BY r.name,e.name,l.id', (organisation_id, run['id']))
        recipients = {}
        for row in rows:
            entry = recipients.setdefault(row['recipient_id'], row | {'amount_total': Decimal('0.00'), 'references': []})
            entry['amount_total'] = money(entry['amount_total'] + decimal(row['amount']))
            detail = row['payment_description'] or row['description'] or row['default_description']
            reference = f"{row['employee_name']}: {detail}" if detail else row['employee_name']
            if reference not in entry['references']:
                entry['references'].append(reference)
        if not recipients:
            raise ValueError('No withholding amounts are available for payout')
        paid = tx.rows("SELECT l.recipient_id,SUM(l.amount) amount FROM payroll_withholding_payout_lines l "
            "JOIN payroll_withholding_payout_batches w ON w.organisation_id=l.organisation_id AND w.id=l.withholding_payout_id "
            "JOIN payroll_payout_batches b ON b.organisation_id=w.organisation_id AND b.id=w.payout_batch_id "
            "WHERE w.organisation_id=? AND w.pay_run_id=? AND b.status!='Cancelled' GROUP BY l.recipient_id",
            (organisation_id, run['id']))
        paid_by_recipient = {row['recipient_id']: money(row['amount']) for row in paid}
        requested = amounts if amounts is not None else {
            recipient_id: str(money(data['amount_total'] - paid_by_recipient.get(recipient_id, Decimal('0.00'))))
            for recipient_id, data in recipients.items()
            if data['amount_total'] > paid_by_recipient.get(recipient_id, Decimal('0.00'))}
        if not requested:
            raise ValueError('No unpaid withholding remains for this run')
        bank_id = bank_account_id
        if bank_id and not tx.one('SELECT id FROM bank_accounts WHERE organisation_id=? AND id=? AND active=1', (organisation_id, bank_id)):
            raise KeyError('Bank account not found')
        batch_id, now = new_id(), utc_now()
        tx.execute('INSERT INTO payroll_payout_batches(id,organisation_id,pay_run_id,payout_type,payout_date,bank_account_id,created_at) VALUES (?,?,?,?,?,?,?)',
                   (batch_id, organisation_id, run['id'], 'withholding', chosen_date, bank_id, now))
        withholding_id = new_id()
        tx.execute("INSERT INTO payroll_withholding_payout_batches(id,organisation_id,pay_run_id,payout_batch_id,status,created_at) VALUES (?,?,?,?,'Draft',?)",
                   (withholding_id, organisation_id, run['id'], batch_id, now))
        for recipient_id, raw_amount in requested.items():
            recipient = recipients.get(recipient_id)
            if not recipient:
                raise KeyError('Recipient not found in pay run')
            amount = money(raw_amount)
            outstanding = money(recipient['amount_total'] - paid_by_recipient.get(recipient_id, Decimal('0.00')))
            if amount <= 0:
                raise ValueError('Payout amounts must be positive')
            if amount > outstanding:
                raise PayoutConflict('Payout exceeds the recipient unpaid withholding amount')
            description = '; '.join(recipient['references'])
            tx.execute('INSERT INTO payroll_withholding_payout_lines(id,organisation_id,withholding_payout_id,recipient_id,amount,iban,description,employee_references) VALUES (?,?,?,?,?,?,?,?)',
                (new_id(), organisation_id, withholding_id, recipient_id, db_number(amount), recipient['iban'],
                 description[:140], __import__('json').dumps(recipient['references'], ensure_ascii=False)))
        audit(tx, organisation_id, actor, 'payroll.payout.created', 'payroll_payout_batch', batch_id,
              {'pay_run_id': run['id'], 'payout_date': chosen_date, 'payout_type': 'withholding'})
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
            if batch['payout_type'] == 'withholding':
                return self._mark_withholding_paid(tx, organisation_id, batch, bank_account_id, actor)
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

    def _mark_withholding_paid(self, tx, organisation_id, batch, bank_account_id, actor):
        bank = tx.one('SELECT * FROM bank_accounts WHERE organisation_id=? AND id=? AND active=1', (organisation_id, bank_account_id))
        if not bank:
            raise KeyError('Bank account not found')
        frozen = {row['role']: row['account_id'] for row in tx.rows(
            'SELECT role,account_id FROM pay_run_posting_accounts WHERE organisation_id=? AND pay_run_id=?',
            (organisation_id, batch['pay_run_id']))}
        lines = batch['withholding_lines']
        if not lines:
            raise ValueError('Withholding payout has no payment lines')
        total = sum((money(line['amount']) for line in lines), Decimal('0.00'))
        by_recipient = {}
        for row in tx.rows('SELECT recipient_id,component_type,amount FROM payroll_withholding_run_lines WHERE organisation_id=? AND pay_run_id=?',
                           (organisation_id, batch['pay_run_id'])):
            role = 'PAYROLL_BAILIFF' if row['component_type'] in ('alimony', 'bailiff') else 'PAYROLL_DEDUCTION'
            recipient_roles = by_recipient.setdefault(row['recipient_id'], {})
            recipient_roles[role] = money(recipient_roles.get(role, Decimal('0.00')) + decimal(row['amount']))
        allocated = {}
        for payout_line in lines:
            recipient_roles = by_recipient.get(payout_line['recipient_id'], {})
            role_items = [(role, amount) for role, amount in recipient_roles.items() if amount]
            role_total = sum((amount for _, amount in role_items), Decimal('0.00'))
            remaining = money(payout_line['amount'])
            for index, (role, amount) in enumerate(role_items):
                debit = remaining if index == len(role_items) - 1 else min(remaining, money(payout_line['amount'] * amount / role_total))
                allocated[role] = money(allocated.get(role, Decimal('0.00')) + debit)
                remaining = money(remaining - debit)
        posting_lines = []
        for role in ('PAYROLL_BAILIFF', 'PAYROLL_DEDUCTION'):
            debit = allocated.get(role, Decimal('0.00'))
            if not debit:
                continue
            account_id = frozen.get(role)
            if not account_id:
                from payroll import PayrollService
                account = PayrollService._posting_account(tx, organisation_id, role)
                account_id = account['id'] if account else None
            if not account_id:
                raise ValueError(f'The {role} account is missing')
            posting_lines.append(PostingLine(account_id, debit=debit, memo='Payroll withholding payout ' + batch['payout_date'],
                source_line_type='payroll_payout', source_line_id=batch['id']))
        posting_lines.append(PostingLine(bank['ledger_account_id'], credit=total, memo='Payroll withholding payout ' + batch['payout_date'],
            source_line_type='payroll_payout', source_line_id=batch['id']))
        posting = LedgerService(self.db).post(organisation_id=organisation_id, voucher_type='payroll_withholding_payout',
            voucher_id=batch['id'], voucher_code='PAY-WH-' + batch['id'][:12], posting_date=batch['payout_date'],
            lines=posting_lines, actor=actor, currency='EUR', tx=tx)
        tx.execute("UPDATE payroll_payout_batches SET status='Paid',bank_account_id=?,paid_at=?,paid_by=?,posted_batch_id=? WHERE organisation_id=? AND id=?",
                   (bank_account_id, utc_now(), actor, posting['id'], organisation_id, batch['id']))
        tx.execute("UPDATE payroll_withholding_payout_batches SET status='Paid' WHERE organisation_id=? AND payout_batch_id=?",
                   (organisation_id, batch['id']))
        audit(tx, organisation_id, actor, 'payroll.payout.paid', 'payroll_payout_batch', batch['id'], {'posted_batch_id': posting['id']})
        return self.get(organisation_id, batch['id'], tx=tx)

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
            if batch['payout_type'] == 'withholding':
                tx.execute("UPDATE payroll_withholding_payout_batches SET status='Cancelled' WHERE organisation_id=? AND payout_batch_id=?",
                           (organisation_id, batch_id))
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
        batch['withholding_lines'] = tx.rows('SELECT l.*,r.name recipient_name,r.reference_number FROM payroll_withholding_payout_lines l '
            'JOIN payroll_withholding_payout_batches w ON w.organisation_id=l.organisation_id AND w.id=l.withholding_payout_id '
            'JOIN payroll_withholding_recipients r ON r.organisation_id=l.organisation_id AND r.id=l.recipient_id '
            'WHERE w.organisation_id=? AND w.payout_batch_id=? ORDER BY r.name,l.id', (organisation_id, batch_id))
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
                                  "WHERE b.organisation_id=? AND b.pay_run_id=? AND b.status='Paid' AND l.employee_id=? "
                                  "AND b.payout_type!='withholding'",
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
