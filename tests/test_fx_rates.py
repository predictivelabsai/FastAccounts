"""Offline rate maintenance and gain/loss-free booking acceptance checks."""
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from core_utils import decimal, money
from documents import DocumentService
from exchange_rates import ExchangeRateService, resolve_rate
from ledger import LedgerService, PostingLine
from test_bulk_sending import ACTOR, sending

RATE = dict(rate_date='2026-01-10', from_currency='USD', to_currency='EUR', rate='1.10')


def url(data):
    return f"/organisations/{data['oid']}/exchange-rates"


def test_crud_duplicate_audit_and_isolation(sending):
    d = sending
    result = d['client'].post(url(d), json=RATE)
    assert result.status_code == 201, result.text
    row = result.json()
    assert row['source'] == 'manual' and row['organisation_id'] == d['oid']
    assert decimal(row['rate']) == Decimal('1.10')
    assert d['client'].get(url(d)).json() == [row]
    duplicate = d['client'].post(url(d), json=RATE)
    assert duplicate.status_code == 422
    assert 'already exists' in duplicate.text
    assert d['db'].scalar("SELECT COUNT(*) FROM audit_events WHERE action='exchange_rate.created'") == 1
    foreign = f"/organisations/{d['other']['id']}/exchange-rates"
    assert d['client'].get(foreign).json() == []
    assert d['client'].delete(foreign + '/' + row['id']).status_code == 404
    assert d['client'].delete(url(d) + '/' + row['id']).json() == {'deleted': True}
    assert d['client'].delete(url(d) + '/' + row['id']).status_code == 404
    assert d['client'].get(url(d)).json() == []
    events = d['db'].rows("SELECT * FROM audit_events WHERE action LIKE 'exchange_rate.%' ORDER BY action")
    assert [x['action'] for x in events] == ['exchange_rate.created', 'exchange_rate.deleted']
    assert all(x['organisation_id'] == d['oid'] and x['actor'] == ACTOR for x in events)
    assert d['client'].post(url(d), json=RATE).status_code == 201


@pytest.mark.parametrize('role', ['owner', 'administrator', 'accountant', 'approver', 'viewer', 'outsider'])
def test_roles_and_foreign_organisation(sending, role):
    d = sending
    row = d['client'].post(url(d), json=RATE).json()
    headers = {'X-Test-User': ACTOR if role == 'owner' else role + '@example.test'}
    assert d['client'].get(url(d), headers=headers).status_code == (403 if role == 'outsider' else 200)
    expected = 201 if role in {'owner', 'administrator'} else 403
    assert d['client'].post(url(d), json=RATE | {'rate_date': '2026-01-11'}, headers=headers).status_code == expected
    assert d['client'].delete(url(d) + '/' + row['id'], headers=headers).status_code == (200 if expected == 201 else 403)
    foreign = f"/organisations/{d['other']['id']}/exchange-rates"
    if role != 'owner':
        assert d['client'].get(foreign, headers=headers).status_code == 403
        assert d['client'].post(foreign, json=RATE, headers=headers).status_code == 403
        assert d['client'].delete(foreign + '/' + row['id'], headers=headers).status_code == 403


@pytest.mark.parametrize('patch', [
    {'rate_date': '2026-02-30'}, {'rate_date': '20260110'}, {'rate_date': '2026-1-10'},
    {'from_currency': 'usd'}, {'from_currency': 'US'}, {'to_currency': 'EURO'},
    {'to_currency': 'USD'}, {'rate': '0'}, {'rate': '-1'}, {'rate': 'NaN'},
    {'rate': 'Infinity'}, {'source': 'ecb'}, {'organisation_id': 'foreign'}, {'unexpected': True},
    {'rate': '0.00000000001'}, {'rate': '10000000000'},
])
def test_input_validation(sending, patch):
    d = sending
    assert d['client'].post(url(d), json=RATE | patch).status_code == 422
    assert not d['client'].get(url(d)).json()
    assert not d['db'].rows("SELECT * FROM audit_events WHERE action LIKE 'exchange_rate.%'")


