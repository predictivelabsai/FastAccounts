from datetime import date
from decimal import Decimal
from dataclasses import FrozenInstanceError

import pytest

from payroll import calculate_pay, minimum_wage, PayrollService
from payroll_rules import rules_for, settlement_date, UnsupportedPayrollYear


def test_verified_rules_and_minimum_wage_boundary():
    rules = rules_for(date(2026, 1, 1))
    assert rules.basic_exemption == Decimal('700')
    assert minimum_wage('2026-03') == (Decimal('886'), Decimal('5.31'))
    assert minimum_wage('2026-04') == (Decimal('946'), Decimal('5.67'))
    assert settlement_date('2026-02') == date(2026, 2, 28)
    with pytest.raises(FrozenInstanceError):
        rules.year = 2027


@pytest.mark.parametrize('year', [2025, 2027])
def test_unsupported_rules_fail_without_creating_a_run(db, ee_org, year):
    with pytest.raises(UnsupportedPayrollYear, match='not configured'):
        rules_for(date(year, 1, 1))
    with pytest.raises(UnsupportedPayrollYear):
        minimum_wage(f'{year}-10')
    service = PayrollService(db)
    with pytest.raises(UnsupportedPayrollYear):
        service.create_run(ee_org['id'], period=f'{year}-10', actor='owner@example.test')
    assert service.runs(ee_org['id']) == []
    with pytest.raises(UnsupportedPayrollYear):
        calculate_pay({}, period=f'{year}-10')
