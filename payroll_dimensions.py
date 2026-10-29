"""Tenant-scoped payroll dimension registers."""
from core_utils import audit, new_id, utc_now
from database import get_database

KINDS = ('department', 'position_group', 'position', 'cost_centre')


class PayrollDimensionService:
    def __init__(self, db=None):
        self.db = db or get_database()

    @staticmethod
    def _validate(tx, organisation_id, kind, code, name, parent_id=None, dimension_id=None):
        if kind not in KINDS:
            raise ValueError('Unknown payroll dimension kind')
        if not isinstance(code, str) or not (code := code.strip()) or len(code) > 40:
            raise ValueError('Code is required and must be at most 40 characters')
        if not isinstance(name, str) or not (name := name.strip()) or len(name) > 180:
            raise ValueError('Name is required and must be at most 180 characters')
        if kind == 'position' and not parent_id:
            raise ValueError('A position must belong to a position group')
        if kind != 'position' and parent_id:
            raise ValueError('Only positions can belong to a position group')
        if parent_id:
            parent = tx.one('SELECT kind FROM payroll_dimensions WHERE organisation_id=? AND id=?',
                            (organisation_id, parent_id))
            if not parent or parent['kind'] != 'position_group':
                raise ValueError('Position group must belong to this organisation')
        if tx.one('SELECT id FROM payroll_dimensions WHERE organisation_id=? AND kind=? AND code=? AND id<>?',
                  (organisation_id, kind, code, dimension_id or '')):
            raise ValueError('Code already exists for this dimension kind')
        return code, name

    def list(self, organisation_id, kind=None, *, active_only=False):
        if kind is not None and kind not in KINDS:
            raise ValueError('Unknown payroll dimension kind')
        where, params = ['organisation_id=?'], [organisation_id]
        if kind:
            where.append('kind=?'); params.append(kind)
        if active_only:
            where.append('active=1')
        with self.db.transaction() as tx:
            return tx.rows('SELECT * FROM payroll_dimensions WHERE ' + ' AND '.join(where) + ' ORDER BY kind,code,id', params)

    def save(self, organisation_id, *, kind, code, name, actor, dimension_id=None, parent_id=None, active=True):
        if not isinstance(active, bool):
            raise ValueError('Active must be a boolean')
        with self.db.transaction() as tx:
            if dimension_id:
                current = tx.one('SELECT * FROM payroll_dimensions WHERE organisation_id=? AND id=?',
                                 (organisation_id, dimension_id))
                if not current:
                    raise KeyError('Payroll dimension not found')
            code, name = self._validate(tx, organisation_id, kind, code, name, parent_id, dimension_id)
            now = utc_now()
            if dimension_id:
                tx.execute('UPDATE payroll_dimensions SET kind=?,code=?,name=?,parent_id=?,active=?,updated_at=? WHERE organisation_id=? AND id=?',
                           (kind, code, name, parent_id, int(active), now, organisation_id, dimension_id))
            else:
                dimension_id = new_id()
                tx.execute('INSERT INTO payroll_dimensions(id,organisation_id,kind,code,name,parent_id,active,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                           (dimension_id, organisation_id, kind, code, name, parent_id, int(active), now, now))
            audit(tx, organisation_id, actor, 'payroll.dimension.saved', 'payroll_dimension', dimension_id,
                  {'kind': kind, 'active': active})
            return tx.one('SELECT * FROM payroll_dimensions WHERE organisation_id=? AND id=?',
                          (organisation_id, dimension_id))

    def deactivate(self, organisation_id, dimension_id, *, actor):
        with self.db.transaction() as tx:
            current = tx.one('SELECT id FROM payroll_dimensions WHERE organisation_id=? AND id=?',
                             (organisation_id, dimension_id))
            if not current:
                raise KeyError('Payroll dimension not found')
            tx.execute('UPDATE payroll_dimensions SET active=0,updated_at=? WHERE organisation_id=? AND id=?',
                       (utc_now(), organisation_id, dimension_id))
            audit(tx, organisation_id, actor, 'payroll.dimension.deactivated', 'payroll_dimension', dimension_id)
        return {'deactivated': True}
