from payroll import PayrollService
from payroll_contracts import PayrollContractService
from decimal import Decimal
from fastapi.testclient import TestClient
from payroll_payouts import PayoutService


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


def test_run_uses_salary_agreement_effective_in_period(db, ee_org, legacy_payroll):
    legacy_payroll(db, ee_org['id'], name='Agreement selector', gross='2000')
    contracts = PayrollContractService(db)
    contract = contracts.create(ee_org['id'], 'legacy-employee', contract_type='employment',
        start_date='2026-01-01', actor='owner@example.test',
        agreement={'base_pay_type':'monthly', 'rate':'2100', 'fte':'1'})
    changed = contracts.add_agreement(ee_org['id'], contract['id'], start_date='2026-12-01', actor='owner@example.test',
        base_pay_type='monthly', rate='2500', fte='1')
    run = PayrollService(db).create_run(ee_org['id'], period='2026-12', actor='owner@example.test')
    assert Decimal(str(run['items'][0]['gross'])) == Decimal('2500.00')
    assert run['items'][0]['contract_lines'][0]['agreement_id'] == changed['id']
    assert run['items'][0]['contract_lines'][0]['payment_type'] == 10


def test_backfilled_single_employment_contract_keeps_legacy_pay_values(db, ee_org, legacy_payroll):
    from payroll import AMOUNTS
    legacy_payroll(db, ee_org['id'], name='Legacy contract values', gross='2000', fte='0.8')
    with db.transaction() as tx:
        tx.execute("INSERT INTO employees(id,organisation_id,name,gross_salary,fte,created_at) VALUES ('control-employee',?,'Legacy control',2000,0.8,'2026-01-01')",
                   (ee_org['id'],))
        tx.execute("INSERT INTO payroll_contracts(id,organisation_id,employee_id,contract_type,start_date,created_at) VALUES ('contract-legacy-employee',?,'legacy-employee','employment','2026-01-01','2026-01-01')",
                   (ee_org['id'],))
        tx.execute("INSERT INTO payroll_salary_agreements(id,organisation_id,contract_id,start_date,base_pay_type,rate,fte,created_at) VALUES ('agreement-legacy-employee',?,'contract-legacy-employee','2026-01-01','monthly',2000,0.8,'2026-01-01')",
                   (ee_org['id'],))
    run = PayrollService(db).create_run(ee_org['id'], period='2026-11', actor='owner@example.test')
    items = {item['employee_id']: item for item in run['items']}
    fields = ('gross_salary', *AMOUNTS)
    assert {key: items['legacy-employee'][key] for key in fields} == {
        key: items['control-employee'][key] for key in fields}


def test_midmonth_salary_agreement_change_prorates_by_working_days(db, ee_org, legacy_payroll):
    legacy_payroll(db, ee_org['id'], name='Agreement proration', gross='2000')
    contracts = PayrollContractService(db)
    contract = contracts.create(ee_org['id'], 'legacy-employee', contract_type='employment',
        start_date='2026-01-01', actor='owner@example.test',
        agreement={'base_pay_type':'monthly', 'rate':'2000', 'fte':'1'})
    changed = contracts.add_agreement(ee_org['id'], contract['id'], start_date='2026-12-16', actor='owner@example.test',
        base_pay_type='monthly', rate='2400', fte='1')
    run = PayrollService(db).create_run(ee_org['id'], period='2026-12', actor='owner@example.test')
    assert Decimal(str(run['items'][0]['gross'])) == Decimal('2190.48')
    assert {line['agreement_id'] for line in run['items'][0]['contract_lines']} == {
        contract['agreements'][0]['id'], changed['id']}


