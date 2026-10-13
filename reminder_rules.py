"""Small fixed-ladder reminder configuration. Absent rows preserve legacy timings."""
from core_utils import audit
from database import get_database
from reminder_rules_repository import ReminderRuleRepository

DEFAULT_STAGES = ((0, -3), (1, 7), (2, 14))


def validate_rule(data):
    if set(data) != {'enabled', 'stages', 'stop_stage'} or type(data['enabled']) is not bool:
        raise ValueError('Reminder rules require an enabled boolean, stages and stop stage')
    stages = data['stages']
    if not isinstance(stages, dict) or set(stages) != {'1', '2'}:
        raise ValueError('Reminder stages must be 1 and 2; stage 0 stays three days before due')
    if any(type(day) is not int for day in stages.values()) or not 1 <= stages['1'] < stages['2'] <= 14:
        raise ValueError('Reminder offsets must increase strictly within 1 to 14 days after due')
    stop = data['stop_stage']
    if stop is not None and (type(stop) is not int or stop not in {0, 1, 2}):
        raise ValueError('Stop stage must be 0, 1 or 2')
    return data


class ReminderRuleService:
    def __init__(self, db=None):
        self.db = db or get_database()

    @staticmethod
    def _payload(row):
        data = dict(enabled=bool(row['enabled']) if row else True,
                    stages={'1': row['stage_1_days'] if row else 7, '2': row['stage_2_days'] if row else 14},
                    stop_stage=row['stop_stage'] if row else None, configured=row is not None)
        ladder = ((0, -3), (1, data['stages']['1']), (2, data['stages']['2'])) if row else DEFAULT_STAGES
        data['effective_stages'] = [dict(stage=stage, days=days) for stage, days in ladder
                                    if data['enabled'] and (data['stop_stage'] is None or stage <= data['stop_stage'])]
        return data

    def get(self, organisation_id):
        with self.db.transaction() as tx:
            return self._payload(ReminderRuleRepository(tx, organisation_id).get())

    def save(self, organisation_id, *, actor, enabled, stages, stop_stage=None):
        data = validate_rule(dict(enabled=enabled, stages=stages, stop_stage=stop_stage))
        with self.db.transaction() as tx:
            repo = ReminderRuleRepository(tx, organisation_id)
            repo.save(data)
            audit(tx, organisation_id, actor, 'reminder_rules.updated', 'reminder_rules', organisation_id, data)
            return self._payload(repo.get())

    def ladder(self, organisation_id):
        return tuple((item['stage'], item['days']) for item in self.get(organisation_id)['effective_stages'])
