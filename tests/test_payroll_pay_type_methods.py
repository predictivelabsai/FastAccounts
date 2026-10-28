from decimal import Decimal

import pytest

from payroll_components import calculate_component_amount


@pytest.mark.parametrize(('method', 'inputs', 'expected'), [
    ('fixed_sum', {'amount': '12.34'}, '12.34'),
    ('sum_x_qty_x_coef', {'rate': '2.5', 'quantity': '4', 'coefficient': '1.5'}, '15.00'),
    ('percentage_of_base', {'base_pay': '1000', 'percentage': '10'}, '100.00'),
    ('percentage_of_hourly_rate', {'hourly_rate': '20', 'percentage': '50', 'quantity': '4'}, '40.00'),
    ('piece_rate', {'rate': '1.25', 'quantity': '8'}, '10.00'),
    ('hourly', {'rate': '12.5', 'quantity': '8'}, '100.00'),
    ('average_monthly_pay', {'average_monthly_pay': '1800', 'quantity': '2'}, '3600.00'),
    ('average_hourly_pay', {'average_hourly_pay': '15', 'quantity': '4'}, '60.00'),
    ('average_working_day_pay', {'average_working_day_pay': '90', 'quantity': '3'}, '270.00'),
    ('contract_sum_x_quantity', {'rate': '25', 'quantity': '3'}, '75.00'),
    ('contract_sum', {'amount': '85'}, '85.00'),
    ('monthly_salary', {'amount': '1200'}, '1200.00'),
    ('monthly_salary_day_based', {'amount': '100', 'quantity': '0.5'}, '50.00'),
    ('percentage', {'base_pay': '200', 'percentage': '5'}, '10.00'),
])
def test_component_calculation_methods(method, inputs, expected):
    assert calculate_component_amount(method, **inputs) == Decimal(expected)


@pytest.mark.parametrize('pension', ['0', '2', '4', '6'])
@pytest.mark.parametrize('exemption', ['0', '700'])
def test_gross_up_from_net_reaches_target_cent(pension, exemption):
    gross = calculate_component_amount('gross_up_from_net', net_target='1500.00',
        pension_percent=pension, exemption=exemption)
    pension_amount = (gross * Decimal(pension) / 100).quantize(Decimal('.01'), rounding='ROUND_HALF_UP')
    ui = (gross * Decimal('.016')).quantize(Decimal('.01'), rounding='ROUND_HALF_UP')
    taxable = max(Decimal(0), gross - pension_amount - ui - Decimal(exemption))
    income_tax = (taxable * Decimal('.22')).quantize(Decimal('.01'), rounding='ROUND_HALF_UP')
    assert gross - pension_amount - ui - income_tax == Decimal('1500.00')
    prior = gross - Decimal('0.01')
    prior_pension = (prior * Decimal(pension) / 100).quantize(Decimal('.01'), rounding='ROUND_HALF_UP')
    prior_ui = (prior * Decimal('.016')).quantize(Decimal('.01'), rounding='ROUND_HALF_UP')
    prior_tax = (max(Decimal(0), prior - prior_pension - prior_ui - Decimal(exemption)) * Decimal('.22')).quantize(Decimal('.01'), rounding='ROUND_HALF_UP')
    assert prior - prior_pension - prior_ui - prior_tax < Decimal('1500.00')
    assert gross.quantize(Decimal('.01')) == gross


def test_existing_fixed_sum_default_is_bit_exact():
    assert calculate_component_amount('fixed_sum', amount='123.456') == Decimal('123.46')


def test_seeded_methods_and_tsd_codes(db, ee_org):
    from payroll import PayrollService
    from payroll_rules import rules_for
    from datetime import date
    types = {row['preset_key']: row for row in PayrollService(db).component_types(ee_org['id'])}
    assert types['overtime']['calculation_method'] == 'percentage_of_hourly_rate'
    assert types['overtime']['default_percentage'] == '150'
    assert types['birth_allowance']['tsd_payment_type'] == 14
    assert types['work_accident_benefit']['tsd_payment_type'] == 32
    assert types['notice_pay']['tsd_payment_type'] == 33
    assert types['rest_day']['palk_row'] == 7
    assert types['unused_leave']['palk_row'] == 9
    assert types['birth_allowance']['palk_row'] == 16
    assert types['work_accident_benefit']['palk_row'] == 17
    assert types['car_compensation']['default_rate'] == '0.3'
    assert types['car_compensation']['default_coefficient'] == '335'
    car_rules = rules_for(date(2026, 10, 1))
    assert car_rules.private_car_rate_per_km == Decimal('0.30')
    assert car_rules.private_car_monthly_limit == Decimal('335')


def test_service_calculates_and_freezes_method_line(db, ee_org, legacy_payroll):
    from payroll import PayrollService
    service = PayrollService(db)
    run = legacy_payroll(db, ee_org['id'], name='Method employee', gross='2000')
    bonus = next(t for t in service.component_types(ee_org['id']) if t['preset_key'] == 'bonus')
    result = service.update_item(ee_org['id'], run['id'], run['items'][0]['id'],
        actor='owner@example.test', components=[{'type_id': bonus['id'], 'percentage': '10'}])
    assert Decimal(result['items'][0]['components'][0]['amount']) == Decimal('200.00')
    line = result['items'][0]['components'][0]
    assert line['calculation_method'] == 'percentage_of_base' and line['palk_row'] == 5
    service.approve(ee_org['id'], run['id'], actor='owner@example.test')
    with pytest.raises(Exception, match='Only draft'):
        service.update_item(ee_org['id'], run['id'], run['items'][0]['id'],
            actor='owner@example.test', components=[])


def test_service_gross_up_from_net_accounts_for_existing_pay(db, ee_org, legacy_payroll):
    from payroll import PayrollService
    service = PayrollService(db)
    run = legacy_payroll(db, ee_org['id'], name='Gross-up employee', gross='2000')
    item = run['items'][0]
    before = Decimal(item['net'])
    gross_up = service.save_component_type(ee_org['id'], actor='owner@example.test', name='Net gross-up',
        calculation_method='gross_up_from_net', income_tax=True, social_tax=True,
        ui_employee=True, ui_employer=True, funded_pension=True, social_minimum=True)
    result = service.update_item(ee_org['id'], run['id'], item['id'], actor='owner@example.test',
        components=[{'type_id': gross_up['id'], 'net_target': '100'}])
    assert Decimal(result['items'][0]['components'][0]['amount']) == Decimal('132.99')
    assert Decimal(result['items'][0]['components'][0]['amount']) > Decimal('100')
    assert Decimal(result['items'][0]['net']) - before == Decimal('100.00')
