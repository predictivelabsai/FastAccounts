"""Tenant-scoped purchase schedules in the caller's accounting transaction."""
from core_utils import db_number, new_id, utc_now
from objects_repository import ObjectRepository


class PeriodisationRepository:
    def __init__(self, tx, organisation_id):
        self.tx, self.oid = tx, organisation_id

    def lock_organisation(self):
        if self.tx.execute('UPDATE organisations SET name=name WHERE id=?', (self.oid,)).rowcount != 1:
            raise KeyError('Organisation not found')
        return self.tx.one('SELECT * FROM organisations WHERE id=?', (self.oid,))

    def bill(self, bill_id):
        row = self.tx.one('SELECT * FROM bills WHERE organisation_id=? AND id=?', (self.oid, bill_id))
        if not row:
            raise KeyError('Bill not found')
        row['lines'] = self.tx.rows(
            'SELECT l.*,a.account_type FROM bill_lines l JOIN bills b ON b.id=l.bill_id '
            'JOIN accounts a ON a.id=l.account_id AND a.organisation_id=b.organisation_id '
            'WHERE b.organisation_id=? AND b.id=? ORDER BY l.line_number', (self.oid, bill_id))
        tags = {l['id']: l for l in ObjectRepository(self.tx, self.oid).document_lines('bill', bill_id)}
        row['lines'] = [tags[l['id']] | {'account_type': l['account_type']} for l in row['lines']]
        return row

    def account(self, account_id):
        return self.tx.one('SELECT * FROM accounts WHERE organisation_id=? AND id=? AND active=1',
                           (self.oid, account_id))

    def deferred_account(self):
        return self.tx.one("SELECT * FROM accounts WHERE organisation_id=? AND system_role='PERIODISED_PURCHASES' AND active=1",
                           (self.oid,))

    def batch(self, batch_id):
        return self.tx.one('SELECT * FROM posting_batches WHERE organisation_id=? AND id=?', (self.oid, batch_id))

    def for_bill(self, bill_id):
        return self.tx.one('SELECT * FROM purchase_schedules WHERE organisation_id=? AND bill_id=?', (self.oid, bill_id))

    def get(self, schedule_id):
        row = self.tx.one(
            'SELECT s.*,b.supplier_number,c.name contact_name FROM purchase_schedules s '
            'JOIN bills b ON b.organisation_id=s.organisation_id AND b.id=s.bill_id '
            'JOIN contacts c ON c.organisation_id=b.organisation_id AND c.id=b.contact_id '
            'WHERE s.organisation_id=? AND s.id=?', (self.oid, schedule_id))
        if not row:
            raise KeyError('Purchase schedule not found')
        row['periods'] = self.tx.rows(
            'SELECT * FROM purchase_schedule_periods WHERE organisation_id=? AND schedule_id=? ORDER BY period_date',
            (self.oid, schedule_id))
        return row

    def ids(self, status=None):
        return self.tx.rows('SELECT id FROM purchase_schedules WHERE organisation_id=?' +
                            (' AND status=?' if status else '') + ' ORDER BY start_period,id',
                            (self.oid, status) if status else (self.oid,))

    def save(self, schedule_id, data, portions, actor):
        now = utc_now()
        self.tx.execute(
            'INSERT INTO purchase_schedules(id,organisation_id,bill_id,expense_account_id,deferred_account_id,'
            'start_period,number_of_periods,split_rule,net_amount,currency,status,notes,created_by,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (schedule_id, self.oid, data['bill_id'], data['expense_account_id'], data['deferred_account_id'],
             data['start_period'], len(portions), data['split_rule'], db_number(data['net_amount']),
             data['currency'], data['status'], data['notes'], actor, now, now))
        for day, amount in portions:
            self.tx.execute(
                'INSERT INTO purchase_schedule_periods(id,organisation_id,schedule_id,period_date,net_amount) VALUES (?,?,?,?,?)',
                (new_id(), self.oid, schedule_id, day, db_number(amount)))

    def funding(self, schedule_id, batch_id):
        self.tx.execute('UPDATE purchase_schedules SET funding_batch_id=?,updated_at=? WHERE organisation_id=? AND id=?',
                        (batch_id, utc_now(), self.oid, schedule_id))

    def funding_entries(self, schedule):
        return self.tx.rows(
            'SELECT g.debit,g.credit,d.projects_project_id,d.projects_location_id,'
            'd.projects_person_id,d.projects_object_id FROM gl_entries g '
            'LEFT JOIN gl_entry_objects d ON d.organisation_id=g.organisation_id AND d.line_id=g.id '
            'WHERE g.organisation_id=? AND g.posting_batch_id=? AND g.account_id=?',
            (self.oid, schedule['funding_batch_id'], schedule['deferred_account_id']))

    def transition(self, schedule_id, status, notes):
        self.tx.execute('UPDATE purchase_schedules SET status=?,notes=?,updated_at=? WHERE organisation_id=? AND id=?',
                        (status, notes, utc_now(), self.oid, schedule_id))

    def posted(self, schedule_id, period_id, batch_id):
        changed = self.tx.execute(
            "UPDATE purchase_schedule_periods SET status='Posted',posted_journal_id=? "
            "WHERE organisation_id=? AND schedule_id=? AND id=? AND status='Pending' AND posted_journal_id IS NULL",
            (batch_id, self.oid, schedule_id, period_id))
        if changed.rowcount != 1:
            raise ValueError('Purchase period is no longer pending')

    def cancel_future(self, schedule_id, day):
        self.tx.execute("UPDATE purchase_schedule_periods SET status='Cancelled' "
                        "WHERE organisation_id=? AND schedule_id=? AND status='Pending' AND period_date>?",
                        (self.oid, schedule_id, day))
