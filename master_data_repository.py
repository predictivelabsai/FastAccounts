"""Tenant-scoped persistence shared by staged master-data imports."""
from core_utils import canonical_json, new_id, utc_now


class ImportRepository:
    def __init__(self, tx, organisation_id):
        self.tx, self.oid = tx, organisation_id

    def lock_organisation(self):
        # A write lock also serialises different batches with overlapping natural keys.
        if self.tx.execute('UPDATE organisations SET name=name WHERE id=?', (self.oid,)).rowcount != 1:
            raise KeyError('Organisation not found')
        return self.tx.one('SELECT * FROM organisations WHERE id=?', (self.oid,))

    def batch(self, batch_id):
        result = self.tx.one('SELECT * FROM import_batches WHERE organisation_id=? AND id=?', (self.oid, batch_id))
        if not result:
            raise KeyError('Import batch not found')
        return result

    def rows(self, batch_id, limit=10000, offset=0):
        return self.tx.rows('SELECT * FROM import_rows WHERE organisation_id=? AND batch_id=? ORDER BY row_number LIMIT ? OFFSET ?',
                            (self.oid, batch_id, limit, offset))

    def transition(self, batch_id, status):
        self.batch(batch_id)
        if self.tx.execute("UPDATE import_batches SET status=?,updated_at=? WHERE organisation_id=? AND id=? AND status='staged'",
                           (status, utc_now(), self.oid, batch_id)).rowcount != 1:
            raise ValueError('Only a staged batch can be committed or discarded')

    def counts(self, batch_id):
        self.tx.execute("UPDATE import_batches SET total_rows=(SELECT COUNT(*) FROM import_rows WHERE organisation_id=? AND batch_id=?),"
                        "error_count=(SELECT COUNT(*) FROM import_rows WHERE organisation_id=? AND batch_id=? AND error<>''),"
                        "warning_count=(SELECT COUNT(*) FROM import_rows WHERE organisation_id=? AND batch_id=? AND warning<>''),updated_at=? "
                        "WHERE organisation_id=? AND id=?",
                        (self.oid, batch_id, self.oid, batch_id, self.oid, batch_id, utc_now(), self.oid, batch_id))

    def stage_batch(self, kind, actor):
        batch_id, now = new_id(), utc_now()
        self.tx.execute("INSERT INTO import_batches(id,organisation_id,kind,status,created_by,created_at,updated_at) VALUES (?,?,?,'staged',?,?,?)",
                        (batch_id, self.oid, kind, actor, now, now))
        return batch_id

    def stage_row(self, batch_id, number, raw, parsed, error='', warning=''):
        now = utc_now()
        self.tx.execute('INSERT INTO import_rows(id,organisation_id,batch_id,row_number,raw_json,parsed_json,error,warning,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (new_id(), self.oid, batch_id, number, canonical_json(raw), canonical_json(parsed), error, warning, now, now))

    def outcome(self, row_id, entity_id, error='', warning=''):
        self.tx.execute('UPDATE import_rows SET entity_id=?,error=?,warning=?,updated_at=? WHERE organisation_id=? AND id=?',
                        (entity_id, error, warning, utc_now(), self.oid, row_id))

    def existing(self, kind, fields):
        if kind == 'contacts':
            return self.tx.one("SELECT id FROM contacts WHERE organisation_id=? AND (LOWER(name)=LOWER(?) OR (registration_no=? AND registration_no<>'')) ORDER BY id LIMIT 1",
                               (self.oid, fields['name'], fields.get('registry_code', '')))
        return self.tx.one('SELECT id FROM items WHERE organisation_id=? AND code=?', (self.oid, fields['code']))

    def account(self, code, role):
        if code:
            return self.tx.one('SELECT id FROM accounts WHERE organisation_id=? AND code=? AND active=1', (self.oid, code))
        return self.tx.one('SELECT id FROM accounts WHERE organisation_id=? AND system_role=? AND active=1', (self.oid, role))

    def create(self, kind, fields, country):
        entity_id, now = new_id(), utc_now()
        if kind == 'contacts':
            self.tx.execute('INSERT INTO contacts(id,organisation_id,name,contact_type,email,phone,address,registration_no,vat_no,iban,country_code,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (entity_id, self.oid, fields['name'], fields['contact_type'], fields.get('email'), fields.get('phone'), fields.get('address'),
                             fields.get('registry_code'), fields.get('vat_number'), fields.get('bank_account'), country, now, now))
        else:
            self.tx.execute("INSERT INTO items(id,organisation_id,code,name,item_type,sales_account_id,purchase_account_id,unit,unit_price,purchase_price,created_at,updated_at) VALUES (?,?,?,?,'service',?,?,?,?,?,?,?)",
                            (entity_id, self.oid, fields['code'], fields['name'], fields['sales_account_id'], fields['purchase_account_id'],
                             fields.get('unit', ''), fields.get('sale_price') or None, fields.get('purchase_price') or None, now, now))
        return entity_id
