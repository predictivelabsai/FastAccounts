"""Tenant-scoped FX run identity, open documents and immutable audit results."""
import json

from core_utils import utc_now


class FxRevaluationRepository:
    def __init__(self, tx, organisation_id):
        self.tx, self.oid = tx, organisation_id

    def lock(self):
        if self.tx.execute('UPDATE organisations SET name=name WHERE id=?', (self.oid,)).rowcount != 1:
            raise KeyError('Organisation not found')

    def existing(self, day):
        return self.tx.one('SELECT id FROM fx_revaluations WHERE organisation_id=? AND revaluation_date=?',
                           (self.oid, day))

    def base_currency(self):
        return self.tx.scalar('SELECT base_currency FROM organisations WHERE id=?', (self.oid,))

    def accounts(self):
        return {r['system_role']: r['id'] for r in self.tx.rows(
            'SELECT id,system_role FROM accounts WHERE organisation_id=? AND active=1', (self.oid,))}

    def documents(self, base):
        rows = []
        for table, kind, statuses, role in (
            ('invoices', 'invoice', ('Issued', 'Part Paid'), 'AR'),
            ('bills', 'bill', ('Approved', 'Part Paid'), 'AP')):
            for row in self.tx.rows(
                f'SELECT * FROM {table} WHERE organisation_id=? AND document_type=? '
                'AND status IN (?,?) AND currency<>? AND total>paid_total ORDER BY id',
                (self.oid, kind, *statuses, base)):
                rows.append(dict(row, control_role=role))
        for row in self.tx.rows('SELECT * FROM prepayments WHERE organisation_id=? AND currency<>? '
                                'AND unallocated_balance>0 ORDER BY id', (self.oid, base)):
            rows.append(dict(row, document_type='prepayment',
                             control_role='CUSTOMER_PREPAYMENTS' if row['side'] == 'customer' else 'SUPPLIER_PREPAYMENTS'))
        return rows

    def create(self, run_id, day, batch_id, actor):
        self.tx.execute('INSERT INTO fx_revaluations(id,organisation_id,revaluation_date,posting_batch_id,'
                        'status,created_by,created_at) VALUES (?,?,?,?,?,?,?)',
                        (run_id, self.oid, day, batch_id, 'Posted' if batch_id else 'Empty', actor, utc_now()))
        return self.tx.one('SELECT * FROM fx_revaluations WHERE organisation_id=? AND id=?', (self.oid, run_id))

    def list(self):
        rows = self.tx.rows(
            'SELECT r.*,a.details_json FROM fx_revaluations r JOIN audit_events a '
            'ON a.organisation_id=r.organisation_id AND a.object_id=r.id '
            "AND a.action='fx_revaluation.posted' WHERE r.organisation_id=? "
            'ORDER BY r.revaluation_date DESC,r.id', (self.oid,))
        for row in rows:
            row.update(json.loads(row.pop('details_json')))
        return rows
