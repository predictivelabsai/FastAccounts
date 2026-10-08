"""Part-time, hourly, II pillar 0% and the 2026 social tax minimum (migration 0006)."""
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ledger import LedgerService
from payroll import (SOCIAL_TAX_MINIMUM_EXEMPTION_LABELS, SOCIAL_TAX_MINIMUM_EXEMPTIONS,
                     PayrollService, calculate_pay)

ACTOR = 'owner@example.test'
FIXTURE = json.loads((Path(__file__).parent / 'fixtures' / 'ee_sample_employees.json').read_text(encoding='utf-8'))
CHECKED = ('gross', 'funded_pension', 'ui_employee', 'income_tax', 'net', 'social_tax',
           'social_tax_base', 'ui_employer', 'employer_cost')


def fixture_employee(row):
    """Map a FastHRM sample row onto FastAccounts employee fields."""
    board = row['contract_type'] == 'board_member'
    data = dict(name=f"{row['first_name']} {row['last_name']}", personal_id=row['personal_code'], email=row['email'],
                funded_pension_percent=row['funded_pension_percent'], apply_tax_free_minimum=row['apply_basic_exemption'],
                pay_basis='board_fee' if board else row['pay_basis'], employment_start_date=row['start_date'])
    if row['pay_basis'] == 'hourly':
        data['hourly_rate'] = row['hourly_rate']
    else:
        data['gross_salary'] = row['monthly_gross']
    if row['fte'] and not board:
        data['fte'] = row['fte']
    return data


def employee(service, org, **kwargs):
    return service.save_employee(org['id'], actor=ACTOR, **(dict(name='Synthetic Employee', gross_salary='2000') | kwargs))


@pytest.mark.parametrize('row', FIXTURE['employees'], ids=lambda r: r['employee_code'])
def test_seven_sample_employees_match_october_expectations(db, ee_org, row):
    service = PayrollService(db)
    saved = service.save_employee(ee_org['id'], actor=ACTOR, **fixture_employee(row))
    expected = row['expected_2026_10']
    hours = {saved['id']: expected['hours']} if saved['pay_basis'] == 'hourly' else None
    item = service.create_run(ee_org['id'], period='2026-10', actor=ACTOR, hours=hours)['items'][0]
    for key in CHECKED:
        assert Decimal(item[key]) == Decimal(expected[key]), key
    assert Decimal(item['tax_free_minimum']) == Decimal(expected['basic_exemption_used'])
    assert Decimal(item['withholding_total']) == Decimal(item['gross']) - Decimal(item['net'])
    assert Decimal(item['employer_cost']) == Decimal(item['gross']) + Decimal(item['social_tax']) + Decimal(item['ui_employer'])


def test_sample_run_totals_and_posting(db, ee_org):
    service = PayrollService(db)
    for row in FIXTURE['employees']:
        service.save_employee(ee_org['id'], actor=ACTOR, **fixture_employee(row))
    hourly = {e['id']: '176' for e in service.employees(ee_org['id']) if e['pay_basis'] == 'hourly'}
    run = service.create_run(ee_org['id'], period='2026-10', actor=ACTOR, hours=hourly)
    assert (run['total_gross'], run['total_net'], run['total_employer_cost']) == ('16254.00', '12480.00', '21797.23')
    liis = next(i for i in run['items'] if i['employee_name'] == 'Liis Kuusk')
    assert (liis['social_tax_base'], liis['social_tax'], liis['social_tax_minimum_topup']) == ('886.00', '292.38', '61.38')
    toomas = next(i for i in run['items'] if i['employee_name'] == 'Toomas Rebane')
    assert toomas['social_tax_minimum_exemption'] == 'board_member' and toomas['pay_basis'] == 'board_fee'
    peeter = next(i for i in run['items'] if i['employee_name'] == 'Peeter Oja')
    assert (peeter['hours'], peeter['hourly_rate'], peeter['gross']) == ('176.00', '8.00', '1408.00')
    run = service.approve(ee_org['id'], run['id'], actor=ACTOR)
    lines = db.rows("SELECT a.system_role, e.debit, e.credit, e.memo FROM gl_entries e JOIN accounts a ON a.id=e.account_id "
                    "WHERE e.posting_batch_id=?", (run['posted_batch_id'],))
    social = sum((Decimal(str(r['debit'])) for r in lines if r['system_role'] == 'PAYROLL_SOCIAL'), Decimal(0))
    assert social == sum((Decimal(i['social_tax']) for i in run['items']), Decimal(0))
    topup = [r for r in lines if r['memo'] == 'Sotsiaalmaksu miinimumkohustuse lisamakse 2026-10']
    assert sorted((r['system_role'], Decimal(str(r['debit'])), Decimal(str(r['credit']))) for r in topup) == [
        ('PAYROLL_EMPLOYER_TAX', Decimal('0'), Decimal('61.38')), ('PAYROLL_SOCIAL', Decimal('61.38'), Decimal('0'))]
    ledger = LedgerService(db)
    assert sum((r['balance'] for r in ledger.trial_balance(ee_org['id'], start='2026-10-01', end='2026-10-31')), Decimal(0)) == 0
    assert ledger.profit_and_loss(ee_org['id'], start='2026-10-01', end='2026-10-31')['expenses'] == Decimal('21797.23')
    from pypdf import PdfReader
    from io import BytesIO
    text = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(service.payslips_pdf(ee_org['id'], run['id']))).pages)
    assert 'Sotsiaalmaksu miinimumkohustuse lisamakse' in text and '61.38' in text and 'Töökoormus (FTE): 0.5' in text
    assert 'Tunnitasu määr: 8.00 EUR × 176.00 tunnid' in text


