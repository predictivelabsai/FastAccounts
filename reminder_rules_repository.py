"""Organisation-scoped reminder rule persistence, shared by both databases."""
from core_utils import utc_now


class ReminderRuleRepository:
    def __init__(self, tx, organisation_id):
        self.tx, self.oid = tx, organisation_id

    def get(self):
        return self.tx.one('SELECT * FROM reminder_rules WHERE organisation_id=?', (self.oid,))

    def save(self, data):
        if self.tx.execute('UPDATE organisations SET name=name WHERE id=?', (self.oid,)).rowcount != 1:
            raise KeyError('Organisation not found')
        self.tx.execute(
            'INSERT INTO reminder_rules(organisation_id,enabled,stage_1_days,stage_2_days,stop_stage,updated_at) '
            'VALUES (?,?,?,?,?,?) ON CONFLICT(organisation_id) DO UPDATE SET enabled=excluded.enabled,'
            'stage_1_days=excluded.stage_1_days,stage_2_days=excluded.stage_2_days,'
            'stop_stage=excluded.stop_stage,updated_at=excluded.updated_at',
            (self.oid, int(data['enabled']), data['stages']['1'], data['stages']['2'], data['stop_stage'], utc_now()))