def test_auth_and_csrf(sending):
    from api_app import api, current_user, require_csrf, User
    from web_app import app
    d = sending
    with TestClient(app) as client:
        assert client.get('/api' + url(d)).status_code == 401
        assert client.post('/api' + url(d), json=RATE).status_code == 401
        assert client.delete('/api' + url(d) + '/missing').status_code == 401
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        with TestClient(app) as client:
            token = client.get('/api/csrf').json()['csrf_token']
            for headers in [{}, {'X-CSRF-Token': 'wrong'}]:
                assert client.post('/api' + url(d), json=RATE, headers=headers).status_code == 403
                assert client.delete('/api' + url(d) + '/missing', headers=headers).status_code == 403
            row = client.post('/api' + url(d), json=RATE, headers={'X-CSRF-Token': token}).json()
            assert client.delete('/api' + url(d) + '/' + row['id'], headers={'X-CSRF-Token': token}).status_code == 200
    finally:
        api.dependency_overrides.clear()
    for route in [r for r in api.routes if '/exchange-rates' in r.path]:
        assert (current_user if route.methods == {'GET'} else require_csrf) in [x.call for x in route.dependant.dependencies]


def test_existing_schema_resolution_and_migration_count(db, ee_org, uk_org):
    assert db.scalar('SELECT COUNT(*) FROM schema_migrations') == 29
    service = ExchangeRateService(db)
    for day, value in [('2026-01-01', '1.05'), ('2026-01-10', '1.10'), ('2026-01-20', '1.20')]:
        service.create(ee_org['id'], **(RATE | {'rate_date': day, 'rate': value}), actor=ACTOR)
    service.create(uk_org['id'], **(RATE | {'rate': '9'}), actor=ACTOR)
    service.create(ee_org['id'], **(RATE | {'from_currency': 'EUR', 'to_currency': 'USD', 'rate': '2'}), actor=ACTOR)
    with db.transaction() as tx:
        assert resolve_rate(tx, ee_org['id'], 'USD', 'EUR', '2026-01-15') == Decimal('1.10')
        assert resolve_rate(tx, ee_org['id'], 'USD', 'EUR', '2026-01-10') == Decimal('1.10')
        assert resolve_rate(tx, ee_org['id'], 'USD', 'EUR', '2025-12-31') is None
        assert resolve_rate(tx, ee_org['id'], 'GBP', 'EUR', '2026-01-15') is None
        assert resolve_rate(tx, ee_org['id'], 'EUR', 'USD', '2026-01-15') == Decimal('2')
    service.delete(ee_org['id'], service.list(ee_org['id'])[2]['id'], actor=ACTOR)
    # Deleting the exact-direction row leaves the inverse unusable.
    inverse_only = ExchangeRateService(db)
    for row in inverse_only.list(ee_org['id']):
        if row['from_currency'] == 'USD':
            inverse_only.delete(ee_org['id'], row['id'], actor=ACTOR)
    with db.transaction() as tx:
        assert resolve_rate(tx, ee_org['id'], 'USD', 'EUR', '2026-01-30') is None
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as tx:
        tx.execute("INSERT INTO exchange_rates SELECT 'invalid',organisation_id,rate_date,from_currency,to_currency,0,'other',created_at FROM exchange_rates LIMIT 1")
    db.migrate()
    assert db.scalar('SELECT COUNT(*) FROM schema_migrations') == 29


def setup(db, org):
    docs = DocumentService(db)
    contact = docs.create_contact(org['id'], name='Synthetic foreign customer', country_code='EE')
    accounts = {x['system_role']: x['id'] for x in db.rows('SELECT * FROM accounts WHERE organisation_id=?', (org['id'],))}
    return docs, contact, accounts


def entries(db, document):
    return db.rows('SELECT * FROM gl_entries WHERE posting_batch_id=? ORDER BY line_number', (document['posting_batch_id'],))