@pytest.mark.parametrize('period,fte,salary,valid', [
    ('2026-04', '0.5', '473.00', True), ('2026-04', '0.5', '472.99', False),
    ('2026-03', '0.5', '443.00', True), ('2026-03', '0.5', '442.99', False),
    ('2026-10', '0.25', '236.50', True), ('2026-10', '1', '945.99', False)])
def test_part_time_minimum_wage_is_pro_rated(db, ee_org, period, fte, salary, valid):
    service = PayrollService(db)
    employee(service, ee_org, gross_salary=salary, fte=fte)
    if valid:
        assert service.create_run(ee_org['id'], period=period, actor=ACTOR)['status'] == 'Draft'
    else:
        with pytest.raises(ValueError, match='gross salary must be at least EUR'):
            service.create_run(ee_org['id'], period=period, actor=ACTOR)


@pytest.mark.parametrize('period,rate,valid', [('2026-04', '5.67', True), ('2026-04', '5.66', False),
                                               ('2026-03', '5.31', True), ('2026-03', '5.30', False)])
def test_hourly_minimum_rate(db, ee_org, period, rate, valid):
    service = PayrollService(db)
    e = employee(service, ee_org, pay_basis='hourly', hourly_rate=rate, gross_salary=None)
    assert e['gross_salary'] is None and e['pay_basis'] == 'hourly'
    if valid:
        item = service.create_run(ee_org['id'], period=period, actor=ACTOR, hours={e['id']: '160'})['items'][0]
        assert Decimal(item['gross']) == (Decimal(rate) * 160).quantize(Decimal('0.01'))
    else:
        with pytest.raises(ValueError, match='hourly rate must be at least EUR'):
            service.create_run(ee_org['id'], period=period, actor=ACTOR, hours={e['id']: '160'})


@pytest.mark.parametrize('hours,message', [(None, 'enter hours worked'), ('0', 'hours must be a positive'),
                                           ('10.555', 'hours must be a positive'), ('745', 'hours must be a positive'),
                                           ('abc', 'hours must be a positive')])
def test_hourly_requires_valid_hours(db, ee_org, hours, message):
    service = PayrollService(db)
    e = employee(service, ee_org, pay_basis='hourly', hourly_rate='8')
    with pytest.raises(ValueError, match=message):
        service.create_run(ee_org['id'], period='2026-10', actor=ACTOR, hours={e['id']: hours} if hours else {})
    assert service.runs(ee_org['id']) == []


def test_ii_pillar_zero_for_any_employee_and_validation(db, ee_org):
    service = PayrollService(db)
    e = employee(service, ee_org, funded_pension_percent=0)
    assert e['funded_pension_percent'] == '0.00' and not e['board_member']
    assert calculate_pay(e)['funded_pension'] == 0
    for bad, message in [(dict(funded_pension_percent=3), '0, 2, 4 or 6'), (dict(fte='0'), 'Work-time fraction'),
                         (dict(fte='1.5'), 'Work-time fraction'), (dict(pay_basis='weekly'), 'Pay basis'),
                         (dict(pay_basis='hourly'), 'Hourly rate must be positive'),
                         (dict(social_tax_minimum_exemption='lottery'), 'Unknown social tax minimum exemption'),
                         (dict(social_tax_minimum_exemption='multiple_employers', apply_tax_free_minimum=True), 'multiple-employers'),
                         (dict(employment_start_date='2026-10-10', employment_end_date='2026-10-01'), 'Employment dates'),
                         (dict(employment_start_date='10.10.2026'), 'Employment dates'),
                         (dict(pay_basis='monthly', board_member=True), 'Board members')]:
        with pytest.raises(ValueError, match=message):
            employee(service, ee_org, name='Invalid', **bad)
    board = employee(service, ee_org, name='Board', board_member=True)
    assert board['pay_basis'] == 'board_fee'
    switched = service.save_employee(ee_org['id'], employee_id=board['id'], actor=ACTOR, board_member=False)
    assert switched['pay_basis'] == 'monthly' and not switched['board_member']
    hourly = service.save_employee(ee_org['id'], employee_id=e['id'], actor=ACTOR, pay_basis='hourly', hourly_rate='7.5')
    assert hourly['gross_salary'] is None and hourly['hourly_rate'] == '7.50'
    back = service.save_employee(ee_org['id'], employee_id=e['id'], actor=ACTOR, pay_basis='monthly', gross_salary='1200')
    assert back['hourly_rate'] is None and back['gross_salary'] == '1200.00'


