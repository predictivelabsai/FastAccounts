from payroll_tor_import import TORImportService, parse_tor_csv
import pytest


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


def test_tor_duplicate_personal_code_is_visible_and_blocks_apply(db, ee_org):
    from payroll import PayrollService

    payroll = PayrollService(db)
    payroll.save_employee(ee_org['id'], actor='owner@example.test', name='First', personal_id='49001010018', gross_salary='1800')
    payroll.save_employee(ee_org['id'], actor='owner@example.test', name='Second', personal_id='49001010018', gross_salary='1900')
    service = TORImportService(db)
    content = b'Personal code,Name,Start date,Contract type\n49001010018,Mari Tamm,2026-02-01,employment\n'
    staged = service.stage(ee_org['id'], content, actor='owner@example.test')
    assert staged['rows'][0]['match_conflict'] == 'Personal code matches more than one employee'
    result = service.apply(ee_org['id'], staged['id'], actor='owner@example.test')
    assert result['failed'] == 1
    refreshed = service.get(ee_org['id'], staged['id'])
    assert refreshed['status'] == 'review'
    assert refreshed['rows'][0]['errors'] == ['Personal code matches more than one employee']
