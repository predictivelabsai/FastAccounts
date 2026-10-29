from payroll import PayrollService
from payroll_contracts import PayrollContractService
from decimal import Decimal


def test_contract_agreement_history_and_tenant_scope(db, ee_org, legacy_payroll):
    legacy_payroll(db, ee_org['id'], name='Contracted', gross='2000')
    service = PayrollContractService(db)
    contract = service.create(ee_org['id'], 'legacy-employee', contract_type='employment',
                              start_date='2026-01-01', actor='owner@example.test',
                              monthly_net_advance='100.25', payday_rule='next_month_day', payday_day=5,
                              agreement={'base_pay_type': 'monthly', 'rate': '2000.00', 'fte': '0.8'},
                              position={'position': 'Accountant', 'occupation_code': '3313'})
    assert contract['contract_type'] == 'employment'
    assert Decimal(str(contract['monthly_net_advance'])) == Decimal('100.25')
    assert Decimal(str(contract['agreements'][0]['fte'])) == Decimal('0.8')
    assert contract['positions'][0]['occupation_code'] == '3313'
    updated = service.add_agreement(ee_org['id'], contract['id'], start_date='2026-07-01', actor='owner@example.test',
                                   base_pay_type='monthly_day_based', rate='2200', fte='1')
    with db.transaction() as tx:
        selected = tx.one('SELECT * FROM payroll_salary_agreements WHERE organisation_id=? AND contract_id=? AND start_date<=? ORDER BY start_date DESC LIMIT 1',
                          (ee_org['id'], contract['id'], '2026-10-31'))
        assert selected['id'] == updated['id']
        assert tx.one('SELECT id FROM payroll_contracts WHERE organisation_id=? AND id=?', ('wrong-tenant', contract['id'])) is None


def test_contract_validation_rejects_bad_fte_and_foreign_employee(db, ee_org):
    service = PayrollContractService(db)
    try:
        service.create(ee_org['id'], 'missing', contract_type='employment', start_date='2026-01-01',
                       actor='owner@example.test', agreement={'base_pay_type': 'monthly', 'rate': '100', 'fte': '1.1'})
    except ValueError as error:
        assert str(error) == 'FTE must be greater than 0 and at most 1'
    else:
        raise AssertionError('Invalid FTE was accepted')
    assert PayrollService(db).employees(ee_org['id']) == []
