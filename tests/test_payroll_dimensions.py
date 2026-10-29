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


def test_approved_payroll_dimension_costs_use_frozen_tenant_scoped_values(db, ee_org, legacy_payroll):
    from payroll_reports import PayrollReportsService
    dimensions = PayrollDimensionService(db)
    department = dimensions.save(ee_org['id'], kind='department', code='OPS', name='Operations', actor='owner@example.test')
    run = legacy_payroll(db, ee_org['id'], name='Frozen dimension employee', gross='2000')
    PayrollService(db).save_employee(ee_org['id'], employee_id='legacy-employee', actor='owner@example.test',
                                     department_id=department['id'])
    PayrollService(db).approve(ee_org['id'], run['id'], actor='owner@example.test')
    PayrollService(db).save_employee(ee_org['id'], employee_id='legacy-employee', actor='owner@example.test',
                                     department_id=None)
    report = PayrollReportsService(db).dimension_costs(ee_org['id'], '2026-10', '2026-10')
    assert len(report) == 1
    assert report[0]['dimension_id'] == department['id']
    assert report[0]['gross'] == '2000.00'
    assert PayrollReportsService(db).dimension_costs('other-tenant', '2026-10', '2026-10') == []


def test_approval_splits_payroll_expenses_with_frozen_analytical_tags(db, ee_org, legacy_payroll):
    from decimal import Decimal
    dimensions = PayrollDimensionService(db)
    department = dimensions.save(ee_org['id'], kind='department', code='OPS', name='Operations', actor='owner@example.test')
    run = legacy_payroll(db, ee_org['id'], name='Tagged employee', gross='2000')
    PayrollService(db).save_employee(ee_org['id'], employee_id='legacy-employee', actor='owner@example.test',
                                     department_id=department['id'])
    PayrollService(db).approve(ee_org['id'], run['id'], actor='owner@example.test')
    batch = db.one('SELECT * FROM posting_batches WHERE organisation_id=? AND voucher_id=?', (ee_org['id'], run['id']))
    entries = db.rows('SELECT g.*,a.system_role,d.payroll_department_id,d.payroll_cost_centre_id,d.projects_project_id '
                      'FROM gl_entries g JOIN accounts a ON a.organisation_id=g.organisation_id AND a.id=g.account_id '
                      'LEFT JOIN gl_entry_objects d ON d.organisation_id=g.organisation_id AND d.line_id=g.id '
                      'WHERE g.organisation_id=? AND g.posting_batch_id=? ORDER BY g.line_number',
                      (ee_org['id'], batch['id']))
    salary = [entry for entry in entries if entry['system_role'] == 'PAYROLL_SALARY']
    assert sum((Decimal(entry['debit']) for entry in salary), Decimal(0)) == Decimal(run['items'][0]['gross'])
    assert len(salary) == 1
    assert salary[0]['payroll_department_id'] == department['id']
    expense_entries = [entry for entry in entries if entry['system_role'] in {'PAYROLL_SALARY', 'PAYROLL_SOCIAL', 'PAYROLL_UI'}]
    assert all(entry['payroll_department_id'] == department['id'] for entry in expense_entries)
    assert all(not entry['payroll_department_id'] for entry in entries if entry['system_role'] not in {'PAYROLL_SALARY', 'PAYROLL_SOCIAL', 'PAYROLL_UI'})
    assert sum((Decimal(entry['debit']) for entry in entries), Decimal(0)) == sum((Decimal(entry['credit']) for entry in entries), Decimal(0))
