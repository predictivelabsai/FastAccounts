"""Tenant-scoped absence register and payroll calendar day counts."""
from datetime import date, timedelta

from core_utils import audit, new_id, utc_now
from payroll_calendar import is_working_day, public_holidays, working_days as norm_working_days
from payroll_absence_pay import VACATION_PAY_METHODS, vacation_pay, vacation_payout_date
from payroll_average import calculate_average_pay
from payroll_calendar import working_days as norm_month_working_days
import json

ABSENCE_TYPES = (
    'annual_leave', 'extended_leave', 'child_leave', 'paternity_leave',
    'maternity_leave', 'parental_leave', 'study_leave', 'care_leave',
    'sick_leave', 'permitted_absence', 'truancy', 'unpaid_leave',
    'alternative_service', 'other',
)
ANNUAL_TYPES = {'annual_leave', 'extended_leave'}


class AbsenceConflict(ValueError):
    """An absence overlaps another absence or has entered approved payroll."""


class PayrollAbsenceService:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def _days(kind, start, end):
        days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
        calendar_days = len(days)
        holidays = {day for year in range(start.year, end.year + 1) for day in public_holidays(year)}
        leave_days = sum(day not in holidays for day in days) if kind in ANNUAL_TYPES else calendar_days
        working = sum(is_working_day(day) for day in days)
        return calendar_days, leave_days, working

    def types(self, organisation_id):
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM organisations WHERE id=?', (organisation_id,)):
                raise KeyError('Organisation not found')
            for kind in ABSENCE_TYPES:
                tx.execute('INSERT INTO payroll_absence_type_settings(organisation_id,absence_type,paid_salary) VALUES (?,?,0) ON CONFLICT(organisation_id,absence_type) DO NOTHING',
                           (organisation_id, kind))
            rows = tx.rows('SELECT absence_type,paid_salary FROM payroll_absence_type_settings WHERE organisation_id=? ORDER BY absence_type', (organisation_id,))
            for row in rows:
                row['paid_salary'] = bool(row['paid_salary'])
            return rows

    def set_type_paid(self, organisation_id, kind, paid, *, actor):
        if kind != 'permitted_absence' or not isinstance(paid, bool):
            raise ValueError('Choose a valid absence type and paid setting')
        with self.db.transaction() as tx:
            if not tx.one('SELECT id FROM organisations WHERE id=?', (organisation_id,)):
                raise KeyError('Organisation not found')
            tx.execute('INSERT INTO payroll_absence_type_settings(organisation_id,absence_type,paid_salary) VALUES (?,?,?) ON CONFLICT(organisation_id,absence_type) DO UPDATE SET paid_salary=excluded.paid_salary',
                       (organisation_id, kind, int(paid)))
            audit(tx, organisation_id, actor, 'payroll.absence_type.updated', 'payroll_absence_type', kind, {'paid_salary': paid})
            return {'absence_type': kind, 'paid_salary': paid}

    def freeze_for_run(self, tx, organisation_id, employee_id, run_id, period):
        """Snapshot absences intersecting the run month and return day totals."""
        year, month = (int(part) for part in period.split('-'))
        first, last = date(year, month, 1), date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        rows = tx.rows('SELECT a.* FROM payroll_absences a WHERE a.organisation_id=? AND a.employee_id=? AND a.start_date<=? AND a.end_date>=? ORDER BY a.start_date,a.id',
                       (organisation_id, employee_id, last.isoformat(), first.isoformat()))
        settings = {row['absence_type']: bool(row['paid_salary']) for row in tx.rows(
            'SELECT absence_type,paid_salary FROM payroll_absence_type_settings WHERE organisation_id=?', (organisation_id,))}
        interrupted = 0
        snapshots = []
        for absence in rows:
            start = max(first, date.fromisoformat(absence['start_date']))
            end = min(last, date.fromisoformat(absence['end_date']))
            counts = self._counts(absence['absence_type'], start.isoformat(), end.isoformat())
            interrupts = absence['absence_type'] != 'permitted_absence' or not settings.get('permitted_absence', False)
            if interrupts:
                interrupted += counts['working_days']
            snapshot_id = new_id()
            tx.execute('INSERT INTO payroll_absence_run_items(id,organisation_id,pay_run_id,employee_id,absence_id,calendar_days,leave_days,working_days,interrupts_salary) VALUES (?,?,?,?,?,?,?,?,?)',
                       (snapshot_id, organisation_id, run_id, employee_id, absence['id'], counts['calendar_days'], counts['leave_days'], counts['working_days'], int(interrupts)))
            snapshots.append(absence | counts | {'interrupts_salary': interrupts})
        norm = norm_working_days(year, month)
        absent = min(interrupted, norm)
        return {'norm_days': norm, 'absence_working_days': absent,
                'worked_days': norm - absent, 'absences': snapshots}

    def list(self, organisation_id, *, month=None, kind=None):
        query = ('SELECT a.*,e.name AS employee_name FROM payroll_absences a '
                 'JOIN employees e ON e.organisation_id=a.organisation_id AND e.id=a.employee_id '
                 'WHERE a.organisation_id=?')
        params = [organisation_id]
        if month:
            try:
                year, number = (int(part) for part in month.split('-'))
                first = date(year, number, 1)
                last = date(year + (number == 12), number % 12 + 1, 1) - timedelta(days=1)
            except (ValueError, AttributeError):
                raise ValueError('Month must use YYYY-MM') from None
            query += ' AND a.start_date<=? AND a.end_date>=?'
            params.extend((last.isoformat(), first.isoformat()))
        if kind:
            if kind not in ABSENCE_TYPES:
                raise ValueError('Choose a valid absence type')
            query += ' AND a.absence_type=?'
            params.append(kind)
        query += ' ORDER BY a.start_date DESC,e.name,a.id'
        rows = self.db.rows(query, params)
        for row in rows:
            row.update(self._counts(row['absence_type'], row['start_date'], row['end_date']))
            row['frozen'] = self.db.scalar('SELECT 1 FROM payroll_absence_run_items x JOIN pay_runs r ON r.organisation_id=x.organisation_id AND r.id=x.pay_run_id WHERE x.organisation_id=? AND x.absence_id=? AND r.status=\'Approved\' LIMIT 1', (organisation_id, row['id'])) is not None
            row['absence_pay'] = self.db.one('SELECT * FROM payroll_absence_pay WHERE organisation_id=? AND absence_id=?',
                                             (organisation_id, row['id']))
            if row['absence_pay']:
                row['absence_pay']['breakdown'] = json.loads(row['absence_pay'].pop('breakdown_json'))
        return rows

    def set_pay_method(self, organisation_id, absence_id, method, *, actor, fixed_amount=None):
        """Create or refresh the pending vacation-pay snapshot for an absence."""
        from core_utils import db_number, decimal, money
        from datetime import date
        if method not in VACATION_PAY_METHODS:
            raise ValueError('Choose a valid vacation pay method')
        if method == 'fixed_sum' and fixed_amount is None:
            raise ValueError('A fixed amount is required for the fixed-sum method')
        if method != 'fixed_sum' and fixed_amount is not None:
            raise ValueError('A fixed amount is only valid for the fixed-sum method')
        with self.db.transaction() as tx:
            absence = tx.one('SELECT a.*,e.name AS employee_name,e.pay_basis,e.gross_salary,e.hourly_rate '
                             'FROM payroll_absences a JOIN employees e '
                             'ON e.organisation_id=a.organisation_id AND e.id=a.employee_id '
                             'WHERE a.organisation_id=? AND a.id=?', (organisation_id, absence_id))
            if not absence:
                raise KeyError('Absence not found')
            if absence['absence_type'] not in ANNUAL_TYPES:
                raise ValueError('Vacation pay applies to annual and extended leave')
            existing = tx.one('SELECT * FROM payroll_absence_pay WHERE organisation_id=? AND absence_id=?',
                              (organisation_id, absence_id))
            if existing and existing['status'] != 'pending':
                raise AbsenceConflict('Absence pay is frozen once added to a payout')
            leave_start, leave_end = date.fromisoformat(absence['start_date']), date.fromisoformat(absence['end_date'])
            run_rows = tx.rows("SELECT i.*,r.period,r.status FROM pay_run_items i JOIN pay_runs r "
                               "ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id "
                               "WHERE i.organisation_id=? AND i.employee_id=? AND r.status='Approved'",
                               (organisation_id, absence['employee_id']))
            for item in run_rows:
                item['components'] = tx.rows('SELECT direction,amount,is_wage FROM pay_item_components '
                                             'WHERE organisation_id=? AND item_id=?',
                                             (organisation_id, item['id']))
            history = tx.rows("SELECT earning_month AS period,wage_total FROM payroll_historical_earnings "
                              "WHERE organisation_id=? AND employee_id=? AND status='Approved'",
                              (organisation_id, absence['employee_id']))
            absence_history = tx.rows('SELECT absence_type,start_date,end_date FROM payroll_absences '
                                      'WHERE organisation_id=? AND employee_id=? AND id<>?',
                                      (organisation_id, absence['employee_id'], absence_id))
            for prior in absence_history:
                prior['wage_paid'] = (prior['absence_type'] == 'permitted_absence' and bool(tx.scalar(
                    'SELECT paid_salary FROM payroll_absence_type_settings WHERE organisation_id=? AND absence_type=?',
                    (organisation_id, 'permitted_absence'))) or prior['absence_type'] not in
                    ('permitted_absence', 'unpaid_leave', 'truancy'))
            avg = calculate_average_pay(absence, leave_start, approved_items=run_rows,
                                        historical_earnings=history, absences=absence_history)
            leave_days = self._counts(absence['absence_type'], absence['start_date'], absence['end_date'])['leave_days']
            work_days = sum(is_working_day(leave_start + timedelta(days=n))
                            for n in range((leave_end - leave_start).days + 1))
            period = leave_start.strftime('%Y-%m')
            norm = norm_month_working_days(leave_start.year, leave_start.month)
            breakdown = vacation_pay(method, average_daily_pay=avg.average_daily_pay,
                                     leave_days=leave_days, monthly_salary=absence.get('gross_salary'),
                                     leave_working_days=work_days, norm_working_days=norm,
                                     fixed_sum=fixed_amount)
            breakdown['average'] = avg.as_dict()
            payout_date = vacation_payout_date(leave_start).isoformat()
            record_id = existing['id'] if existing else new_id()
            now = utc_now()
            tx.execute('INSERT INTO payroll_absence_pay(id,organisation_id,absence_id,employee_id,method,fixed_amount,gross,breakdown_json,status,payout_batch_id,payment_date,payment_month,created_at,updated_at) '
                       'VALUES (?,?,?,?,?,?,?,? ,\'pending\',NULL,?,?,?,?) ON CONFLICT(organisation_id,absence_id) '
                       'DO UPDATE SET method=excluded.method,fixed_amount=excluded.fixed_amount,gross=excluded.gross,'
                       'breakdown_json=excluded.breakdown_json,payment_date=excluded.payment_date,'
                       'payment_month=excluded.payment_month,updated_at=excluded.updated_at '
                       'WHERE payroll_absence_pay.status=\'pending\'',
                       (record_id, organisation_id, absence_id, absence['employee_id'], method,
                        None if fixed_amount is None else db_number(money(fixed_amount)), breakdown['amount'],
                        json.dumps(breakdown, sort_keys=True), payout_date, period, now, now))
            audit(tx, organisation_id, actor, 'payroll.absence_pay.calculated', 'payroll_absence_pay', record_id,
                  {'absence_id': absence_id, 'method': method, 'gross': breakdown['amount']})
            result = tx.one('SELECT * FROM payroll_absence_pay WHERE organisation_id=? AND id=?',
                            (organisation_id, record_id))
            result['gross'] = db_number(money(result['gross']))
            result['fixed_amount'] = (None if result['fixed_amount'] is None
                                      else db_number(money(result['fixed_amount'])))
            return result | {'breakdown': breakdown}

    @classmethod
    def _counts(cls, kind, start_date, end_date):
        start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        calendar, leave, working = cls._days(kind, start, end)
        return {'calendar_days': calendar, 'leave_days': leave, 'working_days': working}

    @staticmethod
    def _validate(kind, start_date, end_date, document_reference, comment):
        if kind not in ABSENCE_TYPES:
            raise ValueError('Choose a valid absence type')
        try:
            start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
            if start.isoformat() != start_date or end.isoformat() != end_date or end < start:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError('Absence dates must be valid YYYY-MM-DD dates in order') from None
        if not isinstance(document_reference, str) or len(document_reference) > 180:
            raise ValueError('Document reference must be at most 180 characters')
        if not isinstance(comment, str) or len(comment) > 2000:
            raise ValueError('Comment must be at most 2000 characters')

    def save(self, organisation_id, employee_id, *, actor, absence_type, start_date,
             end_date, document_reference='', comment='', absence_id=None):
        self._validate(absence_type, start_date, end_date, document_reference, comment)
        with self.db.transaction() as tx:
            employee = tx.one('SELECT id FROM employees WHERE organisation_id=? AND id=?', (organisation_id, employee_id))
            if not employee:
                raise KeyError('Employee not found')
            if tx.dialect == 'postgres':
                tx.one('SELECT id FROM employees WHERE organisation_id=? AND id=? FOR UPDATE', (organisation_id, employee_id))
            old = tx.one('SELECT * FROM payroll_absences WHERE organisation_id=? AND id=?', (organisation_id, absence_id)) if absence_id else None
            if absence_id and not old:
                raise KeyError('Absence not found')
            if old and self._frozen(tx, organisation_id, absence_id):
                raise AbsenceConflict('Absences frozen in an approved payroll run cannot be edited')
            overlap = tx.one('SELECT id FROM payroll_absences WHERE organisation_id=? AND employee_id=? AND start_date<=? AND end_date>=? AND id<>?',
                             (organisation_id, employee_id, end_date, start_date, absence_id or ''))
            if overlap:
                raise AbsenceConflict('Absence dates overlap an existing absence for this employee')
            absence_id = absence_id or new_id()
            now = utc_now()
            if old:
                tx.execute('UPDATE payroll_absences SET employee_id=?,absence_type=?,start_date=?,end_date=?,document_reference=?,comment=?,updated_at=? WHERE organisation_id=? AND id=?',
                           (employee_id, absence_type, start_date, end_date, document_reference.strip(), comment.strip(), now, organisation_id, absence_id))
                action = 'payroll.absence.updated'
            else:
                tx.execute('INSERT INTO payroll_absences(id,organisation_id,employee_id,absence_type,start_date,end_date,document_reference,comment,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (absence_id, organisation_id, employee_id, absence_type, start_date, end_date, document_reference.strip(), comment.strip(), now, now))
                action = 'payroll.absence.created'
            audit(tx, organisation_id, actor, action, 'payroll_absence', absence_id,
                  {'employee_id': employee_id, 'absence_type': absence_type, 'start_date': start_date, 'end_date': end_date})
        return next(row for row in self.list(organisation_id) if row['id'] == absence_id)

    def collective_annual_leave(self, organisation_id, employee_ids, *, actor, start_date,
                                end_date, document_reference='', comment=''):
        if not employee_ids or len(set(employee_ids)) != len(employee_ids):
            raise ValueError('Select one or more distinct employees')
        self._validate('annual_leave', start_date, end_date, document_reference, comment)
        results = []
        with self.db.transaction() as tx:
            for employee_id in employee_ids:
                if not tx.one('SELECT id FROM employees WHERE organisation_id=? AND id=? AND active=1', (organisation_id, employee_id)):
                    raise KeyError('Employee not found or inactive')
                if tx.one('SELECT id FROM payroll_absences WHERE organisation_id=? AND employee_id=? AND start_date<=? AND end_date>=?',
                          (organisation_id, employee_id, end_date, start_date)):
                    raise AbsenceConflict('Collective leave overlaps an existing absence')
            now = utc_now()
            for employee_id in employee_ids:
                absence_id = new_id()
                tx.execute('INSERT INTO payroll_absences(id,organisation_id,employee_id,absence_type,start_date,end_date,document_reference,comment,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (absence_id, organisation_id, employee_id, 'annual_leave', start_date, end_date, document_reference.strip(), comment.strip(), now, now))
                audit(tx, organisation_id, actor, 'payroll.absence.created', 'payroll_absence', absence_id,
                      {'employee_id': employee_id, 'absence_type': 'annual_leave', 'collective': True})
                results.append(absence_id)
        return [row for row in self.list(organisation_id) if row['id'] in results]

    def delete(self, organisation_id, absence_id, *, actor):
        with self.db.transaction() as tx:
            absence = tx.one('SELECT id FROM payroll_absences WHERE organisation_id=? AND id=?', (organisation_id, absence_id))
            if not absence:
                raise KeyError('Absence not found')
            if self._frozen(tx, organisation_id, absence_id):
                raise AbsenceConflict('Absences frozen in an approved payroll run cannot be deleted')
            tx.execute('DELETE FROM payroll_absences WHERE organisation_id=? AND id=?', (organisation_id, absence_id))
            audit(tx, organisation_id, actor, 'payroll.absence.deleted', 'payroll_absence', absence_id)
            return True

    @staticmethod
    def _frozen(tx, organisation_id, absence_id):
        return bool(tx.one('SELECT 1 FROM payroll_absence_run_items x JOIN pay_runs r ON r.organisation_id=x.organisation_id AND r.id=x.pay_run_id WHERE x.organisation_id=? AND x.absence_id=? AND r.status=\'Approved\' LIMIT 1', (organisation_id, absence_id)))
