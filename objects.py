"""Analytical dimension administration and validation, independent of posting amounts."""
from core_utils import audit, new_id
from database import get_database
from objects_repository import ObjectRepository, DIMENSIONS


class ObjectService:
    def __init__(self, db=None):
        self.db = db or get_database()

    def list(self, organisation_id):
        with self.db.transaction() as tx:
            return ObjectRepository(tx, organisation_id).list()

    def get(self, organisation_id, object_id):
        with self.db.transaction() as tx:
            return ObjectRepository(tx, organisation_id).get(object_id)

    @staticmethod
    def _validate(repo, data, object_id=None):
        if data['object_type'] not in DIMENSIONS.values() or not isinstance(data['active'], bool):
            raise ValueError('Valid object type and active boolean are required')
        data = dict(data)
        for key, limit in [('code', 40), ('name', 180), ('notes', 2000)]:
            if not isinstance(data[key], str):
                raise ValueError('Invalid object fields')
            data[key] = data[key].strip()
            if len(data[key]) > limit or (key != 'notes' and not data[key]):
                raise ValueError('An object requires a code and name within the length limits')
        if repo.duplicate(data['object_type'], data['code'], object_id):
            raise ValueError('Object code already exists for this type')
        return data

    def create(self, organisation_id, *, object_type, code, name, actor, active=True, notes=''):
        with self.db.transaction() as tx:
            repo = ObjectRepository(tx, organisation_id)
            repo.lock_organisation()
            data = self._validate(repo, dict(object_type=object_type, code=code, name=name, active=active, notes=notes))
            object_id = new_id()
            row = repo.save(object_id, data)
            audit(tx, organisation_id, actor, 'object.created', 'object', object_id)
            return row

    def update(self, organisation_id, object_id, *, actor, **changes):
        if changes.keys() - {'object_type', 'code', 'name', 'active', 'notes'} or any(v is None for v in changes.values()):
            raise ValueError('Invalid object fields')
        with self.db.transaction() as tx:
            repo = ObjectRepository(tx, organisation_id)
            repo.lock_organisation()
            current = repo.get(object_id)
            current['active'] = bool(current['active'])
            data = self._validate(repo, current | changes, object_id)
            if data['object_type'] != current['object_type'] and repo.referenced(object_id):
                raise ValueError('A referenced object cannot change type')
            row = repo.save(object_id, data, existing=True)
            audit(tx, organisation_id, actor, 'object.updated', 'object', object_id, {'active': data['active']})
            return row

    def delete(self, organisation_id, object_id, *, actor):
        with self.db.transaction() as tx:
            repo = ObjectRepository(tx, organisation_id)
            repo.lock_organisation()
            repo.get(object_id)
            if repo.referenced(object_id):
                raise ValueError('This object is in use. Deactivate it instead.')
            repo.delete(object_id)
            audit(tx, organisation_id, actor, 'object.deleted', 'object', object_id)
        return {'deleted': True}


def dimensions(data):
    """Normalise optional dimension IDs from a document dictionary or PostingLine."""
    return {key: (data.get(key) if isinstance(data, dict) else getattr(data, key)) or None for key in DIMENSIONS}


def validate_dimensions(repo, data, *, active=True):
    values = dimensions(data)
    for key, object_id in values.items():
        if object_id:
            row = repo.get(object_id)
            if row['object_type'] != DIMENSIONS[key] or (active and not row['active']):
                raise ValueError('Object dimension must match its type and be active')
    return values
