from decimal import Decimal

from payroll import PayrollService
from payroll_withholdings import PayrollWithholdingService


ACTOR = 'owner@example.test'


def setup_agreement(db, ee_org, payroll, *, method='fixed_sum', component_type='agreed_deduction', **values):
    employee = payroll.save_employee(ee_org['id'], actor=ACTOR, name='Withholding employee',
                                     gross_salary=values.pop('gross_salary', '2000'))
    service = PayrollWithholdingService(db)
    recipient = service.save_recipient(ee_org['id'], actor=ACTOR, name='Recipient',
        registry_code='12345678', iban='EE382200221020145685')
    agreement = service.save_agreement(ee_org['id'], actor=ACTOR, employee_id=employee['id'],
        recipient_id=recipient['id'], component_type=component_type, method=method,
        start_date='2026-01-01', **values)
    return employee, service, agreement


def test_draft_generates_each_method_and_third_pillar_note(db, ee_org):
    payroll = PayrollService(db)
    cases = [('fixed_sum', 'agreed_deduction', {'monthly_amount': '20'}, '20.00'),
             ('percent_of_gross', 'union_fee', {'percentage': '2'}, '40.00'),
             ('sum_x_qty', 'agreed_deduction', {'rate': '3', 'quantity': '4'}, '12.00'),
             ('third_pillar_net', 'third_pillar', {'monthly_amount': '25'}, '25.00')]
    for index, (method, kind, payload, expected) in enumerate(cases):
        employee = payroll.save_employee(ee_org['id'], actor=ACTOR, name=f'Employee {index}', gross_salary='2000')
        svc = PayrollWithholdingService(db)
        recipient = svc.save_recipient(ee_org['id'], actor=ACTOR, name=f'Recipient {index}',
            registry_code=f'1234567{index}', iban='EE382200221020145685')
        svc.save_agreement(ee_org['id'], actor=ACTOR, employee_id=employee['id'], recipient_id=recipient['id'],
            component_type=kind, method=method, start_date='2026-01-01', **payload)
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    amounts = [item['withholdings'][0]['amount'] for item in run['items']]
    assert amounts == [case[3] for case in cases]
    assert 'tax-free treatment (TSD type 25 / exemption 640) pending accountant confirmation' in run['items'][-1]['withholdings'][0]['description']


def test_cap_and_ordinary_garnishable_limit_reduce_with_warning(db, ee_org):
    payroll = PayrollService(db)
    employee, service, agreement = setup_agreement(db, ee_org, payroll, component_type='bailiff',
        monthly_amount='900', total_cap='1000')
    with db.transaction() as tx:
        tx.execute('UPDATE payroll_withholding_agreements SET withheld_to_date=800 WHERE organisation_id=? AND id=?',
                   (ee_org['id'], agreement['id']))
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    item = next(row for row in run['items'] if row['employee_id'] == employee['id'])
    line = item['withholdings'][0]
    assert line['amount'] == '200.00'
    assert 'reduced to legal/net limit' not in line['description']
    with db.transaction() as tx:
        tx.execute('UPDATE payroll_withholding_agreements SET withheld_to_date=0,total_cap=NULL WHERE organisation_id=? AND id=?',
                   (ee_org['id'], agreement['id']))
    payroll.delete_run(ee_org['id'], run['id'], actor=ACTOR)
    run = payroll.create_run(ee_org['id'], period='2026-11', actor=ACTOR)
    item = next(row for row in run['items'] if row['employee_id'] == employee['id'])
    assert Decimal(item['withholdings'][0]['amount']) <= Decimal('557.84')
    assert item['withholding_warnings']


def test_child_maintenance_uses_lower_protected_portion_and_warning(db, ee_org):
    payroll = PayrollService(db)
    employee, _, _ = setup_agreement(db, ee_org, payroll, component_type='alimony', monthly_amount='1200')
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    item = next(row for row in run['items'] if row['employee_id'] == employee['id'])
    assert item['withholdings'][0]['amount'] == '1030.84'
    assert item['withholding_warnings']


def test_manual_components_survive_recalculation_with_generated_lines(db, ee_org):
    payroll = PayrollService(db)
    employee, service, agreement = setup_agreement(db, ee_org, payroll, monthly_amount='30')
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    item = next(row for row in run['items'] if row['employee_id'] == employee['id'])
    manual_agreement = service.save_agreement(ee_org['id'], actor=ACTOR, employee_id=employee['id'],
        recipient_id=agreement['recipient_id'], component_type='agreed_deduction', method='fixed_sum',
        start_date='2026-01-01', monthly_amount='15')
    service.delete_agreement(ee_org['id'], manual_agreement['id'], actor=ACTOR)
    with db.transaction() as tx:
        tx.execute('INSERT INTO payroll_withholding_run_lines '
            '(id,organisation_id,pay_run_id,pay_run_item_id,agreement_id,recipient_id,employee_id,component_type,amount,generated,description) '
            'VALUES (?,?,?,?,?,?,?,?,?,0,?)', ('manual-line', ee_org['id'], run['id'], item['id'],
             manual_agreement['id'], agreement['recipient_id'], employee['id'], 'agreed_deduction', '15.00', 'Manual line'))
    preset = next(row for row in payroll.component_types(ee_org['id']) if row['preset_key'] == 'bailiff')
    updated_run = payroll.update_item(ee_org['id'], run['id'], item['id'], actor=ACTOR, components=[
        {'type_id': preset['id'], 'name': preset['name'], 'amount': '10', 'direction': 'deduction'}])
    updated = next(row for row in updated_run['items'] if row['id'] == item['id'])
    assert any(not component['is_generated'] for component in updated['components'])
    assert len(updated['withholdings']) == 2
    assert any(not line['generated'] and line['amount'] == '15.00' for line in updated['withholdings'])


def test_approval_updates_cap_in_same_transaction_and_closes_agreement(db, ee_org):
    payroll = PayrollService(db)
    employee, service, agreement = setup_agreement(db, ee_org, payroll, monthly_amount='50', total_cap='50')
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    payroll.approve(ee_org['id'], run['id'], actor=ACTOR)
    saved = service.agreements(ee_org['id'])[0]
    assert saved['withheld_to_date'] == 50
    assert saved['active'] == 0
    with db.transaction() as tx:
        approved = payroll._run(tx, ee_org['id'], run['id'])
    assert approved['items'][0]['withholdings'][0]['amount'] == '50.00'


def test_generated_withholding_is_tenant_scoped(db, ee_org, uk_org):
    payroll = PayrollService(db)
    employee, service, agreement = setup_agreement(db, ee_org, payroll, monthly_amount='50')
    assert service.agreements(uk_org['id']) == []
    assert db.rows('SELECT * FROM payroll_withholding_run_lines WHERE organisation_id=?', (uk_org['id'],)) == []
