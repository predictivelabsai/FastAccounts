"""Analytical objects, dimension propagation, immutable history and report filtering."""
from decimal import Decimal
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from core_utils import new_id, utc_now
from database import Database, reset_database_cache
from documents import DocumentService
from ledger import LedgerService, PostingLine
from objects import ObjectService
from objects_repository import DIMENSIONS, ObjectRepository

ACTOR = 'owner@example.test'


@pytest.fixture
def objects(db, ee_org):
    service = ObjectService(db)
    oid = ee_org['id']
    rows = {kind: service.create(oid, object_type=kind, code=kind.upper(), name='Synthetic ' + kind, actor=ACTOR)
            for kind in DIMENSIONS.values()}
    with db.transaction() as tx:
        tx.execute('INSERT INTO fiscal_periods(id,organisation_id,code,starts_on,ends_on) VALUES (?,?,?,?,?)',
                   (new_id(), oid, 'SYNTHETIC-2025', '2025-01-01', '2025-12-31'))
    return service, oid, rows


def account(db, oid, role):
    return db.scalar('SELECT id FROM accounts WHERE organisation_id=? AND system_role=?', (oid, role))


def invoice(db, oid, tags, amount='10.01', day='2026-01-01', other_lines=None, **kwargs):
    docs = DocumentService(db)
    contact = docs.create_contact(oid, name='Synthetic customer', country_code='EE')
    result = docs.create_invoice(oid, contact_id=contact['id'], issue_date=day, actor=ACTOR,
        lines=[dict(account_id=account(db, oid, 'SALES'), unit_price=amount, **tags), *(other_lines or [])], **kwargs)
    return docs.issue_invoice(result['id'], actor=ACTOR)


def test_crud_audit_validation_and_tenancy(db, objects, uk_org):
    service, oid, rows = objects
    assert len(service.list(oid)) == 4 and service.list(uk_org['id']) == []
    obj = rows['project']
    assert service.update(oid, obj['id'], actor=ACTOR, name=' Edited ', notes=' Note ')['name'] == 'Edited'
    with pytest.raises(KeyError):
        service.get(uk_org['id'], obj['id'])
    with pytest.raises(KeyError):
        service.update(uk_org['id'], obj['id'], actor=ACTOR, name='Wrong tenant')
    with pytest.raises(KeyError):
        service.delete(uk_org['id'], obj['id'], actor=ACTOR)
    for changes in [{'code': ' '}, {'name': ' '}, {'active': 1}, {'object_type': 'crm'}, {'notes': None}, {'extra': True}]:
        with pytest.raises(ValueError):
            service.update(oid, obj['id'], actor=ACTOR, **changes)
    with pytest.raises(ValueError, match='already exists'):
        service.create(oid, object_type='project', code='PROJECT', name='Duplicate', actor=ACTOR)
    assert service.delete(oid, obj['id'], actor=ACTOR) == {'deleted': True}
    assert len(service.list(oid)) == 3
    assert [r['action'] for r in db.rows('SELECT action FROM audit_events WHERE organisation_id=? AND object_type=? ORDER BY created_at,id',
                                        (oid, 'object'))].count('object.created') == 4