def test_concurrent_employment_and_board_contracts_create_per_type_tsd_lines(db, ee_org, legacy_payroll):
    legacy_payroll(db, ee_org['id'], name='Two contracts', gross='2000')
    contracts = PayrollContractService(db)
    contracts.create(ee_org['id'], 'legacy-employee', contract_type='employment',
        start_date='2026-01-01', actor='owner@example.test',
        agreement={'base_pay_type':'monthly', 'rate':'2000', 'fte':'1'})
    contracts.create(ee_org['id'], 'legacy-employee', contract_type='board_member',
        start_date='2026-01-01', actor='owner@example.test',
        agreement={'base_pay_type':'monthly', 'rate':'1000', 'fte':'1'})
    payroll = PayrollService(db)
    run = payroll.create_run(ee_org['id'], period='2026-11', actor='owner@example.test')
    assert Decimal(str(run['items'][0]['gross'])) == Decimal('3000.00')
    payroll.approve(ee_org['id'], run['id'], actor='owner@example.test')
    lines = db.rows('SELECT payment_type,amount,ui_employee_base FROM pay_item_tsd_lines WHERE organisation_id=? AND source_kind=? AND source_id=? ORDER BY payment_type',
                    (ee_org['id'], 'pay_run_item', run['items'][0]['id']))
    assert [(line['payment_type'], Decimal(str(line['amount'])), Decimal(str(line['ui_employee_base'])))
            for line in lines] == [(10, Decimal('2000.00'), Decimal('2000.00')),
                                    (21, Decimal('1000.00'), Decimal('0.00'))]


def test_contract_net_advance_proposal_is_deducted_from_salary_payout(db, ee_org, legacy_payroll):
    legacy_payroll(db, ee_org['id'], name='Advance employee', gross='2000')
    PayrollContractService(db).create(ee_org['id'], 'legacy-employee', contract_type='employment',
        start_date='2026-01-01', actor='owner@example.test', monthly_net_advance='300',
        agreement={'base_pay_type':'monthly', 'rate':'2000', 'fte':'1'})
    with db.transaction() as tx:
        tx.execute('UPDATE employees SET iban=?,bank_account_owner=? WHERE organisation_id=? AND id=?',
                   ('EE382200221020145685', 'Advance employee', ee_org['id'], 'legacy-employee'))
    payroll = PayrollService(db)
    run = payroll.create_run(ee_org['id'], period='2026-11', actor='owner@example.test')
    frozen = {key: run['items'][0][key] for key in ('gross','income_tax','social_tax','net')}
    payroll.approve(ee_org['id'], run['id'], actor='owner@example.test')
    advance = PayoutService(db).list(ee_org['id'], run_id=run['id'])[0]
    assert advance['payout_type'] == 'advance' and advance['payout_date'] == '2026-11-15'
    assert Decimal(str(advance['lines'][0]['amount'])) == Decimal('300.00')
    asset = db.one("SELECT id FROM accounts WHERE organisation_id=? AND account_type='Asset' AND active=1 ORDER BY code LIMIT 1", (ee_org['id'],))
    with db.transaction() as tx:
        tx.execute("INSERT INTO bank_accounts(id,organisation_id,ledger_account_id,name,currency,iban_masked,iban,bic) VALUES ('advance-bank',?,?,?,'EUR','********5685',?,'HABAEE2X')",
                   (ee_org['id'], asset['id'], 'Salary bank', 'EE382200221020145685'))
    payouts = PayoutService(db)
    payouts.mark_paid(ee_org['id'], advance['id'], 'advance-bank', actor='owner@example.test')
    salary = payouts.create(ee_org['id'], run['id'], actor='owner@example.test')
    assert Decimal(str(salary['lines'][0]['amount'])) == Decimal(str(frozen['net'])) - Decimal('300.00')
    after = payroll.runs(ee_org['id'])[0]['items'][0]
    assert {key: after[key] for key in frozen} == frozen


def test_contract_api_enforces_tenant_roles_and_csrf(db, ee_org, monkeypatch):
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    from api_app import api
    client = TestClient(api)
    root = f"/organisations/{ee_org['id']}"
    headers = {'X-Test-User': 'owner@example.test'}
    employee = client.post(root + '/employees', headers=headers, json={'name': 'API employee', 'gross_salary': '2000'}).json()
    payload = {'contract_type': 'employment', 'start_date': '2026-01-01',
               'agreement': {'base_pay_type': 'monthly', 'rate': '2000'},
               'position': {'position': 'Accountant'}}
    assert client.get(root + f"/employees/{employee['id']}/contracts", headers=headers).status_code == 200
    created = client.post(root + f"/employees/{employee['id']}/contracts", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    assert created.json()['contract_type'] == 'employment'
    assert client.get(root + f"/employees/{employee['id']}/contracts", headers={'X-Test-User': 'outsider@example.test'}).status_code == 403
    assert client.post(root + f"/employees/{employee['id']}/contracts", headers={'X-Test-User': 'viewer@example.test'}, json=payload).status_code == 403
