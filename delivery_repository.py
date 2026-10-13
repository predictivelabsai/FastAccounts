"""Existing invoice delivery and audit records, scoped to the book."""
import json

from core_utils import audit, new_id, utc_now


class DeliveryRepository:
    def __init__(self, tx, organisation_id):
        self.tx, self.oid = tx, organisation_id

    def lock(self):
        if self.tx.execute('UPDATE organisations SET name=name WHERE id=?', (self.oid,)).rowcount != 1:
            raise KeyError('Organisation not found')

    def history(self, invoice_id):
        rows = self.tx.rows(
            'SELECT * FROM invoice_deliveries WHERE organisation_id=? AND invoice_id=? ORDER BY created_at,id',
            (self.oid, invoice_id))
        events = self.tx.rows(
            "SELECT object_id,details_json FROM audit_events WHERE organisation_id=? "
            "AND action='invoice.delivery' ORDER BY created_at,id", (self.oid,))
        details = {row['object_id']: json.loads(row['details_json']) for row in events}
        return [row | {'attachment_id': details.get(row['id'], {}).get('attachment_id'),
                       'request_key': details.get(row['id'], {}).get('request_key')}
                for row in rows]

    def reserve(self, invoice, recipient, actor, attachment_id, request_key):
        delivery_id, now = new_id(), utc_now()
        self.tx.execute(
            'INSERT INTO invoice_deliveries(id,organisation_id,invoice_id,channel,recipient,status,provider,created_by,created_at) '
            'VALUES (?,?,?,?,?,?,?,?,?)',
            (delivery_id, self.oid, invoice['id'], 'email', recipient, 'Prepared', 'postmark', actor, now))
        self.event(delivery_id, invoice['id'], actor, 'Prepared', recipient, attachment_id, request_key)
        return delivery_id

    def event(self, delivery_id, invoice_id, actor, status, recipient, attachment_id, request_key):
        audit(self.tx, self.oid, actor, 'invoice.delivery', 'invoice_delivery', delivery_id,
              dict(invoice_id=invoice_id, status=status, recipient=recipient,
                   attachment_id=attachment_id, request_key=request_key))

    def finish(self, delivery_id, invoice_id, actor, status, recipient, attachment_id, request_key, provider_id, error):
        self.tx.execute(
            'UPDATE invoice_deliveries SET status=?,provider_message_id=?,error_message=? WHERE organisation_id=? AND id=?',
            (status, provider_id, error, self.oid, delivery_id))
        self.event(delivery_id, invoice_id, actor, status, recipient, attachment_id, request_key)
