from datetime import date

import pytest

from organisations import OrganisationService
from payroll_payday import PaydaySettingsService, payday


@pytest.mark.parametrize(('period', 'rule', 'day', 'expected'), [
    ('2026-10', 'next_month_day', 10, date(2026, 11, 10)),
    ('2026-10', 'current_month_day', 31, date(2026, 10, 30)),
    ('2026-07', 'next_month_day', 31, date(2026, 8, 31)),
    ('2026-10', 'next_month_first_working_day', None, date(2026, 11, 2)),
    ('2026-02', 'current_month_day', 24, date(2026, 2, 23)),
])
def test_payday_rules_clamp_and_shift_back(period, rule, day, expected):
    assert payday(period, rule, day) == expected


def test_dated_payday_rules_are_scoped_and_audited(db):
    org = OrganisationService(db).create(name='Payday test', country_code='EE', entity_type='EE_OU', owner_email='owner@example.test')
    other = OrganisationService(db).create(name='Other test', country_code='EE', entity_type='EE_OU', owner_email='other@example.test')
    service = PaydaySettingsService(db)
    saved = service.save(org['id'], start_date='2026-01-01', rule_start_date='2026-01-01',
                         rule='next_month_day', day=5, actor='owner@example.test')
    service.save(org['id'], start_date='2026-01-01', rule_start_date='2026-07-01',
                 rule='current_month_day', day=10, actor='owner@example.test')
    assert [rule['start_date'] for rule in service.get(org['id'])['rules']] == ['2026-01-01', '2026-07-01']
    assert service.get(other['id']) == {'payroll_start_date': None, 'language': 'et', 'rules': []}
    assert db.scalar("SELECT COUNT(*) FROM audit_events WHERE organisation_id=? AND action='payroll.payday_rule.saved'", (org['id'],)) == 2
    assert saved['payroll_start_date'] == '2026-01-01'


@pytest.mark.parametrize(('rule', 'day'), [('next_month_first_working_day', 2), ('current_month_day', None)])
def test_payday_rule_requires_valid_day(rule, day):
    with pytest.raises(ValueError):
        payday('2026-10', rule, day)
