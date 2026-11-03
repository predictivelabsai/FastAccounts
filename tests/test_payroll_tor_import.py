from payroll_tor_import import TORImportService, parse_tor_csv
from core_utils import parse_decimal_ee
from decimal import Decimal
import pytest


@pytest.mark.parametrize(("raw", "expected"), [
    ("1234.56", "1234.56"), ("1234,56", "1234.56"),
    ("1 234,56", "1234.56"), ("1\u00a0234,56", "1234.56"),
    ("1\u202f234,56", "1234.56"), ("1.234,56", "1234.56"),
    ("1,234.56", "1234.56"), (" 1 234,56 EUR ", "1234.56"),
    ("1234,56 €", "1234.56"),
    ("0,75", "0.75"),
])
def test_estonian_decimal_parser(raw, expected):
    assert parse_decimal_ee(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["", "1,2,3", "12abc", "1.234.56 EURx"])
def test_estonian_decimal_parser_rejects_garbage(raw):
    with pytest.raises(ValueError, match="Invalid decimal value"):
        parse_decimal_ee(raw)


def test_tor_semicolon_decimal_comma_and_estonian_names():
    content = ("Isikukood;Nimi;Alguskuupäev;Töölepingu liik;Koormus\n"
               "49001010018;Õnne Ülemõisa;2026-01-01;Tööleping;0,75\n"
               "49001010019;Šarlota Žukova;2026-01-01;Tööleping;0,5\n").encode("utf-8-sig")
    rows = parse_tor_csv(content)
    assert [(row["name"], row["fte"]) for row in rows] == [
        ("Õnne Ülemõisa", "0.75"), ("Šarlota Žukova", "0.5")]


def test_tor_reads_windows_1257_csv():
    content = "Isikukood;Nimi;Alguskuupäev;Töölepingu liik\n49001010018;Õnne Ülemõisa;2026-01-01;Tööleping\n".encode("cp1257")
    assert parse_tor_csv(content)[0]["name"] == "Õnne Ülemõisa"


def test_tor_header_aliases_errors_and_decimal_workload():
    content = ('Isikukood,Nimi,Alguskuupäev,Lõppkuupäev,Töölepingu liik,Ametikoht,Ametiala kood,Koormus,Töökoha aadress\n'
               '49001010018,Mari Tamm,2026-01-01,,Tööleping,Raamatupidaja,3313,0.5,Tallinn\n'
               'bad,,not-a-date,,Mystery,,,,\n').encode('utf-8')
    rows = parse_tor_csv(content)
    assert rows[0]['contract_type'] == 'employment'
    assert rows[0]['fte'] == '0.5'
    assert rows[0]['workplace_address'] == 'Tallinn'
    assert rows[1]['errors'] == ['Personal code and name are required', 'Start Date must use YYYY-MM-DD', 'Unsupported contract type']


def test_tor_staging_is_tenant_scoped_and_idempotent(db, ee_org):
    service = TORImportService(db)
    content = b'Personal code,Name,Start date,Contract type,FTE\n49001010018,Mari,2026-01-01,employment,100%\n'
    first = service.stage(ee_org['id'], content, actor='owner@example.test')
    second = service.stage(ee_org['id'], content, actor='owner@example.test')
    assert first['id'] == second['id']
    assert first['status'] == 'review'
    assert first['assumptions']
    assert first['rows'][0]['fte'] == 1
    with pytest.raises(KeyError):
        service.get('wrong-tenant', first['id'])


def test_tor_apply_creates_employee_contract_and_position_idempotently(db, ee_org):
    service = TORImportService(db)
    content = ('Personal code,Name,Start date,End date,Contract type,Position,Occupation code,FTE,Workplace address\n'
               '49001010018,Mari Tamm,2026-01-01,,employment,Accountant,3313,0.5,Tallinn\n').encode()
    staged = service.stage(ee_org['id'], content, actor='owner@example.test')
    result = service.apply(ee_org['id'], staged['id'], actor='owner@example.test')
    assert result['applied'] == 1 and result['failed'] == 0, result['outcomes']
    employee = db.one('SELECT * FROM employees WHERE organisation_id=? AND personal_id=?',
                       (ee_org['id'], '49001010018'))
    assert employee['name'] == 'Mari Tamm' and employee['gross_salary'] is None
    assert employee['pay_basis'] == 'income_line'
    assert employee['fte'] == 0.5
    contract = db.one('SELECT * FROM payroll_contracts WHERE organisation_id=? AND employee_id=?',
                      (ee_org['id'], employee['id']))
    assert contract['contract_type'] == 'employment' and contract['workplace_address'] == 'Tallinn'
    position = db.one('SELECT * FROM payroll_contract_positions WHERE organisation_id=? AND contract_id=?',
                      (ee_org['id'], contract['id']))
    assert (position['position'], position['occupation_code']) == ('Accountant', '3313')
    repeated = service.apply(ee_org['id'], staged['id'], actor='owner@example.test')
    assert repeated['unchanged'] == 1
    assert db.scalar('SELECT COUNT(*) FROM employees WHERE organisation_id=?', (ee_org['id'],)) == 1
    assert db.scalar('SELECT COUNT(*) FROM payroll_contracts WHERE organisation_id=?', (ee_org['id'],)) == 1
    from payroll import PayrollService
    with pytest.raises(ValueError, match='eligible for the period'):
        PayrollService(db).create_run(ee_org['id'], period='2026-11', actor='owner@example.test')


