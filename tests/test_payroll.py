from decimal import Decimal
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from core_utils import money
from ledger import LedgerService
from payroll import PayrollConflict, PayrollService, calculate_pay

ACTOR = 'owner@example.test'


def employee(service, org, **kwargs):
    return service.save_employee(org['id'], actor=ACTOR, **(dict(name='Synthetic Employee', gross_salary='2000') | kwargs))


@pytest.mark.parametrize('exemption,tax,net', [(False, '424.16', '1503.84'), (True, '270.16', '1657.84')])
def test_worked_examples(exemption, tax, net):
    result = calculate_pay(dict(gross_salary='2000', funded_pension_percent=2, board_member=False, apply_tax_free_minimum=exemption))
    assert result['funded_pension'] == Decimal('40.00')
    assert result['ui_employee'] == Decimal('32.00')
    assert result['income_tax'] == Decimal(tax)
    assert result['net'] == Decimal(net)
    assert result['employer_cost'] == Decimal('2676.00')
    assert result['withholding_total'] == result['gross']-result['net']


def test_board_and_rounding(db, ee_org):
    service = PayrollService(db)
    e = employee(service, ee_org, board_member=True)
    result = calculate_pay(e)
    assert e['funded_pension_percent'] == '0.00'
    assert result['ui_employee'] == result['ui_employer'] == result['funded_pension'] == 0
    assert result['income_tax'] == Decimal('440.00')
    e = employee(service, ee_org, name='Board pension', board_member=True, funded_pension_percent=6, gross_salary='1000.25')
    assert calculate_pay(e)['funded_pension'] == Decimal('60.02')
    assert calculate_pay(e)['social_tax'] == Decimal('330.08')


@pytest.mark.parametrize('period,salary,valid', [('2026-03','886',True), ('2026-03','885.99',False), ('2026-04','946',True), ('2026-04','945.99',False)])
def test_minimum_wage(db, ee_org, period, salary, valid):
    service = PayrollService(db)
    employee(service, ee_org, gross_salary=salary)
    if valid:
        assert service.create_run(ee_org['id'], period=period, actor=ACTOR)['status'] == 'Draft'
    else:
        with pytest.raises(ValueError, match='at least EUR'):
            service.create_run(ee_org['id'], period=period, actor=ACTOR)
        assert service.runs(ee_org['id']) == []


def test_workflow_snapshot_balance_pdf_and_delete(db, ee_org):
    service = PayrollService(db)
    e = employee(service, ee_org, apply_tax_free_minimum=True)
    employee(service, ee_org, name='Board', board_member=True, gross_salary='500')
    run = service.create_run(ee_org['id'], period='2026-07', actor=ACTOR)
    service.save_employee(ee_org['id'], employee_id=e['id'], actor=ACTOR, gross_salary='3000', name='Changed', active=False)
    with pytest.raises(PayrollConflict):
        service.create_run(ee_org['id'], period='2026-07', actor=ACTOR)
    run = service.approve(ee_org['id'], run['id'], actor=ACTOR)
    assert run['status'] == 'Approved'
    original = next(i for i in run['items'] if i['employee_id'] == e['id'])
    assert original['employee_name'] == 'Synthetic Employee'
    assert original['gross'] == '2000.00'
    ledger = LedgerService(db)
    assert sum((r['balance'] for r in ledger.trial_balance(ee_org['id'], start='2026-07-01', end='2026-07-31')), Decimal(0)) == 0
    assert ledger.profit_and_loss(ee_org['id'], start='2026-07-01', end='2026-07-31')['expenses'] == money(run['total_employer_cost'])
    assert db.scalar("SELECT COUNT(*) FROM posting_batches WHERE organisation_id=? AND voucher_type='payroll'", (ee_org['id'],)) == 1
    for action in (service.approve, service.delete_run):
        with pytest.raises(PayrollConflict):
            action(ee_org['id'], run['id'], actor=ACTOR)
    pdf = service.payslips_pdf(ee_org['id'], run['id'])
    assert pdf.startswith(b'%PDF')
    import pypdf
    reader = pypdf.PdfReader(BytesIO(pdf))
    assert len(reader.pages) == 2
    text = '\n'.join(p.extract_text() for p in reader.pages)
    assert '1657.84' in text and '342.16' in text and 'Kinnipeetud summad kokku' in text
    draft = service.create_run(ee_org['id'], period='2026-08', actor=ACTOR)
    service.delete_run(ee_org['id'], draft['id'], actor=ACTOR)
    assert len(service.runs(ee_org['id'])) == 1


