from decimal import Decimal

import pytest

from payroll import PayrollService
from payroll_tax_settings import EmployeeTaxSettingsService, TaxSettingConflict

ACTOR = 'owner@example.test'


def setup(db, org):
    payroll = PayrollService(db)
    person = payroll.save_employee(org['id'], actor=ACTOR, name='Synthetic person',
                                   gross_salary='2000', apply_tax_free_minimum=True)
    return payroll, person, EmployeeTaxSettingsService(db)


@pytest.mark.parametrize('mode,amount,exemption,net', [
    ('maximum', None, '700.00', '1657.84'),
    ('limited', '300', '300.00', '1569.84'),
    ('none', None, '0.00', '1503.84'),
])
def test_effective_application_and_merit_vector(db, ee_org, mode, amount, exemption, net):
    payroll, person, settings = setup(db, ee_org)
    settings.save(ee_org['id'], person['id'], actor=ACTOR, kind='tax_free',
                  start_date='2026-10-15', mode=mode, amount=amount)
    september = payroll.create_run(ee_org['id'], period='2026-09', actor=ACTOR)
    assert september['items'][0]['tax_free_minimum'] == '700.00'
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    item = run['items'][0]
    assert item['tax_free_minimum'] == exemption
    assert item['net'] == net
    assert item['ui_employee'] == '32.00'
    assert item['ui_employer'] == '16.00'
    assert item['social_tax'] == '660.00'
    assert item['funded_pension'] == '40.00'


@pytest.mark.parametrize('rate', [0, 2, 4, 6])
def test_pension_history_is_resolved_at_month_end_and_frozen(db, ee_org, rate):
    payroll, person, settings = setup(db, ee_org)
    row = settings.save(ee_org['id'], person['id'], actor=ACTOR, kind='pension',
                        start_date='2026-10-31', rate=rate)
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    assert Decimal(run['items'][0]['funded_pension']) == Decimal('2000') * rate / 100
    payroll.approve(ee_org['id'], run['id'], actor=ACTOR)
    with pytest.raises(TaxSettingConflict, match='approved'):
        settings.delete(ee_org['id'], person['id'], row['id'], actor=ACTOR)
    with pytest.raises(TaxSettingConflict, match='approved'):
        settings.save(ee_org['id'], person['id'], actor=ACTOR, kind='pension',
                      start_date='2026-10-31', rate=6, setting_id=row['id'])
    settings.save(ee_org['id'], person['id'], actor=ACTOR, kind='pension',
                  start_date='2026-11-01', rate=0)
    assert payroll.runs(ee_org['id'])[0]['items'] == run['items']


def test_employee_ui_exclusion_and_draft_snapshot(db, ee_org):
    payroll, person, settings = setup(db, ee_org)
    row = settings.save(ee_org['id'], person['id'], actor=ACTOR, kind='unemployment',
                        start_date='2026-10-15', applies=False)
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    assert run['items'][0]['ui_employee'] == '0.00'
    assert run['items'][0]['ui_employer'] == '16.00'
    settings.delete(ee_org['id'], person['id'], row['id'], actor=ACTOR)
    edited = payroll.update_item(ee_org['id'], run['id'], run['items'][0]['id'], actor=ACTOR, components=[])
    assert edited['items'][0]['ui_employee'] == '0.00'


@pytest.mark.parametrize('amount', ['-1', '700.01', 'NaN', '10.001', None])
def test_limited_application_validation(db, ee_org, amount):
    _, person, settings = setup(db, ee_org)
    with pytest.raises(ValueError):
        settings.save(ee_org['id'], person['id'], actor=ACTOR, kind='tax_free',
                      start_date='2026-10-01', mode='limited', amount=amount)
