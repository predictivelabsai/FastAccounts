"""Tenant-scoped quote persistence, using the current workflow transaction."""
from core_utils import db_number, new_id, utc_now


class QuoteRepository:
    def __init__(self, tx, organisation_id):
        self.tx, self.oid = tx, organisation_id

    def lock_organisation(self):
        # Serialise numbering, transitions and conversion on SQLite and PostgreSQL.
        if self.tx.execute('UPDATE organisations SET name=name WHERE id=?', (self.oid,)).rowcount != 1:
            raise KeyError('Organisation not found')
        return self.tx.one('SELECT * FROM organisations WHERE id=?', (self.oid,))

    def get(self, quote_id):
        row = self.tx.one(
            'SELECT q.*,c.name contact_name FROM quotes q JOIN contacts c '
            'ON c.organisation_id=q.organisation_id AND c.id=q.contact_id '
            'WHERE q.organisation_id=? AND q.id=?', (self.oid, quote_id))
        if not row:
            raise KeyError('Quote not found')
        row['lines'] = self.tx.rows(
            'SELECT * FROM quote_lines WHERE organisation_id=? AND quote_id=? ORDER BY line_number',
            (self.oid, quote_id))
        return row

    def list(self):
        return self.tx.rows(
            'SELECT q.*,c.name contact_name FROM quotes q JOIN contacts c '
            'ON c.organisation_id=q.organisation_id AND c.id=q.contact_id '
            'WHERE q.organisation_id=? ORDER BY q.quote_date DESC,q.created_at DESC,q.quote_number DESC',
            (self.oid,))

    def customer(self, contact_id):
        return self.tx.one('SELECT contact_type FROM contacts WHERE organisation_id=? AND id=?',
                           (self.oid, contact_id))

    def save(self, quote_id, data, lines, *, number=None, actor=None):
        now = utc_now()
        values = (data['contact_id'], data['currency'], data['quote_date'], data['valid_until'],
                  data['notes'], data['amount_type'], db_number(data['subtotal']),
                  db_number(data['tax_total']), db_number(data['total']), now)
        if number is not None:
            self.tx.execute(
                'INSERT INTO quotes(contact_id,currency,quote_date,valid_until,notes,line_amount_type,'
                'subtotal,tax_total,total,updated_at,id,organisation_id,quote_number,created_by,created_at) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (*values, quote_id, self.oid, number, actor, now))
        else:
            self.tx.execute(
                'UPDATE quotes SET contact_id=?,currency=?,quote_date=?,valid_until=?,notes=?,line_amount_type=?,'
                'subtotal=?,tax_total=?,total=?,updated_at=? WHERE id=? AND organisation_id=?',
                (*values, quote_id, self.oid))
            self.tx.execute('DELETE FROM quote_lines WHERE organisation_id=? AND quote_id=?', (self.oid, quote_id))
        for line in lines:
            self.tx.execute(
                'INSERT INTO quote_lines(id,organisation_id,quote_id,line_number,description,quantity,unit_price,'
                'account_id,tax_code_id,net_amount,tax_amount,gross_amount) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (new_id(), self.oid, quote_id, line['line_number'], line['description'],
                 db_number(line['quantity']), db_number(line['unit_price']), line['account_id'],
                 line['tax_code_id'], db_number(line['net_amount']), db_number(line['tax_amount']), db_number(line['gross_amount'])))

    def transition(self, quote_id, status, *, actor=None, invoice_id=None):
        now = utc_now()
        if status == 'Accepted':
            self.tx.execute('UPDATE quotes SET status=?,accepted_at=?,accepted_by=?,updated_at=? WHERE organisation_id=? AND id=?',
                            (status, now, actor, now, self.oid, quote_id))
        elif status == 'Converted':
            self.tx.execute('UPDATE quotes SET status=?,converted_invoice_id=?,updated_at=? WHERE organisation_id=? AND id=?',
                            (status, invoice_id, now, self.oid, quote_id))
        else:
            self.tx.execute('UPDATE quotes SET status=?,updated_at=? WHERE organisation_id=? AND id=?',
                            (status, now, self.oid, quote_id))

    def due(self, day):
        return self.tx.rows("SELECT id FROM quotes WHERE organisation_id=? AND status IN ('Draft','Sent') AND valid_until<? ORDER BY id",
                            (self.oid, day))
