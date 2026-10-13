"""Offline staged master-data lifecycle, integrity and API regressions."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from api_app import api, current_user, require_csrf, User
from database import reset_database_cache
from import_service import MasterDataImportService
from master_data_repository import ImportRepository
from core_utils import new_id, utc_now

ACTOR = 'owner@example.test'
CONTACTS = 'name,contact_type,email,phone,address,registry code,VAT number,bank account\nSynthetic customer,both,hello@example.test,+3725555555,Test street,12345678,EE123456789,EE001234\n'
ITEMS = 'code,name,unit,sale price,purchase price\nSYN,Synthetic service,hour,12.3456,4.50\n'


@pytest.mark.parametrize('kind,content', [('contacts', CONTACTS), ('items', ITEMS)])
def test_commit_records_ids_and_reimport_skips(db, ee_org, kind, content):
    service = MasterDataImportService(db)
    batch = service.stage(ee_org['id'], kind, content, actor=ACTOR)
    assert batch['status'] == 'staged' and batch['total_rows'] == 1
    assert batch['error_count'] == 0 and not batch['rows'][0]['entity_id']
    result = service.commit(ee_org['id'], batch['id'], actor=ACTOR)
    assert result['status'] == 'committed'
    record = db.one(f'SELECT * FROM {kind} WHERE organisation_id=? AND id=?', (ee_org['id'], result['rows'][0]['entity_id']))
    assert record['name'].startswith('Synthetic')
    if kind == 'contacts':
        assert record['phone'] == '+3725555555'
        assert record['registration_no'] == '12345678' and record['iban'] == 'EE001234'
    else:
        assert record['unit'] == 'hour'
        assert Decimal(str(record['unit_price'])) == Decimal('12.3456')
        assert Decimal(str(record['purchase_price'])) == Decimal('4.50')
        assert record['sales_account_id'] == db.scalar('SELECT id FROM accounts WHERE organisation_id=? AND system_role=?', (ee_org['id'], 'SALES'))
    repeat = service.stage(ee_org['id'], kind, content, actor=ACTOR)
    assert repeat['warning_count'] == 1
    repeat = service.commit(ee_org['id'], repeat['id'], actor=ACTOR)
    assert repeat['rows'][0]['warning'] == 'Existing record skipped'
    assert repeat['rows'][0]['entity_id'] is None
    assert db.scalar(f'SELECT COUNT(*) FROM {kind} WHERE organisation_id=?', (ee_org['id'],)) == 1
    with pytest.raises(ValueError, match='Only a staged'):
        service.commit(ee_org['id'], batch['id'], actor=ACTOR)


@pytest.mark.parametrize('kind,content', [
    ('contacts', 'name,contact_type,email\nGood,customer,good@example.test\nBad,wrong,invalid\nAnother,supplier,a@example.test\n'),
    ('items', 'code,name,sale_price\nGOOD,Good,12\nBAD,Bad,NaN\nANOTHER,Another,7\n'),
    ('contacts', 'name,contact_type\nGood,customer\nBad,customer,extra\nAnother,supplier\n'),
])
def test_row_errors_do_not_abort_valid_rows(db, ee_org, kind, content):
    service = MasterDataImportService(db)
    batch = service.stage(ee_org['id'], kind, content, actor=ACTOR)
    assert batch['total_rows'] == 3 and batch['error_count'] == 1
    result = service.commit(ee_org['id'], batch['id'], actor=ACTOR)
    assert [bool(r['entity_id']) for r in result['rows']] == [True, False, True]
    assert result['rows'][1]['error']


def test_contact_keys_name_or_registry_and_in_batch_duplicates(db, ee_org):
    service = MasterDataImportService(db)
    content = 'name,contact_type,registry_code\nAlice,both,12345678\nalice,customer,87654321\nRenamed,supplier,12345678\n'
    batch = service.stage(ee_org['id'], 'contacts', content, actor=ACTOR)
    assert batch['warning_count'] == 2
    result = service.commit(ee_org['id'], batch['id'], actor=ACTOR)
    assert result['warning_count'] == 2
    assert sum(bool(r['entity_id']) for r in result['rows']) == 1


def test_discard_retains_audit_rows_and_prevents_commit(db, ee_org):
    service = MasterDataImportService(db)
    batch = service.stage(ee_org['id'], 'items', ITEMS, actor=ACTOR)
    result = service.discard(ee_org['id'], batch['id'], actor=ACTOR)
    assert result['status'] == 'discarded' and result['rows'] == batch['rows']
    for action in (service.commit, service.discard):
        with pytest.raises(ValueError):
            action(ee_org['id'], batch['id'], actor=ACTOR)
    assert db.scalar('SELECT COUNT(*) FROM items WHERE organisation_id=?', (ee_org['id'],)) == 0


def test_tenant_isolation_in_queries_keys_accounts_and_foreign_keys(db, ee_org, uk_org):
    service = MasterDataImportService(db)
    batch = service.stage(ee_org['id'], 'items', ITEMS, actor=ACTOR)
    for action in (service.get, service.commit, service.discard):
        with pytest.raises(KeyError):
            action(uk_org['id'], batch['id'], **({} if action == service.get else {'actor': ACTOR}))
    service.commit(ee_org['id'], batch['id'], actor=ACTOR)
    other = service.stage(uk_org['id'], 'items', ITEMS, actor=ACTOR)
    assert other['warning_count'] == 0
    assert service.commit(uk_org['id'], other['id'], actor=ACTOR)['rows'][0]['entity_id']
    # Code 4010 exists only in the EE chart.
    bad = service.stage(uk_org['id'], 'items', 'code,name,sale_account\nX,X,4010\n', actor=ACTOR)
    assert bad['error_count'] == 1
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as tx:
            ImportRepository(tx, uk_org['id']).stage_row(batch['id'], 55, {}, {})


@pytest.mark.parametrize('content', ['', 'email\nx@example.test\n', 'name,name,contact_type\nx,x,both\n', 'name,contact_type,currency\nx,both,USD\n', '"broken header'])
def test_invalid_headers_and_content_rejected_without_batches(db, ee_org, content):
    with pytest.raises(ValueError):
        MasterDataImportService(db).stage(ee_org['id'], 'contacts', content, actor=ACTOR)
    assert db.scalar('SELECT COUNT(*) FROM import_batches WHERE organisation_id=?', (ee_org['id'],)) == 0


def test_broken_quote_preserves_preceding_rows_as_staged(db, ee_org):
    service = MasterDataImportService(db)
    batch = service.stage(ee_org['id'], 'contacts', 'name,contact_type\nGood,both\n"Unclosed,both\n', actor=ACTOR)
    assert batch['error_count'] == 1 and batch['total_rows'] == 2
    result = service.commit(ee_org['id'], batch['id'], actor=ACTOR)
    assert result['rows'][0]['entity_id'] and result['rows'][1]['error'] == 'Malformed CSV row'


def test_malformed_row_can_resume_and_row_numbers_match_csv_lines(db, ee_org):
    batch = MasterDataImportService(db).stage(ee_org['id'], 'contacts', 'name,contact_type\n\n"Bad"x,both\nGood,both\n', actor=ACTOR)
    assert batch['total_rows'] == 2 and batch['error_count'] == 1
    assert [r['row_number'] for r in batch['rows']] == [3, 4]
    assert batch['rows'][1]['parsed']['name'] == 'Good'


def test_upgrade_preserves_existing_master_data(tmp_path, monkeypatch):
    import shutil
    import database
    from documents import DocumentService
    from organisations import OrganisationService

    original = database.MIGRATIONS
    previous = tmp_path / 'previous' / 'sqlite'
    previous.mkdir(parents=True)
    for path in (original / 'sqlite').glob('*.sql'):
        if path.stem < '0019':
            shutil.copyfile(path, previous / path.name)
    monkeypatch.setattr(database, 'MIGRATIONS', previous.parent)
    db = database.Database(path=str(tmp_path / 'upgrade.sqlite'))
    db.migrate()
    org = OrganisationService(db).create(name='Synthetic upgrade', country_code='EE', entity_type='EE_OU', owner_email=ACTOR)
    docs = DocumentService(db)
    contact = docs.create_contact(org['id'], name='Preserved contact', country_code='EE')
    item = docs.create_item(org['id'], code='OLD', name='Preserved item', unit_price='1.25')
    monkeypatch.setattr(database, 'MIGRATIONS', original)
    assert db.migrate() == ['0019_master_data_import', '0020_quotes', '0021_periodisation', '0022_payment_links', '0023_analytical_objects', '0024_reminder_rules', '0025_fx_realised', '0026_fx_revaluations', '0027_mfa', '0028_document_settings', '0029_copilot']
    assert db.migrate() == []
    assert db.one('SELECT * FROM contacts WHERE organisation_id=? AND id=?', (org['id'], contact['id'])) == contact
    after = db.one('SELECT * FROM items WHERE organisation_id=? AND id=?', (org['id'], item['id']))
    assert {key: after[key] for key in item} == item
    assert after['unit'] == '' and after['purchase_price'] is None


@pytest.mark.parametrize('field,value', [('registry_code', 'abc'), ('registry_code', '1234567'), ('vat_number', 'EE123'), ('vat_number', 'EE1234567890'), ('email', 'no-at-sign')])
def test_contact_formats(db, ee_org, field, value):
    batch = MasterDataImportService(db).stage(ee_org['id'], 'contacts', f'name,contact_type,{field}\nBad,both,{value}\n', actor=ACTOR)
    assert batch['error_count'] == 1


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', '0.00001', '10000000000000000', 'abc'])
def test_exact_price_validation(db, ee_org, value):
    batch = MasterDataImportService(db).stage(ee_org['id'], 'items', f'code,name,purchase_price\nX,X,{value}\n', actor=ACTOR)
    assert batch['error_count'] == 1


def test_account_changes_between_stage_and_commit_are_row_errors(db, ee_org):
    service = MasterDataImportService(db)
    batch = service.stage(ee_org['id'], 'items', ITEMS, actor=ACTOR)
    with db.transaction() as tx:
        tx.execute("UPDATE accounts SET active=0 WHERE organisation_id=? AND system_role='SALES'", (ee_org['id'],))
    result = service.commit(ee_org['id'], batch['id'], actor=ACTOR)
    assert result['error_count'] == 1 and result['rows'][0]['entity_id'] is None


def test_atomic_rollback_including_status_and_ids(db, ee_org, monkeypatch):
    service = MasterDataImportService(db)
    batch = service.stage(ee_org['id'], 'contacts', 'name,contact_type\nA,both\nB,both\n', actor=ACTOR)
    original = ImportRepository.create
    def fail_second(self, kind, fields, country):
        if fields['name'] == 'B':
            raise RuntimeError('Synthetic database failure')
        return original(self, kind, fields, country)
    monkeypatch.setattr(ImportRepository, 'create', fail_second)
    with pytest.raises(RuntimeError):
        service.commit(ee_org['id'], batch['id'], actor=ACTOR)
    result = service.get(ee_org['id'], batch['id'])
    assert result['status'] == 'staged' and all(r['entity_id'] is None for r in result['rows'])
    assert db.scalar('SELECT COUNT(*) FROM contacts WHERE organisation_id=?', (ee_org['id'],)) == 0


def test_concurrent_batches_share_natural_key_lock(db, ee_org):
    service = MasterDataImportService(db)
    batches = [service.stage(ee_org['id'], 'contacts', CONTACTS, actor=ACTOR) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda b: service.commit(ee_org['id'], b['id'], actor=ACTOR), batches))
    assert sum(r['warning_count'] for r in results) == 1
    assert db.scalar('SELECT COUNT(*) FROM contacts WHERE organisation_id=?', (ee_org['id'],)) == 1


def test_pagination(db, ee_org):
    service = MasterDataImportService(db)
    batch = service.stage(ee_org['id'], 'contacts', 'name,contact_type\nA,both\nB,both\n', actor=ACTOR)
    assert service.get(ee_org['id'], batch['id'], limit=1, offset=1)['rows'][0]['parsed']['name'] == 'B'
    with pytest.raises(ValueError):
        service.get(ee_org['id'], batch['id'], limit=0)


def test_api_authorisation_lifecycle_and_csrf_dependencies(db, ee_org, uk_org, monkeypatch):
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    reset_database_cache()
    with db.transaction() as tx:
        tx.execute('INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)', (new_id(), ee_org['id'], 'viewer@example.test', 'viewer', utc_now()))
    base = f"/organisations/{ee_org['id']}/imports"
    with TestClient(api, headers={'X-Test-User': ACTOR}) as client:
        response = client.post(base, json={'kind': 'contacts', 'csv_content': CONTACTS})
        assert response.status_code == 201
        batch = response.json()
        url = base + '/' + batch['id']
        viewer = {'X-Test-User': 'viewer@example.test'}
        assert client.get(url, headers=viewer).status_code == 200
        assert client.post(base, headers=viewer, json={'kind': 'items', 'csv_content': ITEMS}).status_code == 403
        for suffix in ('commit', 'discard'):
            assert client.post(url + '/' + suffix, headers=viewer).status_code == 403
        assert client.get(url, headers={'X-Test-User': 'outsider@example.test'}).status_code == 403
        assert client.get(f"/organisations/{uk_org['id']}/imports/{batch['id']}").status_code == 404
        assert client.post(url + '/commit').json()['status'] == 'committed'
        assert client.post(url + '/commit').status_code == 422
        batch = client.post(base, json={'kind': 'items', 'csv_content': ITEMS}).json()
        assert client.post(base + '/' + batch['id'] + '/discard').json()['status'] == 'discarded'
        assert client.post(base, json={'kind': 'contacts', 'csv_content': 'bad'}).status_code == 422
    routes = [r for r in api.routes if '/imports' in r.path and '/bank-' not in r.path]
    assert len(routes) == 4
    for route in routes:
        assert (current_user if route.methods == {'GET'} else require_csrf) in [d.call for d in route.dependant.dependencies]
    # Exercise actual CSRF enforcement with a user dependency, without test-header bypass.
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        from web_app import app
        with TestClient(app) as client:
            assert client.post('/api' + base, json={'kind': 'items', 'csv_content': ITEMS}).status_code == 403
            token = client.get('/api/csrf').json()['csrf_token']
            assert client.post('/api' + base, headers={'X-CSRF-Token': token}, json={'kind': 'items', 'csv_content': ITEMS}).status_code == 201
    finally:
        api.dependency_overrides.clear()
        reset_database_cache()