def test_social_tax_minimum_rules():
    base = dict(funded_pension_percent=2, apply_tax_free_minimum=False, board_member=False)
    low = calculate_pay(base | dict(gross_salary='500', fte='0.5'), period='2026-10')
    assert (low['social_tax_base'], low['social_tax'], low['social_tax_minimum_topup']) == (
        Decimal('886.00'), Decimal('292.38'), Decimal('127.38'))
    assert low['employer_cost'] == Decimal('500') + Decimal('292.38') + Decimal('4.00')
    for reason in SOCIAL_TAX_MINIMUM_EXEMPTIONS:
        exempt = calculate_pay(base | dict(gross_salary='500', social_tax_minimum_exemption=reason), period='2026-10')
        assert exempt['social_tax'] == Decimal('165.00') and exempt['social_tax_minimum_topup'] == 0
        assert exempt['social_tax_minimum_exemption'] == reason
    board = calculate_pay(base | dict(gross_salary='300', board_member=True), period='2026-10')
    assert board['social_tax'] == Decimal('99.00') and board['social_tax_minimum_exemption'] == 'board_member'
    # Employment starting 16.10: minimum base 886 / 31 x 16 = 457.29 (SMS § 2 lg 3).
    joiner = calculate_pay(base | dict(gross_salary='400', employment_start_date='2026-10-16'), period='2026-10')
    assert (joiner['social_tax_base'], joiner['social_tax']) == (Decimal('457.29'), Decimal('150.91'))
    leaver = calculate_pay(base | dict(gross_salary='20', employment_end_date='2026-10-01'), period='2026-10')
    assert leaver['social_tax_base'] == Decimal('28.58')
    assert set(SOCIAL_TAX_MINIMUM_EXEMPTION_LABELS) == set(SOCIAL_TAX_MINIMUM_EXEMPTIONS) | {'board_member'}


def test_employees_outside_employment_dates_are_not_paid(db, ee_org):
    service = PayrollService(db)
    employee(service, ee_org, name='Current')
    employee(service, ee_org, name='Left', employment_end_date='2026-09-30')
    employee(service, ee_org, name='Future', employment_start_date='2026-11-01')
    run = service.create_run(ee_org['id'], period='2026-10', actor=ACTOR)
    assert [i['employee_name'] for i in run['items']] == ['Current']


def test_api_hourly_employee_and_hours(db, ee_org, monkeypatch):
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    from api_app import api
    client = TestClient(api)
    root = f"/organisations/{ee_org['id']}"
    headers = {'X-Test-User': ACTOR}
    created = client.post(root+'/employees', headers=headers, json={
        'name': 'Hourly API', 'pay_basis': 'hourly', 'hourly_rate': '8.00', 'apply_tax_free_minimum': True,
        'social_tax_minimum_exemption': None, 'employment_start_date': None})
    assert created.status_code == 201, created.text
    part = client.post(root+'/employees', headers=headers, json={
        'name': 'Part-time API', 'gross_salary': '700', 'fte': '0.5', 'funded_pension_percent': '0',
        'apply_tax_free_minimum': True})
    assert part.status_code == 201, part.text
    assert part.json()['fte'] == '0.5'
    assert client.post(root+'/employees', headers=headers, json={'name': 'Bad', 'gross_salary': '900', 'fte': '2'}).status_code == 422
    missing = client.post(root+'/pay-runs', headers=headers, json={'period': '2026-10'})
    assert missing.status_code == 422 and 'Hourly API: enter hours worked' in missing.text
    run = client.post(root+'/pay-runs', headers=headers, json={'period': '2026-10', 'hours': {created.json()['id']: '176'}})
    assert run.status_code == 201, run.text
    items = {i['employee_name']: i for i in run.json()['items']}
    assert items['Hourly API']['net'] == '1212.70'
    assert items['Part-time API']['social_tax'] == '292.38' and items['Part-time API']['employer_cost'] == '997.98'


