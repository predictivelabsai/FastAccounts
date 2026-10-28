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
    assert gross - pension_amount - ui - income_tax >= Decimal('1500.00')
    assert gross.quantize(Decimal('.01')) == gross


def test_existing_fixed_sum_default_is_bit_exact():
    assert calculate_component_amount('fixed_sum', amount='123.456') == Decimal('123.46')
