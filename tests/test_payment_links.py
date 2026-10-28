"""Offline payment URLs, tenancy, access controls and additive migration checks."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import secrets
import shutil
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from core_utils import new_id, utc_now
from database import Database, reset_database_cache
from documents import DocumentService
from payment_links import PaymentLinkService

ACTOR = 'owner@example.test'
TEMPLATE = 'https://pay.example.test/{token}?total={invoice_total}&due={invoice_due}&number={invoice_number}&id={invoice_id}&currency={currency}'
CONFIG = dict(provider='everypay', name='Synthetic EveryPay', url_template=TEMPLATE, enabled=True, currency='EUR')


@pytest.fixture
def sale(db, ee_org):
    oid = ee_org['id']
    docs = DocumentService(db)
    contact = docs.create_contact(oid, name='Synthetic customer', country_code='EE', contact_type='customer')
    income = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (oid,))
    invoice = docs.create_invoice(oid, contact_id=contact['id'], issue_date='2026-01-01', actor=ACTOR,
                                  lines=[dict(account_id=income, unit_price='10.01')])
    return PaymentLinkService(db), oid, invoice, docs


@pytest.mark.parametrize('provider', ['everypay', 'linkpay', 'custom'])
def test_exact_amount_idempotency_and_no_postings(db, sale, provider, monkeypatch):
    import httpx
    monkeypatch.setattr(httpx.Client, 'request', lambda *a, **k: pytest.fail('Payment links must stay offline'))
    service, oid, invoice, docs = sale
    method = service.create_config(oid, actor=ACTOR, **(CONFIG | {'provider': provider}))
    assert service.invoice_links(oid, invoice['id']) == []
    with pytest.raises(ValueError, match='unpaid issued'):
        service.generate(oid, invoice['id'], method['id'])
    invoice = docs.issue_invoice(invoice['id'], actor=ACTOR)
    before = db.rows('SELECT * FROM gl_entries ORDER BY id')
    first = service.generate(oid, invoice['id'], method['id'])
    assert service.generate(oid, invoice['id'], method['id']) == first
    assert service.invoice_links(oid, invoice['id']) == [first]
    params = parse_qs(urlsplit(first['url']).query)
    assert params == dict(total=['10.01'], due=['10.01'], number=[invoice['number']], id=[invoice['id']], currency=['EUR'])
    assert len(first['token']) >= 43
    assert first['url'].startswith('https://pay.example.test/' + first['token'])
    assert service.invoice_payload(oid, invoice['id'])['payment_links'] == [first]
    assert db.rows('SELECT * FROM gl_entries ORDER BY id') == before
    assert docs.invoice(invoice['id']) == invoice


def test_refresh_disable_and_concurrent_generation(db, sale):
    service, oid, invoice, docs = sale
    method = service.create_config(oid, actor=ACTOR, **CONFIG)
    docs.issue_invoice(invoice['id'], actor=ACTOR)
    with ThreadPoolExecutor(max_workers=2) as pool:
        links = list(pool.map(lambda _: service.generate(oid, invoice['id'], method['id']), range(2)))
    assert links[0] == links[1]
    assert db.scalar('SELECT COUNT(*) FROM invoice_payment_links') == 1
    service.update_config(oid, method['id'], actor=ACTOR, url_template='https://other.example.test/{token}?amount={invoice_due}')
    updated = service.generate(oid, invoice['id'], method['id'])
    assert updated['token'] == links[0]['token'] and updated['id'] == links[0]['id']
    assert updated['url'] == 'https://other.example.test/' + updated['token'] + '?amount=10.01'
    service.update_config(oid, method['id'], actor=ACTOR, enabled=False)
    assert service.invoice_links(oid, invoice['id']) == []
    with pytest.raises(ValueError, match='disabled'):
        service.generate(oid, invoice['id'], method['id'])
    service.update_config(oid, method['id'], actor=ACTOR, enabled=True)
    assert service.generate(oid, invoice['id'], method['id'])['token'] == updated['token']


def test_currency_guard_multiple_methods_and_encoding(db, sale):
    service, oid, invoice, docs = sale
    mismatch = service.create_config(oid, actor=ACTOR, **(CONFIG | {'currency': 'GBP'}))
    matching = service.create_config(oid, actor=ACTOR, **CONFIG)
    any_currency = service.create_config(oid, actor=ACTOR, **(CONFIG | {'provider': 'custom', 'currency': ''}))
    docs.issue_invoice(invoice['id'], actor=ACTOR)
    with pytest.raises(ValueError, match='currency'):
        service.generate(oid, invoice['id'], mismatch['id'])
    assert {l['method_id'] for l in service.invoice_links(oid, invoice['id'])} == {matching['id'], any_currency['id']}
    # Exercise escaping without modifying immutable issued document fields.
    with db.transaction() as tx:
        from payment_links_repository import PaymentLinkRepository
        row = PaymentLinkRepository(tx, oid).invoice(invoice['id']) | {'number': 'SYNTHETIC & /?õ'}
        result = service._generate(PaymentLinkRepository(tx, oid), row, matching)
    assert parse_qs(urlsplit(result['url']).query)['number'] == ['SYNTHETIC & /?õ']


def test_part_paid_paid_and_credit_note(db, sale):
    service, oid, invoice, docs = sale
    method = service.create_config(oid, actor=ACTOR, **CONFIG)
    docs.issue_invoice(invoice['id'], actor=ACTOR)
    link = service.generate(oid, invoice['id'], method['id'])
    bank = docs.create_bank_account(oid, name='Synthetic bank', currency='EUR')
    docs.record_payment(oid, payment_type='customer_receipt', bank_account_id=bank['id'], payment_date='2026-01-02',
                        contact_id=invoice['contact_id'], amount='2.00', actor=ACTOR,
                        allocations=[dict(document_type='invoice', document_id=invoice['id'], amount='2.00')])
    partial = service.generate(oid, invoice['id'], method['id'])
    assert partial['token'] == link['token']
    assert parse_qs(urlsplit(partial['url']).query)['due'] == ['8.01']
    docs.record_payment(oid, payment_type='customer_receipt', bank_account_id=bank['id'], payment_date='2026-01-03',
                        contact_id=invoice['contact_id'], amount='8.01', actor=ACTOR,
                        allocations=[dict(document_type='invoice', document_id=invoice['id'], amount='8.01')])
    assert service.invoice_links(oid, invoice['id']) == []
    with pytest.raises(ValueError, match='unpaid issued'):
        service.generate(oid, invoice['id'], method['id'])
    credit = docs.create_invoice(oid, contact_id=invoice['contact_id'], issue_date='2026-01-04', actor=ACTOR,
        document_type='credit_note', original_invoice_id=invoice['id'],
        lines=[dict(account_id=invoice['lines'][0]['account_id'], unit_price='1')])
    docs.issue_invoice(credit['id'], actor=ACTOR)
    assert service.invoice_links(oid, credit['id']) == []


@pytest.mark.parametrize('template', [
    'javascript:alert(1)', 'http://pay.example.test/{token}', '//pay.example.test',
    'https://user:password@pay.example.test', 'https://{invoice_number}.example.test',
    'https://pay.example.test/{unknown}', 'https://pay.example.test/{invoice_id.__class__}',
    'https://pay.example.test/{invoice_total:.2f}', 'https://pay.example.test/{token!r}',
    'https://pay.example.test/{}', 'https://pay.example.test/{', 'https://pay.example.test/a\nb',
    'https://pay.example.test\\evil', 'https://pay.example.test:bad/{token}',
])
def test_unsafe_templates_rejected(sale, template):
    service, oid, _, _ = sale
    with pytest.raises(ValueError):
        service.create_config(oid, actor=ACTOR, **(CONFIG | {'url_template': template}))
    assert service.list_configs(oid) == []


@pytest.mark.parametrize('changes', [{'name': ' '}, {'currency': 'EU'}, {'provider': 'unknown'}, {'enabled': 1}])
def test_invalid_configuration(sale, changes):
    service, oid, _, _ = sale
    with pytest.raises(ValueError):
        service.create_config(oid, actor=ACTOR, **(CONFIG | changes))


def test_tenancy_and_composite_foreign_keys(db, sale, uk_org):
    service, oid, invoice, docs = sale
    foreign = uk_org['id']
    method = service.create_config(oid, actor=ACTOR, **CONFIG)
    foreign_method = service.create_config(foreign, actor=ACTOR, **CONFIG)
    docs.issue_invoice(invoice['id'], actor=ACTOR)
    link = service.generate(oid, invoice['id'], method['id'])
    with pytest.raises(KeyError):
        service.update_config(foreign, method['id'], actor=ACTOR, name='Other')
    with pytest.raises(KeyError):
        service.invoice_links(foreign, invoice['id'])
    with pytest.raises(KeyError):
        service.generate(oid, invoice['id'], foreign_method['id'])
    for column, value in [('method_id', foreign_method['id']), ('organisation_id', foreign)]:
        with pytest.raises(sqlite3.IntegrityError), db.transaction() as tx:
            tx.execute(f'UPDATE invoice_payment_links SET {column}=? WHERE organisation_id=? AND id=?', (value, oid, link['id']))
    assert db.rows('PRAGMA foreign_key_check') == []
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as tx:
        tx.execute('INSERT INTO invoice_payment_links(id,organisation_id,invoice_id,method_id,token,url,created_at,updated_at) '
                   'VALUES (?,?,?,?,?,?,?,?)', (new_id(), oid, invoice['id'], method['id'], secrets.token_urlsafe(32), link['url'], utc_now(), utc_now()))


def test_api_roles_csrf_and_payload(db, sale, uk_org, monkeypatch):
    from api_app import api, User, current_user, require_csrf
    service, oid, invoice, docs = sale
    docs.issue_invoice(invoice['id'], actor=ACTOR)
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    reset_database_cache()
    with db.transaction() as tx:
        for role in ['viewer', 'approver', 'accountant', 'administrator']:
            tx.execute('INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)',
                       (new_id(), oid, role + '@example.test', role, utc_now()))
    base = f'/organisations/{oid}/payment-methods'
    invoice_url = f"/organisations/{oid}/invoices/{invoice['id']}"
    with TestClient(api, headers={'X-Test-User': ACTOR}) as client:
        assert client.get(invoice_url + '.pdf').content.startswith(b'%PDF')
        assert client.get(invoice_url + '.xml').status_code == 200
        response = client.post(base, json=CONFIG)
        assert response.status_code == 201, response.text
        url = base + '/' + response.json()['id']
        for role in ['viewer', 'approver', 'accountant']:
            headers = {'X-Test-User': role + '@example.test'}
            assert client.get(base, headers=headers).status_code == 200
            assert client.get(invoice_url, headers=headers).json()['payment_links']
            assert client.get(invoice_url + '/payment-links', headers=headers).status_code == 200
            assert client.post(base, headers=headers, json=CONFIG).status_code == 403
            assert client.patch(url, headers=headers, json={'enabled': False}).status_code == 403
        assert client.patch(url, headers={'X-Test-User': 'administrator@example.test'}, json={'name': 'Edited'}).status_code == 200
        assert client.post(base, json=CONFIG | {'credentials': 'forbidden'}).status_code == 422
        assert client.patch(url, json={'enabled': None}).status_code == 422
        assert client.patch(url, json={'extra': True}).status_code == 422
        assert client.get(base, headers={'X-Test-User': 'outsider@example.test'}).status_code == 403
        assert client.get(invoice_url.replace(oid, uk_org['id'])).status_code == 404
        assert client.patch(url.replace(oid, uk_org['id']), json={'name': 'Foreign'}).status_code == 404
    for route in [r for r in api.routes if '/payment-methods' in r.path or '/payment-links' in r.path]:
        assert (current_user if route.methods == {'GET'} else require_csrf) in [d.call for d in route.dependant.dependencies]
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        from web_app import app
        with TestClient(app) as client:
            token = client.get('/api/csrf').json()['csrf_token']
            assert client.post('/api' + base, json=CONFIG).status_code == 403
            assert client.patch('/api' + url, json={'enabled': False}).status_code == 403
            assert client.patch('/api' + url, json={'enabled': False}, headers={'X-CSRF-Token': token}).status_code == 200
            assert client.get('/api' + invoice_url).json()['payment_links'] == []
    finally:
        api.dependency_overrides.clear()
        reset_database_cache()


def test_upgrade_and_rerun_preserve_existing_data(tmp_path, monkeypatch):
    import database
    from organisations import OrganisationService
    original = database.MIGRATIONS
    previous = tmp_path / 'previous' / 'sqlite'
    previous.mkdir(parents=True)
    for file in (original / 'sqlite').glob('*.sql'):
        if file.stem < '0022':
            shutil.copyfile(file, previous / file.name)
    monkeypatch.setattr(database, 'MIGRATIONS', previous.parent)
    db = Database(path=str(tmp_path / 'upgrade.sqlite'))
    db.migrate()
    org = OrganisationService(db).create(name='Synthetic company', country_code='EE', entity_type='EE_OU', owner_email=ACTOR)
    docs = DocumentService(db)
    contact = docs.create_contact(org['id'], name='Synthetic customer', country_code='EE')
    income = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (org['id'],))
    invoice = docs.create_invoice(org['id'], contact_id=contact['id'], issue_date='2026-01-01', actor=ACTOR,
                                  lines=[dict(account_id=income, unit_price='12.34')])
    docs.issue_invoice(invoice['id'], actor=ACTOR)
    tables = ['organisations', 'accounts', 'contacts', 'invoices', 'invoice_lines', 'posting_batches', 'gl_entries', 'audit_events']
    before = {table: db.rows(f'SELECT * FROM {table} ORDER BY id') for table in tables}
    monkeypatch.setattr(database, 'MIGRATIONS', original)
    assert db.migrate() == ['0022_payment_links', '0023_analytical_objects', '0024_reminder_rules', '0025_fx_realised', '0026_fx_revaluations', '0027_mfa', '0028_document_settings', '0029_copilot', '0030_master_data_maintenance', '0031_master_data_groups', '0032_copilot_access', '0033_copilot_settings', '0034_payroll_demo_fixes', '0035_payroll_income_line', '0036_payroll_component_catalogue', '0037_employee_tax_settings', '0038_payroll_payday_rules', '0039_payroll_payouts', '0040_payroll_settlement_dates', '0041_payroll_sepa_details', '0042_payroll_component_metadata', '0043_payroll_absences'] and db.migrate() == []
    service = PaymentLinkService(db)
    method = service.create_config(org['id'], actor=ACTOR, **CONFIG)
    link = service.generate(org['id'], invoice['id'], method['id'])
    with db.transaction() as tx:
        tx.connection.executescript((original / 'sqlite' / '0022_payment_links.sql').read_text(encoding='utf-8'))
    assert service.generate(org['id'], invoice['id'], method['id']) == link
    organisations_now = db.rows('SELECT * FROM organisations')
    assert all(row.pop('copilot_enabled') == 0 for row in organisations_now)
    for row in organisations_now:
        row.pop('language', None)
    contacts_now = db.rows('SELECT * FROM contacts')
    assert all(row.pop('active') == 1 for row in contacts_now)  # added by 0030_master_data_maintenance
    for table in tables:
        if table == 'organisations':
            continue
        if table == 'contacts':
            assert contacts_now == before['contacts']
            continue
        assert all(row in db.rows(f'SELECT * FROM {table}') for row in before[table])
    assert organisations_now == before['organisations']
    assert db.rows('PRAGMA foreign_key_check') == []


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_append_only_locale_merge(language):
    from web import i18n
    path = f'web/locales/{language}.json'
    raw = Path(path).read_text(encoding='utf-8')
    data = json.loads(raw)
    assert list(data)[-(9):] == ['payment_links', 'analytical_objects', 'invoice_exports', 'bulk_sending', 'reminder_rules', 'fx_rates', 'document_settings', 'copilot', 'periods']
    for section, additions in data['payment_links'].items():
        assert not additions.keys() & data[section].keys()
        for key, value in additions.items():
            assert i18n.catalog(language)[section][key] == value
    assert i18n.t('nav.payment_methods', language) == i18n.catalog(language)['workspace']['Payment methods']
    assert i18n.t('workspace.Payment link', language) != 'workspace.Payment link'
    assert i18n.t('nav.periodised', language) == i18n.catalog(language)['workspace']['Periodised']
    assert '\u2014' not in json.dumps(data['payment_links'], ensure_ascii=False)