@pytest.mark.parametrize('field,kind', DIMENSIONS.items())
def test_invoice_dimensions_reports_comparison_and_reversal(db, objects, field, kind):
    service, oid, rows = objects
    tags = {field: rows[kind]['id']}
    sale = invoice(db, oid, tags, other_lines=[dict(account_id=account(db, oid, 'SALES'), unit_price='20.02')])
    assert sale['lines'][0][field] == tags[field]
    ledger = LedgerService(db)
    query = dict(start='2026-01-01', end='2026-01-31', object_id=tags[field])
    filtered = ledger.general_ledger(oid, **query)
    assert len(filtered) == 1 and Decimal(str(filtered[0]['credit'])) == Decimal('10.01')
    assert ledger.profit_and_loss(oid, **query)['income'] == Decimal('10.01')
    assert ledger.profit_and_loss(oid, start=query['start'], end=query['end'])['income'] == Decimal('30.03')
    invoice(db, oid, tags, amount='3.33', day='2025-12-01')
    for compare in ['previous', 'prior_year', 'ytd']:
        report = ledger.profit_and_loss(oid, **query, compare=compare)
        assert report['compare'] == compare and report['income'] == Decimal('10.01')
        assert report['comparative']['income'] == (Decimal('3.33') if compare == 'previous' else Decimal('0'))
    trial = ledger.trial_balance(oid, **query)
    assert sum((r['credit'] for r in trial), Decimal(0)) == Decimal('10.01')
    with pytest.raises(ValueError, match='Deactivate'):
        service.delete(oid, tags[field], actor=ACTOR)
    with pytest.raises(ValueError, match='change type'):
        service.update(oid, tags[field], actor=ACTOR, object_type='object' if kind != 'object' else 'project')
    service.update(oid, tags[field], actor=ACTOR, active=False)
    ledger.reverse(sale['posting_batch_id'], reversal_date='2026-01-02', actor=ACTOR)
    assert ledger.profit_and_loss(oid, **query)['income'] == Decimal('0.00')
    assert len(ledger.general_ledger(oid, **query)) == 2
    with pytest.raises(ValueError, match='active'):
        invoice(db, oid, tags)


@pytest.mark.parametrize('document_type', ['bill', 'supplier_credit'])
def test_bill_and_supplier_credit_propagation(db, objects, document_type):
    service, oid, rows = objects
    docs = DocumentService(db)
    contact = docs.create_contact(oid, name='Synthetic supplier', country_code='EE')
    tags = {key: rows[kind]['id'] for key, kind in DIMENSIONS.items()}
    expense = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND account_type='Expense' ORDER BY code LIMIT 1", (oid,))
    bill = docs.create_bill(oid, contact_id=contact['id'], supplier_number='SYNTHETIC', bill_date='2026-01-01',
        due_date='2026-01-31', actor=ACTOR, document_type=document_type,
        lines=[dict(account_id=expense, unit_price='12.34', **tags)])
    assert {k: bill['lines'][0][k] for k in tags} == tags
    docs.approve_bill(bill['id'], actor=ACTOR)
    report = LedgerService(db).profit_and_loss(oid, start='2026-01-01', end='2026-01-31', object_id=rows['project']['id'])
    assert report['expenses'] == Decimal('12.34') * (1 if document_type == 'bill' else -1)
    assert db.rows('PRAGMA foreign_key_check') == []


def test_draft_references_and_wrong_type_tenant_rejected(db, objects, uk_org):
    service, oid, rows = objects
    docs = DocumentService(db)
    customer = docs.create_contact(oid, name='Synthetic customer', country_code='EE')
    foreign = service.create(uk_org['id'], object_type='project', code='P', name='Foreign', actor=ACTOR)
    for object_id in [foreign['id'], rows['person']['id'], 'missing']:
        with pytest.raises((KeyError, ValueError)):
            docs.create_invoice(oid, contact_id=customer['id'], issue_date='2026-01-01', actor=ACTOR,
                lines=[dict(account_id=account(db, oid, 'SALES'), unit_price='1', projects_project_id=object_id)])
    assert not db.rows('SELECT id FROM invoices WHERE organisation_id=?', (oid,))
    draft = docs.create_invoice(oid, contact_id=customer['id'], issue_date='2026-01-01', actor=ACTOR,
        lines=[dict(account_id=account(db, oid, 'SALES'), unit_price='1', projects_project_id=rows['project']['id'])])
    with pytest.raises(ValueError, match='Deactivate'):
        service.delete(oid, rows['project']['id'], actor=ACTOR)
    for wrong_id in [foreign['id'], rows['person']['id']]:
        with pytest.raises(sqlite3.IntegrityError), db.transaction() as tx:
            tx.execute('UPDATE invoice_line_objects SET projects_project_id=? WHERE organisation_id=? AND line_id=?',
                       (wrong_id, oid, draft['lines'][0]['id']))
    service.update(oid, rows['project']['id'], actor=ACTOR, active=False)
    assert docs.issue_invoice(draft['id'], actor=ACTOR)['status'] == 'Issued'
    with pytest.raises(KeyError):
        LedgerService(db).profit_and_loss(oid, start='2026-01-01', end='2026-01-31', object_id=foreign['id'])


