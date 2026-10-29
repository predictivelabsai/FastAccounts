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