@pytest.mark.parametrize('kind', ['invoice', 'credit_note', 'bill', 'supplier_credit'])
@pytest.mark.parametrize('explicit,expected', [(None, '1.10'), (Decimal('1.25'), '1.25')])
def test_document_booking_conversion(db, ee_org, kind, explicit, expected):
    docs, contact, accounts = setup(db, ee_org)
    ExchangeRateService(db).create(ee_org['id'], **RATE, actor=ACTOR)
    sales = kind in {'invoice', 'credit_note'}
    args = dict(contact_id=contact['id'], currency='USD', document_type=kind, actor=ACTOR,
                exchange_rate=explicit, lines=[dict(account_id=accounts['SALES' if sales else 'EXPENSE'], unit_price='10.00')])
    if sales:
        draft = docs.create_invoice(ee_org['id'], issue_date='2026-01-10', **args)
        posted = docs.issue_invoice(draft['id'], actor=ACTOR)
    else:
        draft = docs.create_bill(ee_org['id'], bill_date='2026-01-10', due_date='2026-01-20', supplier_number=kind, **args)
        docs.submit_bill_for_review(draft['id'], actor=ACTOR)
        posted = docs.approve_bill(draft['id'], actor=ACTOR)
    rate = Decimal(expected)
    assert decimal(draft['exchange_rate']) == rate
    assert decimal(posted['total']) == Decimal('10')
    rows = entries(db, posted)
    assert sum(decimal(x['debit']) for x in rows) == sum(decimal(x['credit']) for x in rows) == money(Decimal('10') * rate)
    assert all(x['currency'] == 'EUR' and x['transaction_currency'] == 'USD' and decimal(x['exchange_rate']) == rate for x in rows)
    assert sorted(decimal(x['transaction_amount']) for x in rows) == [Decimal('-10'), Decimal('10')]
    assert all(x['account_id'] in {accounts['AR' if sales else 'AP'], accounts['SALES' if sales else 'EXPENSE']} for x in rows)
    reversed_batch = docs.ledger.reverse(posted['posting_batch_id'], reversal_date='2026-01-11', actor=ACTOR)
    reversal = db.rows('SELECT * FROM gl_entries WHERE posting_batch_id=? ORDER BY line_number', (reversed_batch['id'],))
    assert [(x['debit'], x['credit']) for x in reversal] == [(x['credit'], x['debit']) for x in rows]


@pytest.mark.parametrize('payment_type', ['customer_receipt', 'supplier_payment'])
@pytest.mark.parametrize('explicit,expected', [(None, '1.10'), (Decimal('1.25'), '1.25')])
def test_payment_conversion_and_override(db, ee_org, payment_type, explicit, expected):
    docs, contact, accounts = setup(db, ee_org)
    ExchangeRateService(db).create(ee_org['id'], **RATE, actor=ACTOR)
    bank = docs.create_bank_account(ee_org['id'], name='Synthetic USD bank', currency='USD')
    payment = docs.record_payment(ee_org['id'], payment_type=payment_type, bank_account_id=bank['id'],
                                  contact_id=contact['id'], payment_date='2026-01-10', amount='10', actor=ACTOR, exchange_rate=explicit)
    rows = entries(db, payment)
    assert decimal(payment['amount']) == Decimal('10') and payment['currency'] == 'USD'
    assert sum(decimal(x['debit']) for x in rows) == sum(decimal(x['credit']) for x in rows) == money(Decimal('10') * Decimal(expected))
    assert all(x['currency'] == 'EUR' and x['transaction_currency'] == 'USD' and decimal(x['exchange_rate']) == Decimal(expected) for x in rows)
    assert sorted(decimal(x['transaction_amount']) for x in rows) == [Decimal('-10'), Decimal('10')]


def test_rate_one_identical_and_missing_fallback(db, ee_org):
    docs, contact, accounts = setup(db, ee_org)
    lines = [PostingLine(accounts['AR'], debit=Decimal('10.125')), PostingLine(accounts['SALES'], credit=Decimal('10.125'))]
    baseline = docs.ledger.post(organisation_id=ee_org['id'], voucher_type='test', voucher_id='baseline', voucher_code='BASE',
                               posting_date='2026-01-10', lines=lines, actor=ACTOR, currency='EUR')
    explicit = docs.ledger.post(organisation_id=ee_org['id'], voucher_type='test', voucher_id='explicit', voucher_code='EXPLICIT',
                               posting_date='2026-01-10', lines=lines, actor=ACTOR, currency='EUR', exchange_rate=Decimal('1'))
    fields = 'account_id,debit,credit,currency,transaction_amount,transaction_currency,exchange_rate'
    get = lambda batch: db.rows(f'SELECT {fields} FROM gl_entries WHERE posting_batch_id=? ORDER BY line_number', (batch['id'],))
    assert get(baseline) == get(explicit)
    stored = get(baseline)[0]
    assert decimal(stored['debit']) == decimal(stored['transaction_amount']) == Decimal('10.13')
    assert stored['account_id'] == accounts['AR'] and stored['currency'] == stored['transaction_currency'] == 'EUR'
    assert decimal(stored['credit']) == 0 and decimal(stored['exchange_rate']) == 1
    draft = docs.create_invoice(ee_org['id'], contact_id=contact['id'], currency='USD', issue_date='2026-01-10', actor=ACTOR,
                                lines=[dict(account_id=accounts['SALES'], unit_price='10')])
    assert decimal(draft['exchange_rate']) == 1
    assert entries(db, docs.issue_invoice(draft['id'], actor=ACTOR))[0]['currency'] == 'EUR'