def test_locked_period_rolls_back(db, ee_org):
    service = PayrollService(db)
    employee(service, ee_org)
    run = service.create_run(ee_org['id'], period='2026-07', actor=ACTOR)
    with db.transaction() as tx:
        tx.execute("UPDATE fiscal_periods SET status='Locked' WHERE organisation_id=? AND code='2026-07'", (ee_org['id'],))
    with pytest.raises(ValueError, match='locked'):
        service.approve(ee_org['id'], run['id'], actor=ACTOR)
    saved = service.runs(ee_org['id'])[0]
    assert saved['status'] == 'Draft' and saved['posted_batch_id'] is None and saved['approved_at'] is None
    assert db.scalar('SELECT COUNT(*) FROM posting_batches WHERE organisation_id=?', (ee_org['id'],)) == 0


def test_tenant_isolation(db, ee_org, uk_org):
    service = PayrollService(db)
    e = employee(service, ee_org)
    run = service.create_run(ee_org['id'], period='2026-07', actor=ACTOR)
    for action in (service.approve, service.delete_run):
        with pytest.raises(KeyError):
            action(uk_org['id'], run['id'], actor=ACTOR)
    with pytest.raises(KeyError):
        service.payslips_pdf(uk_org['id'], run['id'])
    from organisations import OrganisationService
    other = OrganisationService(db).create(name='Other EE', country_code='EE', entity_type='EE_OU', owner_email=ACTOR)
    with pytest.raises(KeyError):
        service.save_employee(other['id'], employee_id=e['id'], actor=ACTOR, name='Intruder')
    assert service.employees(other['id']) == []


def test_api(db, ee_org, monkeypatch):
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    from api_app import api
    client = TestClient(api)
    root = f"/organisations/{ee_org['id']}"
    headers = {'X-Test-User': ACTOR}
    other = {'X-Test-User': 'intruder@example.test'}
    assert client.get(root+'/employees').status_code == 401
    assert client.get(root+'/employees', headers=other).status_code == 403
    response = client.post(root+'/employees', headers=headers, json={'name':'API employee','gross_salary':'2000'})
    assert response.status_code == 201, response.text
    eid = response.json()['id']
    assert client.patch(root+'/employees/'+eid, headers=headers, json={'apply_tax_free_minimum':True}).status_code == 200
    for patch in ({'name':None}, {'gross_salary':None}, {'funded_pension_percent':3}, {'active':None}):
        assert client.patch(root+'/employees/'+eid, headers=headers, json=patch).status_code == 422
    run = client.post(root+'/pay-runs', headers=headers, json={'period':'2026-07'})
    assert run.status_code == 201, run.text
    rid = run.json()['id']
    assert run.json()['items'][0]['net'] == '1657.84'
    assert client.post(root+'/pay-runs', headers=headers, json={'period':'2026-07'}).status_code == 409
    assert client.post(root+f'/pay-runs/{rid}/approve', headers=headers).status_code == 200
    assert client.post(root+f'/pay-runs/{rid}/approve', headers=headers).status_code == 409
    assert client.delete(root+f'/pay-runs/{rid}', headers=headers).status_code == 409
    assert client.get(root+f'/pay-runs/{rid}/payslips.pdf', headers=headers).status_code == 200
    from web_app import app
    mounted = TestClient(app)
    assert mounted.get('/api'+root+f'/pay-runs/{rid}/payslips.pdf', headers=headers).content.startswith(b'%PDF')
    assert client.get(root+f'/pay-runs/{rid}/payslips.pdf', headers=other).status_code == 403
    assert client.get(root+'/pay-runs', headers=headers).json()[0]['items']
    draft = client.post(root+'/pay-runs', headers=headers, json={'period':'2026-08'}).json()
    assert client.delete(root+'/pay-runs/'+draft['id'], headers=headers).status_code == 204
    assert client.post(root+'/pay-runs', headers=headers, json={'period':'2027-01'}).status_code == 422
    client.patch(root+'/employees/'+eid, headers=headers, json={'gross_salary':'945'})
    assert client.post(root+'/pay-runs', headers=headers, json={'period':'2026-08'}).status_code == 422


