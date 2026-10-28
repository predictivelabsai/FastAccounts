"""Pure leave-lot calculations and tenant-scoped liability reports."""
from datetime import date, timedelta
from decimal import Decimal
import re

from core_utils import decimal, money, audit, utc_now
from database import get_database
from payroll_absences import PayrollAbsenceService
from payroll_average import calculate_average_pay
from payroll_leave_liability import LeaveLot, accrued_days, expiry_date, liability_value


def _lots(entitlements, openings, absences, settings, employed_from, as_at, employed_to=None):
    lots = []
    opening_lots = []
    opening = openings[-1] if openings else None
    if employed_from or entitlements:
        start = max(date.fromisoformat(employed_from or entitlements[0]['effective_from']), date(1900, 1, 1))
        if opening:
            start = max(start, date.fromisoformat(opening['cutover_date']) + timedelta(days=1))
        through = min(as_at, date.fromisoformat(employed_to)) if employed_to else as_at
        for year in range(start.year, through.year + 1):
            year_start, year_end = date(year, 1, 1), min(date(year, 12, 31), through)
            boundaries = sorted({max(start, year_start), *(date.fromisoformat(row['effective_from']) for row in entitlements
                if year_start < date.fromisoformat(row['effective_from']) <= year_end)})
            for index, segment_start in enumerate(boundaries):
                segment_end = (boundaries[index + 1] - timedelta(days=1)) if index + 1 < len(boundaries) else year_end
                applicable = [row for row in entitlements if row['effective_from'] <= segment_start.isoformat()]
                if not applicable:
                    continue
                amount = accrued_days(applicable[-1]['days_per_year'], segment_start, segment_end, year)
                if amount:
                    lots.append(LeaveLot(amount, segment_start, expiry_date(year, settings['basic_expiry_policy']), 'basic'))
    if opening:
        cutover = date.fromisoformat(opening['cutover_date'])
        if cutover <= as_at:
            if decimal(opening['unused_days']):
                opening_lots.append(LeaveLot(decimal(opening['unused_days']), cutover,
                    expiry_date(cutover.year, settings['basic_expiry_policy']), 'basic'))
            if decimal(opening['extended_unused_days']):
                opening_lots.append(LeaveLot(decimal(opening['extended_unused_days']), cutover,
                    expiry_date(cutover.year, settings['extended_expiry_policy']), 'extended'))
            lots.extend(opening_lots)
    movements = []
    for lot in lots:
        movements.append({'type': 'opening' if any(lot is opening_lot for opening_lot in opening_lots) else 'accrual',
                          'date': lot.accrued_on.isoformat(), 'kind': lot.kind, 'days': str(lot.days),
                          'expires_on': lot.expires_on.isoformat() if lot.expires_on else None})
    balances = {index: lot.days for index, lot in enumerate(lots)}
    leave_rows = sorted((row for row in absences if row['absence_type'] in ('annual_leave', 'extended_leave')
                         and row['start_date'] <= as_at.isoformat()
                         and (not opening or row['start_date'] > opening['cutover_date'])),
                        key=lambda row: (row['start_date'], row['id']))
    for absence in leave_rows:
        end = min(date.fromisoformat(absence['end_date']), as_at)
        start = date.fromisoformat(absence['start_date'])
        days = Decimal(str(PayrollAbsenceService._counts(absence['absence_type'], start.isoformat(), end.isoformat())['leave_days']))
        kind = 'extended' if absence['absence_type'] == 'extended_leave' else 'basic'
        remaining = days
        eligible = sorted((i for i, lot in enumerate(lots) if lot.kind == kind and lot.accrued_on <= start
                           and balances[i] > 0 and (lot.expires_on is None or lot.expires_on >= start)),
                          key=lambda i: (lots[i].accrued_on, lots[i].expires_on or date.max))
        for index in eligible:
            used = min(remaining, balances[index])
            balances[index] -= used
            remaining -= used
            if used:
                lot = lots[index]
                movements.append({'type': 'consumption', 'date': start.isoformat(), 'kind': kind, 'days': str(used),
                                  'absence_id': absence['id'], 'from_lot_date': lot.accrued_on.isoformat()})
            if remaining == 0:
                break
        excess = remaining
        if excess:
            movements.append({'type': 'consumption', 'date': start.isoformat(), 'kind': kind, 'days': str(excess), 'absence_id': absence['id'], 'unallocated': True})
    for index, lot in enumerate(lots):
        if lot.expires_on and lot.expires_on < as_at and balances[index] > 0:
            movements.append({'type': 'expired', 'date': lot.expires_on.isoformat(), 'kind': lot.kind, 'days': str(balances[index])})
    active = [LeaveLot(balances[index], lot.accrued_on, lot.expires_on, lot.kind)
              for index, lot in enumerate(lots) if balances[index] > 0
              and (lot.expires_on is None or lot.expires_on >= as_at)]
    return active, sorted(movements, key=lambda row: (row['date'], row['type']))