def test_immutable_tags_and_composite_parent_keys(db, objects, uk_org):
    _, oid, rows = objects
    sale = invoice(db, oid, {'projects_project_id': rows['project']['id']})
    for table in ['invoice_line_objects', 'gl_entry_objects']:
        row = db.one(f'SELECT * FROM {table} WHERE organisation_id=?', (oid,))
        for sql in [f'UPDATE {table} SET projects_project_id=NULL WHERE organisation_id=? AND line_id=?',
                    f'DELETE FROM {table} WHERE organisation_id=? AND line_id=?']:
            with pytest.raises(sqlite3.IntegrityError, match='immutable'), db.transaction() as tx:
                tx.execute(sql, (oid, row['line_id']))
    control = db.one('SELECT id FROM gl_entries WHERE organisation_id=? AND posting_batch_id=? AND account_id=?',
                     (oid, sale['posting_batch_id'], account(db, oid, 'AR')))
    with pytest.raises(sqlite3.IntegrityError, match='immutable'), db.transaction() as tx:
        ObjectRepository(tx, oid).save_dimensions('gl', sale['posting_batch_id'], control['id'],
            {k: rows['project']['id'] if kind == 'project' else None for k, kind in DIMENSIONS.items()})
    # A foreign parent/line pair cannot be used by a companion row in another tenant.
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as tx:
        tx.execute('INSERT INTO invoice_line_objects(organisation_id,parent_id,line_id) VALUES (?,?,?)',
                   (uk_org['id'], sale['id'], sale['lines'][0]['id']))


def test_api_roles_csrf_journal_and_reports(db, objects, uk_org, monkeypatch):
    from api_app import api, User, current_user, require_csrf
    service, oid, rows = objects
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    reset_database_cache()
    with db.transaction() as tx:
        for role in ['viewer', 'approver', 'accountant', 'administrator']:
            tx.execute('INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)',
                       (new_id(), oid, role + '@example.test', role, utc_now()))
    base = f'/organisations/{oid}'
    payload = dict(object_type='object', code='NEW', name='Synthetic object')
    with TestClient(api, headers={'X-Test-User': ACTOR}) as client:
        response = client.post(base + '/objects', json=payload)
        assert response.status_code == 201, response.text
        url = base + '/objects/' + response.json()['id']
        for role in ['viewer', 'approver', 'accountant']:
            headers = {'X-Test-User': role + '@example.test'}
            assert client.get(base + '/objects', headers=headers).status_code == 200
            assert client.get(url, headers=headers).status_code == 200
            assert client.post(base + '/objects', headers=headers, json=payload).status_code == 403
            assert client.patch(url, headers=headers, json={'active': False}).status_code == 403
            assert client.delete(url, headers=headers).status_code == 403
        assert client.patch(url, json={'active': None}).status_code == 422
        assert client.post(base + '/objects', json=payload | {'extra': True}).status_code == 422
        assert client.patch(url, headers={'X-Test-User': 'administrator@example.test'}, json={'active': False}).status_code == 200
        assert client.get(url.replace(oid, uk_org['id'])).status_code == 404
        assert client.delete(url).status_code == 200
        tag = dict(projects_project_id=rows['project']['id'])
        journal = dict(voucher_code='SYNTHETIC-J', posting_date='2026-01-01', currency='EUR', idempotency_key='synthetic-journal',
                       lines=[dict(account_id=account(db, oid, 'BANK'), debit='2.22', **tag),
                              dict(account_id=account(db, oid, 'SALES'), credit='2.22', **tag)])
        first = client.post(base + '/journals', json=journal)
        assert first.status_code == 201, first.text
        assert client.post(base + '/journals', json=journal).json()['id'] == first.json()['id']
        for report in ['general-ledger', 'trial-balance', 'profit-and-loss']:
            response = client.get(base + '/reports/' + report, params=dict(start='2026-01-01', end='2026-01-31', object_id=rows['project']['id']))
            assert response.status_code == 200, response.text
            if report == 'general-ledger':
                assert len(response.json()) == 2
            if report == 'profit-and-loss':
                assert Decimal(str(response.json()['profit'])) == Decimal('2.22')
    for route in [r for r in api.routes if '/objects' in r.path]:
        assert (current_user if route.methods == {'GET'} else require_csrf) in [d.call for d in route.dependant.dependencies]
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        from web_app import app
        with TestClient(app) as client:
            token = client.get('/api/csrf').json()['csrf_token']
            url = '/api' + base + '/objects/' + rows['person']['id']
            assert client.patch(url, json={'active': False}).status_code == 403
            assert client.delete(url).status_code == 403
            assert client.patch(url, json={'active': False}, headers={'X-CSRF-Token': token}).status_code == 200
    finally:
        api.dependency_overrides.clear()
        reset_database_cache()