def test_tor_apply_matches_existing_employee_and_updates_contract(db, ee_org):
    from payroll import PayrollService

    employee = PayrollService(db).save_employee(ee_org['id'], actor='owner@example.test', name='Old Name',
                                                personal_id='49001010018', gross_salary='1800')
    service = TORImportService(db)
    content = b'Personal code,Name,Start date,Contract type,Position\n49001010018,Mari Tamm,2026-02-01,employment,Bookkeeper\n'
    staged = service.stage(ee_org['id'], content, actor='owner@example.test')
    assert staged['rows'][0]['matched_employee_id'] == employee['id']
    assert service.apply(ee_org['id'], staged['id'], actor='owner@example.test')['updated'] == 1
    saved = db.one('SELECT * FROM employees WHERE organisation_id=? AND id=?', (ee_org['id'], employee['id']))
    assert saved['name'] == 'Mari Tamm' and saved['gross_salary'] == 1800
    assert db.scalar('SELECT COUNT(*) FROM employees WHERE organisation_id=?', (ee_org['id'],)) == 1
    follow_up = b'Personal code,Name,Start date,End date,Contract type,Workplace address\n49001010018,Mari Tamm,2026-02-01,2026-12-31,employment,Tartu\n'
    second = service.stage(ee_org['id'], follow_up, actor='owner@example.test')
    assert service.apply(ee_org['id'], second['id'], actor='owner@example.test')['updated'] == 1
    contract = db.one('SELECT * FROM payroll_contracts WHERE organisation_id=? AND employee_id=?',
                      (ee_org['id'], employee['id']))
    assert contract['end_date'] == '2026-12-31' and contract['workplace_address'] == 'Tartu'
    assert db.scalar('SELECT COUNT(*) FROM payroll_contracts WHERE organisation_id=? AND employee_id=?',
                     (ee_org['id'], employee['id'])) == 1


def test_tor_duplicate_personal_code_is_visible_and_blocks_apply(db, ee_org):
    from payroll import PayrollService

    payroll = PayrollService(db)
    payroll.save_employee(ee_org['id'], actor='owner@example.test', name='First', personal_id='49001010018', gross_salary='1800')
    second_employee = payroll.save_employee(ee_org['id'], actor='owner@example.test', name='Second', personal_id='49001010018', gross_salary='1900')
    service = TORImportService(db)
    content = b'Personal code,Name,Start date,Contract type\n49001010018,Mari Tamm,2026-02-01,employment\n'
    staged = service.stage(ee_org['id'], content, actor='owner@example.test')
    assert staged['rows'][0]['match_conflict'] == 'Personal code matches more than one employee'
    result = service.apply(ee_org['id'], staged['id'], actor='owner@example.test')
    assert result['failed'] == 1
    refreshed = service.get(ee_org['id'], staged['id'])
    assert refreshed['status'] == 'review'
    assert refreshed['rows'][0]['errors'] == ['Personal code matches more than one employee']
    payroll.delete_employee(ee_org['id'], second_employee['id'], actor='owner@example.test')
    retried = service.apply(ee_org['id'], staged['id'], actor='owner@example.test')
    assert retried['updated'] == 1 and retried['failed'] == 0
    assert service.get(ee_org['id'], staged['id'])['status'] == 'applied'


def test_tor_api_requires_write_role_for_apply(db, ee_org, monkeypatch):
    from fastapi.testclient import TestClient
    from api_app import api

    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    client = TestClient(api)
    root = f"/organisations/{ee_org['id']}/payroll/tor-imports"
    owner = {'X-Test-User':'owner@example.test'}
    content = b'Personal code,Name,Start date,Contract type\n49001010018,Mari Tamm,2026-01-01,employment\n'
    staged = client.post(root, headers=owner, files={'file':('tor.csv',content,'text/csv')})
    assert staged.status_code == 201
    import_id = staged.json()['id']
    assert client.post(f'{root}/{import_id}/apply', json={}).status_code == 401
    assert client.post(f'{root}/{import_id}/apply', headers={'X-Test-User':'viewer@example.test'}, json={}).status_code == 403
    applied = client.post(f'{root}/{import_id}/apply', headers=owner, json={})
    assert applied.status_code == 200 and applied.json()['applied'] == 1

    from api_app import User, api, current_user
    from web_app import app
    api.dependency_overrides[current_user] = lambda: User(email='owner@example.test')
    try:
        with TestClient(app) as session_client:
            csrf_path = f'/api/organisations/{ee_org["id"]}/payroll/tor-imports/{import_id}/apply'
            assert session_client.post(csrf_path, json={}).status_code == 403
            token = session_client.get('/api/csrf').json()['csrf_token']
            assert session_client.post(csrf_path, json={}, headers={'X-CSRF-Token':token}).status_code == 200
    finally:
        api.dependency_overrides.clear()