class PayrollLeaveLiabilityService:
    def __init__(self, db=None):
        self.db = db or get_database()

    def settings(self, organisation_id):
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM organisations WHERE id=?', (organisation_id,)):
                raise KeyError('Organisation not found')
            tx.execute('INSERT INTO payroll_leave_settings(organisation_id) VALUES (?) ON CONFLICT DO NOTHING', (organisation_id,))
            return tx.one('SELECT * FROM payroll_leave_settings WHERE organisation_id=?', (organisation_id,))

    def save_settings(self, organisation_id, *, basic_expiry_policy, extended_expiry_policy,
                      reserve_posting_enabled, actor):
        valid = {'none', '1_january_year_plus_2', '31_december_year_plus_1'}
        if basic_expiry_policy not in valid or extended_expiry_policy not in valid or not isinstance(reserve_posting_enabled, bool):
            raise ValueError('Choose valid leave expiry policies and reserve setting')
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM organisations WHERE id=?', (organisation_id,)):
                raise KeyError('Organisation not found')
            tx.execute('INSERT INTO payroll_leave_settings(organisation_id,basic_expiry_policy,extended_expiry_policy,reserve_posting_enabled) VALUES (?,?,?,?) ON CONFLICT(organisation_id) DO UPDATE SET basic_expiry_policy=excluded.basic_expiry_policy,extended_expiry_policy=excluded.extended_expiry_policy,reserve_posting_enabled=excluded.reserve_posting_enabled',
                       (organisation_id, basic_expiry_policy, extended_expiry_policy, int(reserve_posting_enabled)))
            audit(tx, organisation_id, actor, 'payroll.leave_settings.saved', 'organisation', organisation_id)
            return tx.one('SELECT * FROM payroll_leave_settings WHERE organisation_id=?', (organisation_id,))

    def report(self, organisation_id, as_at):
        as_at = date.fromisoformat(as_at) if isinstance(as_at, str) else as_at
        if not isinstance(as_at, date):
            raise ValueError('Choose a valid liability date')
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM organisations WHERE id=?', (organisation_id,)):
                raise KeyError('Organisation not found')
            tx.execute('INSERT INTO payroll_leave_settings(organisation_id) VALUES (?) ON CONFLICT DO NOTHING', (organisation_id,))
            settings = tx.one('SELECT * FROM payroll_leave_settings WHERE organisation_id=?', (organisation_id,))
            employees = tx.rows('SELECT * FROM employees WHERE organisation_id=? ORDER BY name,id', (organisation_id,))
            result, totals = [], {key: Decimal(0) for key in ('remaining_days', 'wage_liability', 'social_tax', 'employer_unemployment', 'total_liability')}
            for employee in employees:
                entitlements = tx.rows('SELECT effective_from,days_per_year FROM payroll_leave_entitlements WHERE organisation_id=? AND employee_id=? AND effective_from<=? ORDER BY effective_from', (organisation_id, employee['id'], as_at.isoformat()))
                openings = tx.rows('SELECT cutover_date,unused_days,extended_unused_days FROM payroll_leave_openings WHERE organisation_id=? AND employee_id=? AND cutover_date<=? AND reviewed_at IS NOT NULL ORDER BY cutover_date', (organisation_id, employee['id'], as_at.isoformat()))
                absences = tx.rows('SELECT id,absence_type,start_date,end_date FROM payroll_absences WHERE organisation_id=? AND employee_id=? AND start_date<=?', (organisation_id, employee['id'], as_at.isoformat()))
                active, movements = _lots(entitlements, openings, absences, settings,
                    employee.get('employment_start_date'), as_at, employee.get('employment_end_date'))
                days = sum((lot.days for lot in active), Decimal(0))
                if not days and not movements:
                    continue
                approved = tx.rows("SELECT i.*,r.period,r.status run_status FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=? AND i.employee_id=? AND r.status='Approved'", (organisation_id, employee['id']))
                for item in approved:
                    item['components'] = tx.rows('SELECT direction,amount,is_wage FROM pay_item_components WHERE organisation_id=? AND item_id=?', (organisation_id, item['id']))
                history = tx.rows("SELECT earning_month period,wage_total,unpaid_absence_days FROM payroll_historical_earnings WHERE organisation_id=? AND employee_id=? AND status='Approved'", (organisation_id, employee['id']))
                absence_for_average = tx.rows('SELECT absence_type,start_date,end_date FROM payroll_absences WHERE organisation_id=? AND employee_id=?', (organisation_id, employee['id']))
                paid_settings = {row['absence_type']: bool(row['paid_salary']) for row in tx.rows(
                    'SELECT absence_type,paid_salary FROM payroll_absence_type_settings WHERE organisation_id=?', (organisation_id,))}
                for absence in absence_for_average:
                    absence['wage_paid'] = (absence['absence_type'] == 'permitted_absence' and paid_settings.get('permitted_absence', False)
                        or absence['absence_type'] not in ('permitted_absence', 'unpaid_leave', 'truancy'))
                average = calculate_average_pay(employee, as_at, approved_items=approved, historical_earnings=history, absences=absence_for_average)
                value = liability_value(days, average.average_daily_pay, as_at)
                row = {'employee_id': employee['id'], 'employee_name': employee['name'], **value, 'movements': movements}
                result.append(row)
                for key in totals:
                    totals[key] += Decimal(value[key]) if key != 'remaining_days' else days
            for key in totals:
                totals[key] = str(money(totals[key])) if key != 'remaining_days' else str(totals[key])
            return {'as_at': as_at.isoformat(), 'employees': result, 'totals': totals}

    def workbook_xlsx(self, organisation_id, as_at):
        from excel_export import leave_liability_workbook
        report = self.report(organisation_id, as_at)
        with self.db.transaction() as tx:
            organisation = tx.one('SELECT * FROM organisations WHERE id=?', (organisation_id,))
        return leave_liability_workbook(organisation, report)

    def post_reserve(self, organisation_id, period, *, actor):
        from calendar import monthrange
        from ledger import LedgerService, PostingLine
        from payroll import PayrollConflict, PayrollService
        if not isinstance(period, str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', period):
            raise ValueError('Payroll periods must use YYYY-MM')
        year, month = int(period[:4]), int(period[5:])
        posting_date = date(year, month, monthrange(year, month)[1])
        report = self.report(organisation_id, posting_date)
        current = Decimal(report['totals']['total_liability'])
        with self.db.transaction() as tx:
            tx.execute('UPDATE payroll_leave_settings SET reserve_posting_enabled=reserve_posting_enabled WHERE organisation_id=?',
                       (organisation_id,))
            existing = tx.one('SELECT * FROM payroll_leave_reserve_posts WHERE organisation_id=? AND period=?',
                              (organisation_id, period))
            if existing:
                raise PayrollConflict('A vacation reserve posting already exists for this month')
            settings = tx.one('SELECT reserve_posting_enabled FROM payroll_leave_settings WHERE organisation_id=?', (organisation_id,))
            if not settings or not settings['reserve_posting_enabled']:
                raise ValueError('Monthly vacation reserve posting is disabled')
            previous = tx.one('SELECT valuation_total FROM payroll_leave_reserve_posts WHERE organisation_id=? AND period<? ORDER BY period DESC LIMIT 1',
                              (organisation_id, period))
            delta = money(current - (Decimal(previous['valuation_total']) if previous else Decimal(0)))
            if not delta:
                raise ValueError('The vacation reserve valuation has not changed')
            payroll = PayrollService(self.db)
            expense = payroll._posting_account(tx, organisation_id, 'PAYROLL_VACATION_RESERVE_EXPENSE')
            liability = payroll._posting_account(tx, organisation_id, 'PAYROLL_VACATION_RESERVE_LIABILITY')
            amount = abs(delta)
            lines = [PostingLine(account_id=expense['id'], debit=amount if delta > 0 else Decimal(0),
                                 credit=amount if delta < 0 else Decimal(0), memo='Vacation reserve valuation change'),
                     PostingLine(account_id=liability['id'], debit=amount if delta < 0 else Decimal(0),
                                 credit=amount if delta > 0 else Decimal(0), memo='Vacation reserve valuation change')]
            batch = LedgerService(self.db).post(organisation_id=organisation_id, voucher_type='payroll_vacation_reserve',
                voucher_id=f'{organisation_id}:{period}', voucher_code='VR-' + period.replace('-', ''),
                posting_date=posting_date.isoformat(), lines=lines, actor=actor, currency='EUR', tx=tx)
            tx.execute('INSERT INTO payroll_leave_reserve_posts(organisation_id,period,posting_batch_id,valuation_total,created_by,created_at) VALUES (?,?,?,?,?,?)',
                       (organisation_id, period, batch['id'], str(current), actor, utc_now()))
            audit(tx, organisation_id, actor, 'payroll.leave_reserve.posted', 'posting_batch', batch['id'],
                  {'period': period, 'delta': str(delta), 'valuation_total': str(current)})
            return {'period': period, 'posting_batch_id': batch['id'], 'delta': str(delta), 'valuation_total': str(current)}

    def reverse_reserve(self, organisation_id, period, *, reversal_date, actor, reason=''):
        from ledger import LedgerService
        with self.db.transaction() as tx:
            row = tx.one('SELECT posting_batch_id FROM payroll_leave_reserve_posts WHERE organisation_id=? AND period=?',
                         (organisation_id, period))
            if not row:
                raise KeyError('Vacation reserve posting not found')
            batch = tx.one('SELECT id FROM posting_batches WHERE organisation_id=? AND id=?',
                           (organisation_id, row['posting_batch_id']))
            if not batch:
                raise KeyError('Vacation reserve posting not found')
            reversal = LedgerService(self.db).reverse(row['posting_batch_id'], reversal_date=reversal_date,
                                                       actor=actor, reason=reason, tx=tx)
            audit(tx, organisation_id, actor, 'payroll.leave_reserve.reversed', 'posting_batch', row['posting_batch_id'],
                  {'reversal_batch_id': reversal['id'], 'period': period})
            return reversal