def test_existing_payroll_upgrades_to_0006(tmp_path, monkeypatch):
    import database
    from organisations import OrganisationService
    root = tmp_path/'old'
    (root/'sqlite').mkdir(parents=True)
    for path in (database.MIGRATIONS/'sqlite').glob('000[1-5]*.sql'):
        (root/'sqlite'/path.name).write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
    original = database.MIGRATIONS
    monkeypatch.setattr(database, 'MIGRATIONS', root)
    db = database.Database(path=str(tmp_path/'upgrade.sqlite'))
    db.migrate()
    org = OrganisationService(db).create(name='Old payroll OÜ', country_code='EE', entity_type='EE_OU', owner_email=ACTOR)
    with db.transaction() as tx:
        tx.execute("INSERT INTO employees(id,organisation_id,name,gross_salary,funded_pension_percent,board_member,created_at) "
                   "VALUES ('e1',?,'Old Board',1500,0,1,'2026-01-01'),('e2',?,'Old Staff',900,2,0,'2026-01-01')", (org['id'], org['id']))
        tx.execute("INSERT INTO pay_runs(id,organisation_id,period,total_gross,total_net,total_employer_cost,created_by,created_at) "
                   "VALUES ('r1',?,'2026-03',900,700,1204,'x','2026-03-31')", (org['id'],))
        tx.execute("INSERT INTO pay_run_items(id,pay_run_id,organisation_id,employee_id,employee_name,gross_salary,board_member,"
                   "funded_pension_percent,gross,funded_pension,ui_employee,tax_free_minimum,income_tax,net,withholding_total,"
                   "social_tax,ui_employer,employer_cost) VALUES ('i1','r1',?,'e2','Old Staff',900,0,2,900,18,14.4,0,191.86,"
                   "675.74,224.26,297,7.2,1204.2)", (org['id'],))
    monkeypatch.setattr(database, 'MIGRATIONS', original)
    assert db.migrate() == ['0006_payroll_part_time_hourly', '0007_automation', '0008_import_staging']
    assert db.rows('PRAGMA foreign_key_check') == []
    service = PayrollService(db)
    employees = {e['name']: e for e in service.employees(org['id'])}
    assert employees['Old Board']['pay_basis'] == 'board_fee' and employees['Old Staff']['pay_basis'] == 'monthly'
    assert employees['Old Staff']['fte'] == '1' and employees['Old Staff']['gross_salary'] == '900.00'
    item = service.runs(org['id'])[0]['items'][0]
    assert (item['social_tax_base'], item['social_tax_minimum_topup'], item['pay_basis']) == ('900.00', '0.00', 'monthly')
    service.save_employee(org['id'], employee_id='e2', actor=ACTOR, funded_pension_percent=0)


def test_new_payroll_labels_are_translated():
    from web import i18n
    et, en = i18n.catalog('et')['workspace'], i18n.catalog('en')['workspace']
    keys = ['Pay basis', 'Hourly pay', 'Work-time fraction (FTE)', 'Hours worked', 'Part-time',
            'Social tax minimum top-up', 'Social tax minimum exemption', 'gross salary must be at least',
            'enter hours worked', *SOCIAL_TAX_MINIMUM_EXEMPTION_LABELS.values()]
    for key in keys:
        assert en[key] == key and et[key] and et[key] != key, key
    assert et['Part-time'] == 'Osakoormus' and et['Hourly pay'] == 'Tunnitasu'
    for lang in ('lv', 'lt'):
        assert all(key in i18n.catalog(lang)['workspace'] for key in keys)


def test_sample_payroll_demo_seed(db, monkeypatch):
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    from seed import SAMPLE_PAYROLL_ORG, seed_demo
    seed_demo()
    org = db.one('SELECT * FROM organisations WHERE name=?', (SAMPLE_PAYROLL_ORG,))
    service = PayrollService(db)
    assert len(service.employees(org['id'])) == 7
    runs = {r['period']: r for r in service.runs(org['id'])}
    assert {p: r['status'] for p, r in runs.items()} == {'2026-09': 'Approved', '2026-10': 'Draft'}
    assert (runs['2026-10']['total_net'], runs['2026-10']['total_employer_cost']) == ('12480.00', '21797.23')
    before = service.runs(org['id'])
    seed_demo()
    assert service.runs(org['id']) == before