@pytest.mark.parametrize('rate', [Decimal('0'), Decimal('-1'), Decimal('NaN'), Decimal('Infinity')])
def test_invalid_posting_rate_atomic(db, ee_org, rate):
    docs, contact, accounts = setup(db, ee_org)
    with pytest.raises(ValueError, match='positive'):
        docs.create_invoice(ee_org['id'], contact_id=contact['id'], currency='USD', issue_date='2026-01-10', actor=ACTOR,
                            exchange_rate=rate, lines=[dict(account_id=accounts['SALES'], unit_price='10')])
    with pytest.raises(ValueError, match='positive'):
        LedgerService(db).post(organisation_id=ee_org['id'], voucher_type='test', voucher_id='bad', voucher_code='BAD',
                              posting_date='2026-01-10', actor=ACTOR, currency='USD', exchange_rate=rate,
                              lines=[PostingLine(accounts['AR'], debit=Decimal('10')), PostingLine(accounts['SALES'], credit=Decimal('10'))])
    assert not db.rows('SELECT * FROM invoices') and not db.rows('SELECT * FROM posting_batches')


def test_rounding_rejects_unbalanced_conversion_atomically(db, ee_org):
    docs, contact, accounts = setup(db, ee_org)
    draft = docs.create_invoice(ee_org['id'], contact_id=contact['id'], currency='USD', issue_date='2026-01-10', actor=ACTOR,
                                exchange_rate=Decimal('1.5'), lines=[dict(account_id=accounts['SALES'], unit_price='0.01'), dict(account_id=accounts['EXPENSE'], unit_price='0.01')])
    with pytest.raises(ValueError, match='Unbalanced posting after exchange rate rounding'):
        docs.issue_invoice(draft['id'], actor=ACTOR)
    assert docs.invoice(draft['id'])['status'] == 'Draft'
    assert not db.rows('SELECT * FROM posting_batches') and not db.rows('SELECT * FROM gl_entries')


def test_line_currency_round_half_up_and_idempotency(db, ee_org):
    docs, contact, accounts = setup(db, ee_org)
    args = dict(organisation_id=ee_org['id'], voucher_type='test', voucher_id='foreign-lines', voucher_code='FX',
                posting_date='2026-01-10', actor=ACTOR, currency='EUR', exchange_rate=Decimal('1.005'),
                lines=[PostingLine(accounts['AR'], debit=Decimal('1'), transaction_currency='USD'),
                       PostingLine(accounts['SALES'], credit=Decimal('1'), transaction_currency='USD')])
    batch = docs.ledger.post(**args)
    rows = entries(db, {'posting_batch_id': batch['id']})
    assert decimal(rows[0]['debit']) == decimal(rows[1]['credit']) == Decimal('1.01')
    assert decimal(rows[0]['transaction_amount']) == 1
    assert docs.ledger.post(**args)['id'] == batch['id']
    assert entries(db, {'posting_batch_id': batch['id']}) == rows
    assert db.scalar("SELECT COUNT(*) FROM audit_events WHERE action='ledger.posted'") == 1


