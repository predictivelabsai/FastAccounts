"""Tenant-scoped analytical objects and additive line dimension storage."""
from core_utils import utc_now

DIMENSIONS = {'projects_project_id': 'project', 'projects_location_id': 'location',
              'projects_person_id': 'person', 'projects_object_id': 'object'}


class ObjectRepository:
    def __init__(self, tx, organisation_id):
        self.tx, self.oid = tx, organisation_id

    def lock_organisation(self):
        if self.tx.execute('UPDATE organisations SET name=name WHERE id=?', (self.oid,)).rowcount != 1:
            raise KeyError('Organisation not found')

    def list(self):
        return self.tx.rows('SELECT * FROM objects WHERE organisation_id=? ORDER BY object_type,code,id', (self.oid,))

    def get(self, object_id):
        row = self.tx.one('SELECT * FROM objects WHERE organisation_id=? AND id=?', (self.oid, object_id))
        if not row:
            raise KeyError('Object not found')
        return row

    def duplicate(self, kind, code, object_id):
        return self.tx.one('SELECT id FROM objects WHERE organisation_id=? AND object_type=? AND code=? AND id<>?',
                           (self.oid, kind, code, object_id or ''))

    def save(self, object_id, data, existing=False):
        now = utc_now()
        values = (data['object_type'], data['code'], data['name'], int(data['active']), data['notes'], now)
        if existing:
            self.tx.execute('UPDATE objects SET object_type=?,code=?,name=?,active=?,notes=?,updated_at=? WHERE organisation_id=? AND id=?',
                            (*values, self.oid, object_id))
        else:
            self.tx.execute('INSERT INTO objects(object_type,code,name,active,notes,updated_at,created_at,organisation_id,id) VALUES (?,?,?,?,?,?,?,?,?)',
                            (*values, now, self.oid, object_id))
        return self.get(object_id)

    def referenced(self, object_id):
        predicate = ' OR '.join(f'{key}=?' for key in DIMENSIONS)
        return any(self.tx.one(f'SELECT line_id FROM {table} WHERE organisation_id=? AND ({predicate}) LIMIT 1',
                               (self.oid, *([object_id] * len(DIMENSIONS))))
                   for table in ('invoice_line_objects', 'bill_line_objects', 'gl_entry_objects'))

    def delete(self, object_id):
        self.tx.execute('DELETE FROM objects WHERE organisation_id=? AND id=?', (self.oid, object_id))

    def save_dimensions(self, kind, parent_id, line_id, values, payroll_values=None):
        payroll_values = payroll_values or {}
        if not any(values.values()) and not any(payroll_values.values()):
            return
        table = {'invoice': 'invoice_line_objects', 'bill': 'bill_line_objects', 'gl': 'gl_entry_objects'}[kind]
        extra = tuple(payroll_values) if kind == 'gl' else ()
        columns = ','.join((*DIMENSIONS, *extra))
        self.tx.execute(f'INSERT INTO {table}(organisation_id,parent_id,line_id,{columns}) VALUES (' +
                        ','.join('?' for _ in range(3 + len(DIMENSIONS) + len(extra))) + ')',
                        (self.oid, parent_id, line_id, *(values[k] for k in DIMENSIONS),
                         *(payroll_values[key] for key in extra)))

    def document_lines(self, kind, parent_id):
        table, parent = {'invoice': ('invoice_lines', 'invoice_id'), 'bill': ('bill_lines', 'bill_id')}[kind]
        headers = {'invoice': 'invoices', 'bill': 'bills'}[kind]
        if not self.tx.scalar("SELECT 1 FROM schema_migrations WHERE version='0023_analytical_objects'"):
            return self.tx.rows(f'SELECT l.* FROM {table} l JOIN {headers} h ON h.id=l.{parent} '
                                f'WHERE h.organisation_id=? AND h.id=? ORDER BY l.line_number', (self.oid, parent_id))
        columns = ','.join(f'd.{key}' for key in DIMENSIONS)
        return self.tx.rows(f'SELECT l.*,{columns} FROM {table} l JOIN {headers} h ON h.id=l.{parent} '
                            f'LEFT JOIN {kind}_line_objects d ON d.organisation_id=h.organisation_id AND d.line_id=l.id '
                            f'WHERE h.organisation_id=? AND h.id=? ORDER BY l.line_number', (self.oid, parent_id))