def test_migration_upgrade_rerun_and_data_preservation(tmp_path, monkeypatch):
    import database
    from organisations import OrganisationService
    original = database.MIGRATIONS
    previous = tmp_path / 'previous' / 'sqlite'
    previous.mkdir(parents=True)
    for file in (original / 'sqlite').glob('*.sql'):
        if file.stem < '0023':
            shutil.copyfile(file, previous / file.name)
    monkeypatch.setattr(database, 'MIGRATIONS', previous.parent)
    db = Database(path=str(tmp_path / 'upgrade.sqlite'))
    db.migrate()
    org = OrganisationService(db).create(name='Synthetic', country_code='EE', entity_type='EE_OU', owner_email=ACTOR)
    invoice(db, org['id'], {})
    tables = ['organisations', 'accounts', 'invoices', 'invoice_lines', 'posting_batches', 'gl_entries', 'audit_events']
    before = {t: db.rows(f'SELECT * FROM {t} ORDER BY id') for t in tables}
    monkeypatch.setattr(database, 'MIGRATIONS', original)
    assert db.migrate() == ['0023_analytical_objects', '0024_reminder_rules', '0025_fx_realised', '0026_fx_revaluations', '0027_mfa', '0028_document_settings', '0029_copilot', '0030_master_data_maintenance'] and db.migrate() == []
    with db.transaction() as tx:
        tx.connection.executescript((original / 'sqlite' / '0023_analytical_objects.sql').read_text(encoding='utf-8'))
    after = {t: db.rows(f'SELECT * FROM {t} ORDER BY id') for t in tables}
    assert all(row.pop('copilot_enabled') == 0 for row in after['organisations'])
    assert before == after
    assert db.rows('PRAGMA foreign_key_check') == []


@pytest.mark.parametrize('approved_first', [False, True])
def test_periodisation_preserves_dimension_totals_and_rounding(db, objects, approved_first):
    from periodisation import PeriodisationService
    service, oid, rows = objects
    second = service.create(oid, object_type='project', code='SECOND', name='Synthetic second project', actor=ACTOR)
    docs = DocumentService(db)
    supplier = docs.create_contact(oid, name='Synthetic supplier', country_code='EE')
    expense = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND account_type='Expense' ORDER BY code LIMIT 1", (oid,))
    bill = docs.create_bill(oid, contact_id=supplier['id'], supplier_number='SYNTHETIC-PER', bill_date='2026-01-01',
        due_date='2026-01-31', actor=ACTOR, lines=[
            dict(account_id=expense, unit_price='0.01', projects_project_id=rows['project']['id']),
            dict(account_id=expense, unit_price='0.02', projects_project_id=second['id'])])
    if approved_first:
        docs.approve_bill(bill['id'], actor=ACTOR)
    periods = PeriodisationService(db)
    schedule = periods.create(oid, bill_id=bill['id'], expense_account_id=expense,
                              start_period='2026-01-01', number_of_periods=3, actor=ACTOR)
    if not approved_first:
        docs.approve_bill(bill['id'], actor=ACTOR)
    service.update(oid, rows['project']['id'], actor=ACTOR, active=False)
    assert periods.post_due(oid, schedule['id'], as_at='2026-03-01', actor=ACTOR)['status'] == 'Completed'
    ledger = LedgerService(db)
    for object_id, expected in [(rows['project']['id'], '0.01'), (second['id'], '0.02')]:
        assert ledger.profit_and_loss(oid, start='2026-01-01', end='2026-03-31', object_id=object_id)['expenses'] == Decimal(expected)
    assert all(Decimal(str(row['debit'])) >= 0 and Decimal(str(row['credit'])) >= 0
               for row in db.rows('SELECT debit,credit FROM gl_entries WHERE organisation_id=?', (oid,)))


