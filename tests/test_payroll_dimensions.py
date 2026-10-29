from payroll_dimensions import PayrollDimensionService
from payroll import PayrollService
from payroll_contracts import PayrollContractService
import pytest


def test_payroll_dimension_register_crud_and_tenant_scope(db, ee_org):
    service = PayrollDimensionService(db)
    group = service.save(ee_org['id'], kind='position_group', code='FIN', name='Finance', actor='owner@example.test')
    position = service.save(ee_org['id'], kind='position', code='ACC', name='Accountant', parent_id=group['id'], actor='owner@example.test')
    department = service.save(ee_org['id'], kind='department', code='OPS', name='Operations', actor='owner@example.test')
    assert service.list(ee_org['id'], 'position') == [position]
    assert service.list('another-tenant') == []
    updated = service.save(ee_org['id'], kind='department', code='OPS', name='Operations team', dimension_id=department['id'], active=False, actor='owner@example.test')
    assert updated['name'] == 'Operations team' and updated['active'] == 0
    assert service.list(ee_org['id'], 'department', active_only=True) == []
    assert service.deactivate(ee_org['id'], position['id'], actor='owner@example.test') == {'deactivated': True}


def test_payroll_dimension_rejects_invalid_group_and_duplicate_code(db, ee_org):
    service = PayrollDimensionService(db)
    group = service.save(ee_org['id'], kind='position_group', code='FIN', name='Finance', actor='owner@example.test')
    try:
        service.save(ee_org['id'], kind='position', code='ACC', name='Accountant', parent_id='foreign-id', actor='owner@example.test')
    except ValueError as error:
        assert 'Position group' in str(error)
    else:
        raise AssertionError('Foreign position group accepted')
    try:
        service.save(ee_org['id'], kind='position_group', code='FIN', name='Other', actor='owner@example.test')
    except ValueError as error:
        assert 'already exists' in str(error)
    else:
        raise AssertionError('Duplicate dimension code accepted')
    assert service.list(ee_org['id']) == [group]


def test_employee_and_contract_dimensions_are_tenant_checked(db, ee_org, legacy_payroll):
    employee = legacy_payroll(db, ee_org['id'], name='Dimension employee', gross='2000')
    dimensions = PayrollDimensionService(db)
    department = dimensions.save(ee_org['id'], kind='department', code='ENG', name='Engineering', actor='owner@example.test')
    group = dimensions.save(ee_org['id'], kind='position_group', code='TECH', name='Technical', actor='owner@example.test')
    position = dimensions.save(ee_org['id'], kind='position', code='DEV', name='Developer', parent_id=group['id'], actor='owner@example.test')
    saved = PayrollService(db).save_employee(ee_org['id'], employee_id='legacy-employee', actor='owner@example.test',
                                            department_id=department['id'], position_id=position['id'])
    assert saved['department_id'] == department['id']
    contracts = PayrollContractService(db)
    contract = contracts.create(ee_org['id'], 'legacy-employee', contract_type='employment', start_date='2026-01-01',
        actor='owner@example.test', department_id=department['id'], position_id=position['id'],
        agreement={'base_pay_type': 'monthly', 'rate': '2000', 'fte': '1', 'department_id': department['id']})
    assert contract['department_id'] == department['id']
    assert contract['agreements'][0]['department_id'] == department['id']
    with pytest.raises(ValueError, match='belong to this organisation'):
        PayrollService(db).save_employee(ee_org['id'], employee_id='legacy-employee', actor='owner@example.test',
                                         department_id='foreign-dimension')