def test_seed_repeatability_and_migration(db, monkeypatch):
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    from seed import seed_demo
    uk, ee = seed_demo()
    before = PayrollService(db).runs(ee['id'])
    assert len(before) == 4
    assert {r['period']: r['status'] for r in before} == {
        '2026-07': 'Approved', '2026-08': 'Approved', '2026-09': 'Approved', '2026-10': 'Draft'}
    assert len(PayrollService(db).employees(ee['id'])) == 6
    assert db.scalar('SELECT COUNT(*) FROM employees WHERE organisation_id=?', (uk['id'],)) == 0
    assert db.migrate() == []
    seed_demo()
    assert PayrollService(db).runs(ee['id']) == before


def test_existing_books_upgrade(tmp_path, monkeypatch):
    import database
    from organisations import OrganisationService
    migration_root = tmp_path/'old_migrations'
    (migration_root/'sqlite').mkdir(parents=True)
    for path in (database.MIGRATIONS/'sqlite').glob('000[1-4]*.sql'):
        (migration_root/'sqlite'/path.name).write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
    original = database.MIGRATIONS
    monkeypatch.setattr(database, 'MIGRATIONS', migration_root)
    db = database.Database(path=str(tmp_path/'upgrade.sqlite'))
    db.migrate()
    org = OrganisationService(db).create(name='Existing books', country_code='EE', entity_type='EE_OU', owner_email=ACTOR)
    with db.transaction() as tx:
        tx.execute("DELETE FROM accounts WHERE organisation_id=? AND system_role LIKE 'PAYROLL_%'", (org['id'],))
    before = db.rows('SELECT * FROM accounts WHERE organisation_id=? ORDER BY code', (org['id'],))
    monkeypatch.setattr(database, 'MIGRATIONS', original)
    assert db.migrate() == ['0005_payroll', '0006_automation']
    after = db.rows("SELECT * FROM accounts WHERE organisation_id=? AND system_role NOT LIKE 'PAYROLL_%' ORDER BY code", (org['id'],))
    assert before == after
    assert len(db.rows("SELECT * FROM accounts WHERE organisation_id=? AND system_role LIKE 'PAYROLL_%'", (org['id'],))) == 7


def test_concurrent_approvals_post_once(db, ee_org):
    from concurrent.futures import ThreadPoolExecutor
    service = PayrollService(db)
    employee(service, ee_org)
    run = service.create_run(ee_org['id'], period='2026-07', actor=ACTOR)
    def approve():
        try:
            service.approve(ee_org['id'], run['id'], actor=ACTOR)
            return 'approved'
        except PayrollConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: approve(), range(2))) == ['approved', 'conflict']
    assert db.scalar("SELECT COUNT(*) FROM posting_batches WHERE organisation_id=? AND voucher_type='payroll'", (ee_org['id'],)) == 1


def test_payslip_unicode_localization_and_fallback(db, ee_org, monkeypatch):
    import documents
    from pypdf import PdfReader
    with db.transaction() as tx:
        tx.execute('UPDATE organisations SET name=? WHERE id=?', ('Põhjatäht Teenused OÜ', ee_org['id']))
    service = PayrollService(db)
    employee(service, ee_org, name='Jüri Õun')
    run = service.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    org = db.one('SELECT * FROM organisations WHERE id=?', (ee_org['id'],))
    def extracted(pdf):
        return PdfReader(BytesIO(pdf)).pages[0].extract_text()
    text = extracted(service.payslips_pdf(ee_org['id'], run['id']))
    if documents.locate_pdf_font():
        assert 'Põhjatäht Teenused OÜ' in text and 'Jüri Õun' in text
        assert 'õ' in text
    assert '?' not in text
    for label in ('PALGALEHT 2026-10', '12345678', 'TSD', 'UAT', '10.', '2026-10'):
        assert label in text
    english = extracted(documents.payroll_pdf(dict(org, country_code='UK'), run))
    assert 'PAYSLIP 2026-10' in english and 'Total employee withholdings' in english
    monkeypatch.setattr(documents, 'locate_pdf_font', lambda bold=False: None)
    fallback = extracted(documents.payroll_pdf(org, run))
    assert 'Pohjataht Teenused OU' in fallback and '?' not in fallback