def test_credit_note_preserves_tags_and_locked_journal_rolls_back(db, objects):
    _, oid, rows = objects
    tags = dict(projects_project_id=rows['project']['id'])
    sale = invoice(db, oid, tags)
    invoice(db, oid, tags, amount='1.01', document_type='credit_note', original_invoice_id=sale['id'])
    ledger = LedgerService(db)
    assert ledger.profit_and_loss(oid, start='2026-01-01', end='2026-01-31', object_id=rows['project']['id'])['income'] == Decimal('9.00')
    period = db.one("SELECT id FROM fiscal_periods WHERE organisation_id=? AND starts_on<=? AND ends_on>=?", (oid, '2026-01-01', '2026-01-01'))
    ledger.lock_period(period['id'], actor=ACTOR, reason='Synthetic close')
    before = db.rows('SELECT * FROM gl_entry_objects WHERE organisation_id=? ORDER BY line_id', (oid,))
    with pytest.raises(ValueError, match='locked'):
        ledger.post(organisation_id=oid, voucher_type='manual_journal', voucher_id='locked', voucher_code='SYNTHETIC',
            posting_date='2026-01-01', actor=ACTOR, currency='EUR',
            lines=[PostingLine(account(db, oid, 'BANK'), debit=Decimal('1'), **tags),
                   PostingLine(account(db, oid, 'SALES'), credit=Decimal('1'), **tags)])
    assert db.rows('SELECT * FROM gl_entry_objects WHERE organisation_id=? ORDER BY line_id', (oid,)) == before


def test_locale_append_sections():
    from web.i18n import catalog, t
    keys = set(catalog('en')['analytical_objects']['workspace'])
    for language in ['en', 'et', 'lt', 'lv']:
        assert set(catalog(language)['analytical_objects']['workspace']) == keys
        assert t('nav.objects', language) == catalog(language)['workspace']['Objects']
    assert t('nav.objects', 'et') == 'Objektid'
    for key, expected in [('Object', 'Objekt'), ('Add object', 'Lisa objekt'),
                          ('Edit object', 'Muuda objekti'), ('Delete object', 'Kustuta objekt')]:
        assert catalog('et')['workspace'][key] == expected


def test_recurring_invoices_inherit_template_dimensions(db, objects):
    from automation import AutomationService
    service, oid, rows = objects
    sale = invoice(db, oid, {'projects_project_id': rows['project']['id']})
    automation = AutomationService(db)
    schedule = automation.create_schedule(oid, template_invoice_id=sale['id'], interval_kind='monthly',
                                          next_run_date='2026-02-01', actor=ACTOR)
    service.update(oid, rows['project']['id'], actor=ACTOR, active=False)
    results = automation.run_due(today='2026-02-01', organisation_ids=[oid])
    assert len(results) == 1 and results[0]['status'] == 'Issued'
    generated = DocumentService(db).invoice(results[0]['invoice_id'], oid)
    assert generated['lines'][0]['projects_project_id'] == rows['project']['id']
    assert LedgerService(db).profit_and_loss(oid, start='2026-02-01', end='2026-02-28', object_id=rows['project']['id'])['income'] == Decimal('10.01')
