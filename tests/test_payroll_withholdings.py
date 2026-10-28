from decimal import Decimal

import pytest

from payroll_withholdings import PayrollWithholdingService, calculate_withholding, normalise_iban


@pytest.mark.parametrize(('method','payload','expected'), [
    ('fixed_sum', {'monthly_amount': '25.50'}, Decimal('25.50')),
    ('percent_of_gross', {'percentage': '10'}, Decimal('200.00')),
    ('sum_x_qty', {'rate': '3.25','quantity': '4'}, Decimal('13.00')),
    ('third_pillar_net', {'monthly_amount': '100'}, Decimal('100.00')),
])
def test_withholding_methods_are_decimal_and_limited_by_net(method, payload, expected):
    agreement = {'method': method, 'component_type': 'agreed_deduction', **payload}
    assert calculate_withholding(agreement, gross='2000', net='500') == expected
    assert calculate_withholding(agreement, gross='2000', net='10') == Decimal('10.00')


def test_withholding_cap_garnishable_limit_and_third_pillar_net_only():
    agreement = {'method': 'fixed_sum', 'component_type': 'bailiff',
                 'monthly_amount': '500', 'total_cap': '300'}
    assert calculate_withholding(agreement, gross='2000', net='900', withheld_to_date='260',
                                 garnishable='20') == Decimal('20.00')
    pillar = {'method': 'third_pillar_net', 'component_type': 'third_pillar', 'monthly_amount': '500'}
    assert calculate_withholding(pillar, gross='1000', net='900') == Decimal('500.00')


def test_iban_normalisation_and_validation():
    assert normalise_iban('ee38 2200 2210 2014 5685') == 'EE382200221020145685'
    with pytest.raises(ValueError, match='valid IBAN'):
        normalise_iban('EE0000')


def test_recipient_and_agreement_are_tenant_scoped(db, ee_org, legacy_payroll):
    actor = 'owner@example.test'
    run = legacy_payroll(db, ee_org['id'], name='Synthetic recipient employee', gross='2000')
    employee_id = run['items'][0]['employee_id']
    service = PayrollWithholdingService(db)
    recipient = service.save_recipient(ee_org['id'], actor=actor, name='Synthetic recipient',
        registry_code='12345678', iban='EE382200221020145685', default_description='Salary order')
    agreement = service.save_agreement(ee_org['id'], actor=actor, employee_id=employee_id,
        recipient_id=recipient['id'], component_type='alimony', method='fixed_sum',
        start_date='2026-01-01', monthly_amount='50.00')
    assert service.recipients(ee_org['id'])[0]['iban'] == 'EE382200221020145685'
    assert service.agreements(ee_org['id'])[0]['id'] == agreement['id']
    assert service.recipients('unknown-tenant') == []
    with pytest.raises(KeyError, match='Employee'):
        service.save_agreement(ee_org['id'], actor=actor, employee_id='foreign-employee',
            recipient_id=recipient['id'], component_type='alimony', method='fixed_sum', start_date='2026-01-01', monthly_amount='50')
