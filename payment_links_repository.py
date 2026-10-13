"""Tenant-scoped local payment configuration and link persistence."""
from core_utils import new_id, utc_now


class PaymentLinkRepository:
    def __init__(self, tx, organisation_id):
        self.tx, self.oid = tx, organisation_id

    def lock_organisation(self):
        if self.tx.execute('UPDATE organisations SET name=name WHERE id=?', (self.oid,)).rowcount != 1:
            raise KeyError('Organisation not found')

    def configs(self):
        return self.tx.rows('SELECT * FROM payment_link_configs WHERE organisation_id=? ORDER BY name,id', (self.oid,))

    def config(self, method_id):
        row = self.tx.one('SELECT * FROM payment_link_configs WHERE organisation_id=? AND id=?', (self.oid, method_id))
        if not row:
            raise KeyError('Payment method not found')
        return row

    def save_config(self, method_id, data, existing=False):
        now = utc_now()
        values = (data['provider'], data['name'], int(data['enabled']), data['url_template'], data['currency'])
        if existing:
            self.tx.execute('UPDATE payment_link_configs SET provider=?,name=?,enabled=?,url_template=?,currency=?,updated_at=? '
                            'WHERE organisation_id=? AND id=?', values + (now, self.oid, method_id))
        else:
            self.tx.execute('INSERT INTO payment_link_configs(provider,name,enabled,url_template,currency,created_at,updated_at,organisation_id,id) '
                            'VALUES (?,?,?,?,?,?,?,?,?)', values + (now, now, self.oid, method_id))
        return self.config(method_id)

    def invoice(self, invoice_id):
        row = self.tx.one('SELECT * FROM invoices WHERE organisation_id=? AND id=?', (self.oid, invoice_id))
        if not row:
            raise KeyError('Invoice not found')
        return row

    def link(self, invoice_id, method_id):
        return self.tx.one('SELECT * FROM invoice_payment_links WHERE organisation_id=? AND invoice_id=? AND method_id=?',
                           (self.oid, invoice_id, method_id))

    def save_link(self, invoice_id, method_id, token, url, existing):
        now = utc_now()
        if existing:
            if existing['url'] != url:
                self.tx.execute('UPDATE invoice_payment_links SET url=?,updated_at=? WHERE organisation_id=? AND id=?',
                                (url, now, self.oid, existing['id']))
        else:
            self.tx.execute('INSERT INTO invoice_payment_links(id,organisation_id,invoice_id,method_id,token,url,created_at,updated_at) '
                            'VALUES (?,?,?,?,?,?,?,?)', (new_id(), self.oid, invoice_id, method_id, token, url, now, now))
        return self.link(invoice_id, method_id)