def test_invoice_api_override_and_base_currency_rate(db, ee_org, sending):
    docs, contact, accounts = setup(db, ee_org)
    ExchangeRateService(db).create(ee_org['id'], **RATE, actor=ACTOR)
    response = sending['client'].post(f"/organisations/{ee_org['id']}/invoices", json=dict(
        contact_id=contact['id'], issue_date='2026-01-10', currency='USD', exchange_rate='1.25',
        lines=[dict(description='Synthetic service', account_id=accounts['SALES'], unit_price='10')]))
    assert response.status_code == 201, response.text
    assert decimal(response.json()['exchange_rate']) == Decimal('1.25')
    draft = docs.create_invoice(ee_org['id'], contact_id=contact['id'], issue_date='2026-01-10', actor=ACTOR,
                                currency='EUR', exchange_rate=Decimal('2'), lines=[dict(account_id=accounts['SALES'], unit_price='10')])
    posted = docs.issue_invoice(draft['id'], actor=ACTOR)
    assert sum(decimal(x['debit']) for x in entries(db, posted)) == Decimal('10')


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_locale_tail(language):
    from web import i18n
    raw = json.loads((i18n.LOCALES_DIR / f'{language}.json').read_text(encoding='utf-8'))
    assert list(raw)[-(6):] == ['invoice_exports', 'bulk_sending', 'reminder_rules', 'fx_rates', 'document_settings', 'copilot']
    assert set(raw['fx_rates']) == {'nav', 'views', 'workspace'}
    assert {'Document', 'Revalue balances', 'Revaluation date', 'Run revaluation',
            'Open portion', 'Booked base', 'Target base', 'Delta', 'Revaluation history',
            'Posting batch', 'No posting'} <= set(raw['fx_rates']['workspace'])
    assert 'fx_rates' in i18n.APPEND_SECTIONS
    for key, value in raw['fx_rates']['workspace'].items():
        assert i18n.catalog(language)['workspace'][key] == value and '\u2014' not in value


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
@pytest.mark.parametrize('role', ['owner', 'viewer'])
def test_settings_offline_browser(monkeypatch, language, role):
    playwright = pytest.importorskip('playwright.sync_api')
    from web import i18n
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    root = Path(__file__).resolve().parents[1]
    rows, calls, errors = [], [], []
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip('Install Playwright Chromium to run browser regressions')
            raise
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            path, method = urlsplit(route.request.url).path, route.request.method
            if path == '/api/organisations':
                return route.fulfill(json=[dict(id='org', name='Synthetic company', country_code='EE', base_currency='EUR', role=role)])
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic-token'})
            if path.startswith('/api/organisations/org/exchange-rates'):
                if method != 'GET':
                    calls.append((method, route.request.post_data_json, route.request.headers.get('x-csrf-token')))
                if method == 'POST':
                    rows.append(route.request.post_data_json | {'id': 'rate', 'source': 'manual'})
                    return route.fulfill(json=rows[-1], status=201)
                if method == 'DELETE':
                    rows.clear()
                    return route.fulfill(json={'deleted': True})
                return route.fulfill(body=json.dumps(rows), content_type="application/json")
            if path.startswith('/api/'):
                return route.fulfill(body='[]', content_type='application/json')
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#exchange-rates')
        try:
            playwright.expect(page.locator('#app-content h1')).to_have_text(words['Exchange rates'])
        except AssertionError:
            pytest.fail(page.locator('#app-content').inner_text())
        playwright.expect(page.locator('[data-view=exchange-rates]')).to_have_text(i18n.t('nav.fx_rates', language))
        if role == 'viewer':
            playwright.expect(page.locator('[name=rate_date]').locator('xpath=ancestor::form').locator('button[type=submit]')).to_be_disabled()
            playwright.expect(page.locator('[name=rate]')).to_be_disabled()
            rows.append(RATE | {'id': 'rate', 'source': 'manual'})
            page.reload()
            playwright.expect(page.locator('[data-action=deleteRate]')).to_be_disabled()
            assert not calls
        else:
            page.locator('[name=rate_date]').fill(RATE['rate_date'])
            page.locator('[name=from_currency]').fill('USD')
            page.locator('[name=rate]').fill('1.10')
            page.locator('[name=rate_date]').locator('xpath=ancestor::form').locator('button[type=submit]').click()
            playwright.expect(page.locator('[data-action=deleteRate]')).to_be_visible()
            assert calls == [('POST', RATE, 'synthetic-token')]
            page.locator('[data-action=deleteRate]').click()
            playwright.expect(page.locator('[data-action=deleteRate]')).to_have_count(0)
            assert calls[-1] == ('DELETE', {}, 'synthetic-token')
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.locator('#app-content').evaluate('el => el.scrollWidth <= el.clientWidth')
        assert not errors
        browser.close()