def test_demo_documents_balances_matches_and_repeatability(db, monkeypatch):
    from banking import BankingService
    from seed import seed_demo
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    orgs = seed_demo()
    tables = ('contacts', 'bank_accounts', 'tax_codes', 'invoices', 'invoice_lines', 'bills', 'bill_lines', 'bank_transactions',
              'payments', 'payment_allocations', 'posting_batches', 'gl_entries', 'pay_runs', 'pay_run_items')
    for org in orgs:
        oid = org['id']
        ee = org['country_code'] == 'EE'
        assert db.scalar('SELECT name FROM bank_accounts WHERE organisation_id=?', (oid,)) == (
            'Arvelduskonto' if ee else 'Operating account')
        contact_names = {r['name'] for r in db.rows('SELECT name FROM contacts WHERE organisation_id=?', (oid,))}
        assert ('Sinilille Teenused OÜ' if ee else 'Brightline Media Ltd') in contact_names
        assert ('Männi Pilveteenused OÜ' if ee else 'Pine Cloud Ltd') in contact_names
        assert not any('Synthetic' in name or 'Acme' in name for name in contact_names)
        assert {r['reference'] for r in db.rows('SELECT reference FROM invoices WHERE organisation_id=?', (oid,))} == {
            f'SALES-2026-{i:03d}' for i in range(1, 19)} | (set() if ee else {'AUTOMATION-WILLOW-TEMPLATE'})
        assert db.rows('SELECT status FROM invoices WHERE organisation_id=? AND reference=?',
                       (oid, 'AUTOMATION-WILLOW-TEMPLATE')) == ([] if ee else [{'status': 'Draft'}])
        assert {r['supplier_number'] for r in db.rows('SELECT supplier_number FROM bills WHERE organisation_id=?', (oid,))} == {
            f'SUP-2026-{i:03d}' for i in range(1, 9)}
        assert all(r['external_id'].startswith(f"BANK-{org['country_code']}-") for r in db.rows(
            'SELECT external_id FROM bank_transactions WHERE organisation_id=?', (oid,)))
        for table, expected in [('invoices', 18 if ee else 19), ('bills', 8), ('bank_transactions', 28), ('contacts', 10)]:
            assert db.scalar(f'SELECT COUNT(*) FROM {table} WHERE organisation_id=?', (oid,)) == expected
        assert {r['status'] for r in db.rows('SELECT status FROM invoices WHERE organisation_id=?', (oid,))} == {'Issued', 'Part Paid', 'Paid'} | (set() if ee else {'Draft'})
        assert {r['status'] for r in db.rows('SELECT status FROM bills WHERE organisation_id=?', (oid,))} == {'Approved', 'Part Paid', 'Paid', 'In Review'}
        assert db.scalar("SELECT COUNT(*) FROM invoices WHERE organisation_id=? AND due_date='2026-09-10' AND status='Issued'", (oid,)) == 1
        pending = db.rows("SELECT * FROM bank_transactions WHERE organisation_id=? AND status!='Reconciled'", (oid,))
        matches = [match for row in pending for match in BankingService(db).suggest(row['id'])]
        assert sum('document number in reference' in match['reasons'] for match in matches) >= 6
        assert sum((r['balance'] for r in LedgerService(db).trial_balance(oid, start='2026-01-01', end='2026-12-31')), Decimal(0)) == 0
    names = {e['name'] for e in PayrollService(db).employees(orgs[1]['id'])}
    assert names == {'Jaan Tamm', 'Kati Kask', 'Liis Kuusk', 'Mari Maasikas', 'Peeter Saar', 'Toomas Oja'}
    before = {table: db.rows(f'SELECT * FROM {table} ORDER BY id') for table in tables}
    seed_demo()
    assert before == {table: db.rows(f'SELECT * FROM {table} ORDER BY id') for table in tables}
