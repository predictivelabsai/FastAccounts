"""Offline purchase expense, VAT, tenancy, migration and API regressions."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from core_utils import money, new_id, utc_now
from database import Database, reset_database_cache
from documents import DocumentService
from ledger import LedgerService, PostingLine
from periodisation import PeriodisationService

ACTOR = 'owner@example.test'


@pytest.fixture
def purchase(db, ee_org, monkeypatch):
    oid = ee_org['id']
    docs = DocumentService(db)
    supplier = docs.create_contact(oid, name='Synthetic insurer', country_code='EE', contact_type='supplier')
    account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='EXPENSE'", (oid,))
    tax = db.scalar("SELECT id FROM tax_codes WHERE organisation_id=? AND kind='standard' AND active=1", (oid,))
    bill = docs.create_bill(oid, contact_id=supplier['id'], supplier_number='SYNTHETIC-001',
        bill_date='2026-01-01', due_date='2026-01-31', actor=ACTOR,
        lines=[dict(description='Annual insurance', quantity='1', unit_price='1200.01', account_id=account, tax_code_id=tax)])
    monkeypatch.setattr('periodisation.current_day', lambda: '2026-01-31')
    return PeriodisationService(db), oid, bill, dict(bill_id=bill['id'], expense_account_id=account,
        start_period='2026-01-31', number_of_periods=12, amount='1200.01')


def create(purchase, **changes):
    service, oid, bill, data = purchase
    return service.create(oid, actor=ACTOR, **(data | changes))


def account_balance(db, oid, role):
    rows = LedgerService(db).trial_balance(oid, start='2026-01-01', end='2026-12-31')
    account = db.one('SELECT code FROM accounts WHERE organisation_id=? AND system_role=?', (oid, role))
    assert sum((r['debit'] - r['credit'] for r in rows), Decimal(0)) == 0
    return next(r['balance'] for r in rows if r['code'] == account['code'])


@pytest.mark.parametrize('posted', [False, True])
@pytest.mark.parametrize('split_rule', ['equal_first', 'equal_last'])
def test_full_bill_and_twelve_net_transfers(db, purchase, monkeypatch, posted, split_rule):
    service, oid, bill, data = purchase
    if posted:
        bill = DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
    original = db.rows('SELECT * FROM gl_entries ORDER BY id')
    schedule = create(purchase, split_rule=split_rule)
    portions = schedule['periods']
    assert len(portions) == 12 and sum((p['net_amount'] for p in portions), Decimal(0)) == Decimal('1200.01')
    assert portions[0 if split_rule == 'equal_first' else -1]['net_amount'] == Decimal('100.01')
    assert all(p['vat_amount'] == 0 for p in portions)
    assert [p['period_date'] for p in portions[:3]] == ['2026-01-31', '2026-02-28', '2026-03-31']
    if not posted:
        assert not db.rows('SELECT * FROM gl_entries')
        with pytest.raises(ValueError, match='Approve'):
            service.post_due(oid, schedule['id'], actor=ACTOR)
        bill = DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
    else:
        assert DocumentService(db).bill(bill['id']) == bill
        assert all(e in db.rows('SELECT * FROM gl_entries') for e in original)
    assert account_balance(db, oid, 'EXPENSE') == 0
    assert account_balance(db, oid, 'PERIODISED_PURCHASES') == Decimal('1200.01')
    assert account_balance(db, oid, 'INPUT_VAT') == money(bill['tax_total'])
    assert account_balance(db, oid, 'AP') == -money(bill['total'])
    january = service.post_due(oid, schedule['id'], actor=ACTOR, period_id=portions[0]['id'])
    assert january['posted_periods'] == 1
    entries = db.rows('SELECT * FROM gl_entries ORDER BY id')
    assert service.post_due(oid, schedule['id'], actor=ACTOR, period_id=portions[0]['id']) == january
    assert db.rows('SELECT * FROM gl_entries ORDER BY id') == entries
    assert account_balance(db, oid, 'EXPENSE') == portions[0]['net_amount']
    assert account_balance(db, oid, 'INPUT_VAT') == money(bill['tax_total'])
    monkeypatch.setattr('periodisation.current_day', lambda: '2026-12-31')
    completed = service.post_due(oid, schedule['id'], actor=ACTOR)
    assert completed['status'] == 'Completed' and completed['posted_periods'] == 12 and completed['pending_amount'] == 0
    assert account_balance(db, oid, 'PERIODISED_PURCHASES') == 0
    assert account_balance(db, oid, 'EXPENSE') == Decimal('1200.01')
    assert account_balance(db, oid, 'INPUT_VAT') == money(bill['tax_total'])
    assert account_balance(db, oid, 'AP') == -money(bill['total'])
    for period in completed['periods']:
        entries = db.rows('SELECT * FROM gl_entries WHERE posting_batch_id=?', (period['posted_journal_id'],))
        assert len(entries) == 2
        assert sum((money(e['debit']) - money(e['credit']) for e in entries), Decimal(0)) == 0
    assert service.post_due(oid, schedule['id'], actor=ACTOR) == completed
    assert service.run_due(oid) == []
    assert db.scalar("SELECT COUNT(*) FROM audit_events WHERE organisation_id=? AND action='periodisation.posted'", (oid,)) == 12
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as tx:
        tx.execute('UPDATE gl_entries SET debit=1 WHERE organisation_id=? AND posting_batch_id=?', (oid, completed['periods'][0]['posted_journal_id']))


@pytest.mark.parametrize('changes', [dict(amount='1200'), dict(amount='NaN'), dict(amount='Infinity'),
    dict(amount='0.001'), dict(amount='-1'), dict(amount='abc'), dict(amount='10000000000000000'),
    dict(number_of_periods=0), dict(number_of_periods=121), dict(number_of_periods=True), dict(number_of_periods=Decimal('12')),
    dict(start_period='bad'), dict(start_period='2025-12-31'), dict(start_period='2028-01-31'),
    dict(split_rule='bad'), dict(status='Completed'), dict(expense_account_id='missing'), dict(bill_id='missing')])
def test_validation_and_atomic_create(db, purchase, changes):
    before = db.rows('SELECT * FROM audit_events ORDER BY id')
    with pytest.raises((ValueError, KeyError)):
        create(purchase, **changes)
    service, oid, _, _ = purchase
    assert service.list(oid) == []
    assert not db.rows('SELECT * FROM purchase_schedule_periods')
    assert not db.rows('SELECT * FROM gl_entries')
    assert db.rows('SELECT * FROM audit_events ORDER BY id') == before


def test_duplicate_and_draft_activation(db, purchase):
    service, oid, bill, data = purchase
    schedule = create(purchase, status='Draft', amount=None)
    with pytest.raises(ValueError, match='already'):
        create(purchase)
    DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
    with pytest.raises(ValueError, match='Active'):
        service.post_due(oid, schedule['id'], actor=ACTOR)
    assert service.run_due(oid) == []
    service.update(oid, schedule['id'], actor=ACTOR, notes='Reviewed')
    active = service.update(oid, schedule['id'], actor=ACTOR, status='Active')
    assert active['status'] == 'Active' and active['notes'] == 'Reviewed'
    with pytest.raises(ValueError):
        service.update(oid, schedule['id'], actor=ACTOR, notes='bad')
    assert service.post_due(oid, schedule['id'], actor=ACTOR)['posted_periods'] == 1


def test_future_post_and_foreign_period_rejected(db, purchase):
    service, oid, bill, _ = purchase
    schedule = create(purchase)
    DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
    with pytest.raises(ValueError, match='advance'):
        service.post_due(oid, schedule['id'], actor=ACTOR, as_at='2026-12-31')
    with pytest.raises(ValueError, match='not due'):
        service.post_due(oid, schedule['id'], actor=ACTOR, period_id=schedule['periods'][1]['id'])
    with pytest.raises(KeyError):
        service.post_due(oid, schedule['id'], actor=ACTOR, period_id='missing')
    assert service.get(oid, schedule['id'])['posted_periods'] == 0


def test_cancel_only_future_preserves_posted_ledger_and_residual(db, purchase):
    service, oid, bill, _ = purchase
    schedule = create(purchase)
    DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
    with pytest.raises(ValueError, match='Post due'):
        service.cancel(oid, schedule['id'], actor=ACTOR)
    posted = service.post_due(oid, schedule['id'], actor=ACTOR)
    entries = db.rows('SELECT * FROM gl_entries ORDER BY id')
    cancelled = service.cancel(oid, schedule['id'], actor=ACTOR)
    assert cancelled['status'] == 'Cancelled' and cancelled['posted_periods'] == 1
    assert cancelled['cancelled_amount'] == Decimal('1100.00') and cancelled['pending_amount'] == 0
    assert cancelled['periods'][0] == posted['periods'][0]
    assert all(p['status'] == 'Cancelled' for p in cancelled['periods'][1:])
    assert db.rows('SELECT * FROM gl_entries ORDER BY id') == entries
    assert account_balance(db, oid, 'PERIODISED_PURCHASES') == Decimal('1100.00')
    assert service.cancel(oid, schedule['id'], actor=ACTOR) == cancelled
    assert service.run_due(oid) == []
    with pytest.raises(ValueError):
        service.post_due(oid, schedule['id'], actor=ACTOR)


def test_cancel_before_bill_approval_keeps_normal_bill(db, purchase, monkeypatch):
    service, oid, bill, _ = purchase
    monkeypatch.setattr('periodisation.current_day', lambda: '2026-01-01')
    schedule = create(purchase)
    service.cancel(oid, schedule['id'], actor=ACTOR)
    DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
    assert account_balance(db, oid, 'EXPENSE') == Decimal('1200.01')
    assert account_balance(db, oid, 'PERIODISED_PURCHASES') == 0


def test_locked_periods_and_failure_rollback(db, purchase, monkeypatch):
    service, oid, bill, _ = purchase
    schedule = create(purchase)
    DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
    with db.transaction() as tx:
        tx.execute("UPDATE fiscal_periods SET status='Locked' WHERE organisation_id=? AND starts_on='2026-02-01'", (oid,))
    monkeypatch.setattr('periodisation.current_day', lambda: '2026-02-28')
    before = {t: db.rows(f'SELECT * FROM {t} ORDER BY id') for t in ['gl_entries', 'posting_batches', 'audit_events', 'purchase_schedule_periods']}
    with pytest.raises(ValueError, match='locked'):
        service.post_due(oid, schedule['id'], actor=ACTOR)
    assert {t: db.rows(f'SELECT * FROM {t} ORDER BY id') for t in before} == before
    with db.transaction() as tx:
        tx.execute("UPDATE fiscal_periods SET status='Open' WHERE organisation_id=?", (oid,))
    from periodisation_repository import PeriodisationRepository
    monkeypatch.setattr(PeriodisationRepository, 'posted', lambda *args: (_ for _ in ()).throw(RuntimeError('Synthetic link failure')))
    with pytest.raises(RuntimeError):
        service.post_due(oid, schedule['id'], actor=ACTOR)
    assert {t: db.rows(f'SELECT * FROM {t} ORDER BY id') for t in before} == before


def test_posted_bill_locked_reclassification_and_reversal_guards(db, purchase):
    service, oid, bill, _ = purchase
    bill = DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
    with db.transaction() as tx:
        tx.execute("UPDATE fiscal_periods SET status='Locked' WHERE organisation_id=? AND starts_on='2026-01-01'", (oid,))
    with pytest.raises(ValueError, match='locked'):
        create(purchase, start_period='2026-02-28', number_of_periods=11)
    assert service.list(oid) == []
    with db.transaction() as tx:
        tx.execute("UPDATE fiscal_periods SET status='Open' WHERE organisation_id=?", (oid,))
    LedgerService(db).reverse(bill['posting_batch_id'], reversal_date='2026-01-31', actor=ACTOR)
    with pytest.raises(ValueError, match='unreversed'):
        create(purchase)
    assert service.list(oid) == []


def test_source_currency_tax_and_account_guards(db, purchase):
    service, oid, bill, data = purchase
    account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (oid,))
    with pytest.raises(ValueError):
        create(purchase, expense_account_id=account)
    for column, value in [('document_type', 'supplier_credit')]:
        with db.transaction() as tx:
            tx.execute(f'UPDATE bills SET {column}=? WHERE organisation_id=? AND id=?', (value, oid, bill['id']))
        with pytest.raises(ValueError):
            create(purchase)
        with db.transaction() as tx:
            tx.execute(f'UPDATE bills SET {column}=? WHERE organisation_id=? AND id=?', (bill[column], oid, bill['id']))
    with db.transaction() as tx:
        tx.execute('UPDATE bill_lines SET recoverable_tax=0 WHERE bill_id=?', (bill['id'],))
    with pytest.raises(ValueError, match='recoverable'):
        create(purchase)


def test_concurrent_period_posting_is_idempotent(db, purchase):
    service, oid, bill, _ = purchase
    schedule = create(purchase)
    DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.post_due(oid, schedule['id'], actor=ACTOR), range(2)))
    assert results[0] == results[1]
    assert db.scalar("SELECT COUNT(*) FROM posting_batches WHERE organisation_id=? AND voucher_type='purchase_period'", (oid,)) == 1


def test_tenant_scope_and_composite_constraints(db, purchase, uk_org):
    service, oid, bill, data = purchase
    schedule = create(purchase)
    foreign = uk_org['id']
    account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='EXPENSE'", (foreign,))
    assert service.list(foreign) == []
    for method in ['get', 'update', 'post_due', 'cancel']:
        with pytest.raises(KeyError):
            getattr(service, method)(foreign, schedule['id'], **({} if method == 'get' else {'actor': ACTOR}))
    with pytest.raises(KeyError):
        service.create(foreign, actor=ACTOR, **data)
    with pytest.raises(ValueError):
        create(purchase, bill_id=DocumentService(db).create_bill(oid,
            contact_id=bill['contact_id'], supplier_number='SYNTHETIC-002', bill_date='2026-01-01', due_date='2026-01-31',
            actor=ACTOR, lines=[dict(account_id=data['expense_account_id'], unit_price='1200.01')])['id'], expense_account_id=account)
    for column in ['expense_account_id', 'deferred_account_id']:
        with pytest.raises(sqlite3.IntegrityError), db.transaction() as tx:
            tx.execute(f'UPDATE purchase_schedules SET {column}=? WHERE organisation_id=? AND id=?', (account, oid, schedule['id']))
    for sql in ["UPDATE purchase_schedule_periods SET status='Posted' WHERE schedule_id=?",
                "UPDATE purchase_schedule_periods SET vat_amount=1 WHERE schedule_id=?",
                "UPDATE purchase_schedule_periods SET net_amount=-1 WHERE schedule_id=?",
                "UPDATE purchase_schedules SET status='Bad' WHERE id=?"]:
        with pytest.raises(sqlite3.IntegrityError), db.transaction() as tx:
            tx.execute(sql, (schedule['id'],))
    assert db.rows('PRAGMA foreign_key_check') == []


@pytest.mark.parametrize('country', ['UK', 'EE'])
@pytest.mark.parametrize('existing_role', [False, True])
def test_upgrade_preserves_data_and_custom_chart(tmp_path, monkeypatch, country, existing_role):
    import database
    import organisations
    original = database.MIGRATIONS
    previous = tmp_path / 'previous' / 'sqlite'
    previous.mkdir(parents=True)
    for file in (original / 'sqlite').glob('*.sql'):
        if file.stem < '0021':
            shutil.copyfile(file, previous / file.name)
    monkeypatch.setattr(database, 'MIGRATIONS', previous.parent)
    for chart in ['UK_ACCOUNTS', 'EE_ACCOUNTS']:
        monkeypatch.setattr(organisations, chart, tuple(r for r in getattr(organisations, chart) if r[4] != 'PERIODISED_PURCHASES'))
    db = Database(path=str(tmp_path / 'upgrade.sqlite'))
    db.migrate()
    org = organisations.OrganisationService(db).create(name='Synthetic preserved company', country_code=country,
        entity_type='UK_COMPANY' if country == 'UK' else 'EE_OU', owner_email=ACTOR)
    oid = org['id']
    docs = DocumentService(db)
    supplier = docs.create_contact(oid, name='Synthetic preserved supplier', country_code=country, contact_type='supplier')
    expense = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='EXPENSE'", (oid,))
    ap = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='AP'", (oid,))
    bill = docs.create_bill(oid, contact_id=supplier['id'], supplier_number='SYNTHETIC-PRESERVED',
        bill_date='2026-01-01', due_date='2026-01-31', actor=ACTOR, lines=[dict(account_id=expense, unit_price='10')])
    batch = LedgerService(db).post(organisation_id=oid, voucher_type='bill', voucher_id=bill['id'],
        voucher_code=bill['supplier_number'], posting_date=bill['bill_date'], actor=ACTOR, currency=org['base_currency'],
        lines=[PostingLine(expense, debit=Decimal('10')), PostingLine(ap, credit=Decimal('10'))])
    with db.transaction() as tx:
        tx.execute("UPDATE bills SET status='Approved',posting_batch_id=? WHERE organisation_id=? AND id=?", (batch['id'], oid, bill['id']))
    preferred = 1400 if country == 'UK' else 1320
    with db.transaction() as tx:
        for offset in [0, 1]:
            tx.execute("INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance) VALUES (?,?,?,'Custom','Asset','Debit')", (new_id(), oid, str(preferred + offset)))
        if existing_role:
            tx.execute("INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) VALUES (?,?,?,'Custom deferred','Asset','Debit','PERIODISED_PURCHASES')", (new_id(), oid, '9999'))
    before = {t: db.rows(f'SELECT * FROM {t} ORDER BY id') for t in ['organisations', 'accounts', 'contacts', 'bills', 'gl_entries', 'posting_batches', 'audit_events']}
    monkeypatch.setattr(database, 'MIGRATIONS', original)
    assert db.migrate() == ['0021_periodisation', '0022_payment_links', '0023_analytical_objects', '0024_reminder_rules', '0025_fx_realised', '0026_fx_revaluations', '0027_mfa', '0028_document_settings', '0029_copilot', '0030_master_data_maintenance', '0031_master_data_groups', '0032_copilot_access', '0033_copilot_settings', '0034_payroll_demo_fixes', '0035_payroll_income_line', '0036_payroll_component_catalogue', '0037_employee_tax_settings', '0038_payroll_payday_rules', '0039_payroll_payouts', '0040_payroll_settlement_dates', '0041_payroll_sepa_details'] and db.migrate() == []
    organisations_now = db.rows("SELECT * FROM organisations ORDER BY id")
    assert all(row.pop('copilot_enabled') == 0 for row in organisations_now)
    for row in organisations_now:
        row.pop('language', None)
    for table, rows in before.items():
        if table == 'accounts':
            assert all(r in db.rows('SELECT * FROM accounts') for r in rows)
        elif table == 'organisations':
            assert organisations_now == rows
        elif table == 'contacts':
            contacts_now = db.rows('SELECT * FROM contacts ORDER BY id')
            assert all(row.pop('active') == 1 for row in contacts_now)
            assert contacts_now == rows  # active added by 0030_master_data_maintenance
        else:
            assert db.rows(f'SELECT * FROM {table} ORDER BY id') == rows
    assert db.scalar("SELECT code FROM accounts WHERE organisation_id=? AND system_role='PERIODISED_PURCHASES'", (oid,)) == ('9999' if existing_role else str(preferred + 2))
    with db.transaction() as tx:
        tx.connection.executescript((original / 'sqlite' / '0021_periodisation.sql').read_text(encoding='utf-8'))
    assert db.scalar("SELECT COUNT(*) FROM accounts WHERE organisation_id=? AND system_role='PERIODISED_PURCHASES'", (oid,)) == 1
    assert db.rows('PRAGMA foreign_key_check') == []
    service = PeriodisationService(db)
    assert service.create(oid, actor=ACTOR, bill_id=bill['id'], expense_account_id=expense,
        start_period='2026-01-31', number_of_periods=1)['net_amount'] == Decimal('10.00')


def test_api_roles_csrf_workflow(db, purchase, uk_org, monkeypatch):
    from api_app import api, User, current_user, require_csrf
    service, oid, bill, data = purchase
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    reset_database_cache()
    with db.transaction() as tx:
        for role in ['viewer', 'approver', 'accountant', 'administrator']:
            tx.execute('INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)',
                (new_id(), oid, role + '@example.test', role, utc_now()))
    base = f'/organisations/{oid}/purchase-schedules'
    with TestClient(api, headers={'X-Test-User': ACTOR}) as client:
        response = client.post(base, json=data | {'status': 'Draft'})
        assert response.status_code == 201, response.text
        schedule = response.json()
        assert schedule['net_amount'] == '1200.01' and schedule['periods'][0]['vat_amount'] == '0.00'
        url = base + '/' + schedule['id']
        for role in ['viewer', 'approver']:
            headers = {'X-Test-User': role + '@example.test'}
            assert client.get(base, headers=headers).status_code == 200
            assert client.get(url, headers=headers).status_code == 200
            assert client.post(base, headers=headers, json=data).status_code == 403
            assert client.patch(url, headers=headers, json={'status': 'Active'}).status_code == 403
            for action in ['/post', '/cancel']:
                assert client.post(url + action, headers=headers).status_code == 403
        assert client.get(url, headers={'X-Test-User': 'outsider@example.test'}).status_code == 403
        foreign = f"/organisations/{uk_org['id']}/purchase-schedules/{schedule['id']}"
        assert client.get(foreign).status_code == 404
        for action in ['/post', '/cancel']:
            assert client.post(foreign + action).status_code == 404
        assert client.patch(url, json={'notes': None}).status_code == 422
        assert client.patch(url, json={'amount': '1'}).status_code == 422
        assert client.patch(url, headers={'X-Test-User': 'accountant@example.test'}, json={'status': 'Active'}).json()['status'] == 'Active'
        assert client.post(url + '/post').status_code == 422
        DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
        assert client.post(url + '/post', json={'period_id': schedule['periods'][0]['id']}).json()['posted_periods'] == 1
        assert client.post(url + '/post').json()['posted_periods'] == 1
        assert client.post(url + '/cancel', headers={'X-Test-User': 'administrator@example.test'}).json()['status'] == 'Cancelled'
    for route in [r for r in api.routes if '/purchase-schedules' in r.path]:
        assert (current_user if route.methods == {'GET'} else require_csrf) in [d.call for d in route.dependant.dependencies]
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        from web_app import app
        with TestClient(app) as client:
            token = client.get('/api/csrf').json()['csrf_token']
            for method, endpoint, payload in [('POST', base, data), ('PATCH', url, {'status': 'Active'}), ('POST', url+'/post', None), ('POST', url+'/cancel', None)]:
                assert client.request(method, '/api'+endpoint, json=payload).status_code == 403
            assert client.post('/api'+url+'/cancel', headers={'X-CSRF-Token': token}).status_code == 200
    finally:
        api.dependency_overrides.clear()
        reset_database_cache()


def test_worker_tick_failure_isolation(db, purchase, monkeypatch):
    from automation import AutomationService
    service, oid, bill, data = purchase
    first = create(purchase)
    second_bill = DocumentService(db).create_bill(oid, contact_id=bill['contact_id'], supplier_number='SYNTHETIC-002',
        bill_date='2026-01-01', due_date='2026-01-31', actor=ACTOR,
        lines=[dict(account_id=data['expense_account_id'], unit_price='12')])
    second = service.create(oid, actor=ACTOR, **(data | {'bill_id': second_bill['id'], 'amount': '12'}))
    DocumentService(db).approve_bill(second_bill['id'], actor=ACTOR)
    result = AutomationService(db).worker_tick(today='2026-01-31')
    assert {r['schedule_id']: r['status'] for r in result['periodisation']} == {first['id']: 'Failed', second['id']: 'Posted'}
    assert service.get(oid, second['id'])['posted_periods'] == 1
    monkeypatch.setattr(PeriodisationService, 'run_due', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('Synthetic worker failure')))
    result = AutomationService(db).worker_tick(today='2026-01-31')
    assert any(e['operation'] == 'periodisation' and e['organisation_id'] == oid for e in result['errors'])


def test_locale_additions_are_at_file_end_and_do_not_override_existing_keys():
    import json
    from web import i18n
    for language in ['en', 'et', 'lt', 'lv']:
        name = f'web/locales/{language}.json'
        current = Path(name).read_text(encoding='utf-8')
        new = json.loads(current)
        assert list(new)[-(10):] == ['periodisation', 'payment_links', 'analytical_objects', 'invoice_exports', 'bulk_sending', 'reminder_rules', 'fx_rates', 'document_settings', 'copilot', 'periods']
        for section, values in new['periodisation'].items():
            assert not (values.keys() & new[section].keys())
        assert i18n.catalog(language)['nav']['periodised'] == i18n.catalog(language)['workspace']['Periodised']


@pytest.mark.parametrize('country', ['UK', 'EE'])
@pytest.mark.parametrize('vat', [False, True])
def test_country_charts_single_period_and_vat(db, uk_org, ee_org, monkeypatch, country, vat):
    org = uk_org if country == 'UK' else ee_org
    oid = org['id']
    docs = DocumentService(db)
    supplier = docs.create_contact(oid, name='Synthetic supplier', country_code=country, contact_type='supplier')
    expense = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='EXPENSE'", (oid,))
    tax = db.scalar("SELECT id FROM tax_codes WHERE organisation_id=? AND kind='standard' AND active=1", (oid,)) if vat else None
    bill = docs.create_bill(oid, actor=ACTOR, contact_id=supplier['id'], supplier_number='SYNTHETIC-COUNTRY',
        bill_date='2026-01-01', due_date='2026-01-31', lines=[dict(account_id=expense, unit_price='1.01', tax_code_id=tax)])
    service = PeriodisationService(db)
    monkeypatch.setattr('periodisation.current_day', lambda: '2026-01-31')
    schedule = service.create(oid, actor=ACTOR, bill_id=bill['id'], expense_account_id=expense,
        start_period='2026-01-31', number_of_periods=1)
    docs.approve_bill(bill['id'], actor=ACTOR)
    completed = service.post_due(oid, schedule['id'], actor=ACTOR)
    assert completed['status'] == 'Completed'
    assert account_balance(db, oid, 'PERIODISED_PURCHASES') == 0
    assert account_balance(db, oid, 'EXPENSE') == Decimal('1.01')
    assert account_balance(db, oid, 'INPUT_VAT') == money(bill['tax_total'])
    assert account_balance(db, oid, 'AP') == -money(bill['total'])
    with pytest.raises(ValueError, match='Completed'):
        service.cancel(oid, schedule['id'], actor=ACTOR)


def test_tiny_amount_and_inactive_accounts(db, purchase):
    service, oid, bill, data = purchase
    tiny = DocumentService(db).create_bill(oid, actor=ACTOR, contact_id=bill['contact_id'], supplier_number='SYNTHETIC-TINY',
        bill_date='2026-01-01', due_date='2026-01-31', lines=[dict(account_id=data['expense_account_id'], unit_price='0.01')])
    with pytest.raises(ValueError, match='penny or cent'):
        create(purchase, bill_id=tiny['id'], amount='0.01')
    for role in ['EXPENSE', 'PERIODISED_PURCHASES']:
        with db.transaction() as tx:
            tx.execute('UPDATE accounts SET active=0 WHERE organisation_id=? AND system_role=?', (oid, role))
        with pytest.raises(ValueError):
            create(purchase)
        with db.transaction() as tx:
            tx.execute('UPDATE accounts SET active=1 WHERE organisation_id=? AND system_role=?', (oid, role))
    assert service.list(oid) == []


def test_bill_change_and_locked_approval_preserve_schedule(db, purchase):
    service, oid, bill, _ = purchase
    schedule = create(purchase)
    with db.transaction() as tx:
        tx.execute("UPDATE fiscal_periods SET status='Locked' WHERE organisation_id=? AND starts_on='2026-01-01'", (oid,))
    with pytest.raises(ValueError, match='locked'):
        DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
    assert service.get(oid, schedule['id'])['funding_batch_id'] is None
    assert not db.rows('SELECT * FROM gl_entries')
    with db.transaction() as tx:
        tx.execute("UPDATE fiscal_periods SET status='Open' WHERE organisation_id=?", (oid,))
        tx.execute("UPDATE bills SET document_type='supplier_credit' WHERE organisation_id=? AND id=?", (oid, bill['id']))
    with pytest.raises(ValueError, match='no longer matches'):
        DocumentService(db).approve_bill(bill['id'], actor=ACTOR)
    assert not db.rows('SELECT * FROM gl_entries')


def test_multiple_expense_accounts_paid_bill_and_reversed_funding(db, purchase):
    service, oid, bill, data = purchase
    cost = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='COST_OF_SALES'", (oid,))
    other = DocumentService(db).create_bill(oid, actor=ACTOR, contact_id=bill['contact_id'], supplier_number='SYNTHETIC-MULTI',
        bill_date='2026-01-01', due_date='2026-01-31', lines=[dict(account_id=cost, unit_price='10'),
            dict(account_id=data['expense_account_id'], unit_price='20')])
    DocumentService(db).approve_bill(other['id'], actor=ACTOR)
    with db.transaction() as tx:
        tx.execute("UPDATE bills SET status='Paid',paid_total=total WHERE organisation_id=? AND id=?", (oid, other['id']))
    schedule = create(purchase, bill_id=other['id'], amount='30')
    assert account_balance(db, oid, 'COST_OF_SALES') == 0 and account_balance(db, oid, 'EXPENSE') == 0
    assert account_balance(db, oid, 'PERIODISED_PURCHASES') == 30
    LedgerService(db).reverse(schedule['funding_batch_id'], reversal_date='2026-01-31', actor=ACTOR)
    with pytest.raises(ValueError, match='unreversed'):
        service.post_due(oid, schedule['id'], actor=ACTOR)
    assert service.get(oid, schedule['id'])['posted_periods'] == 0
