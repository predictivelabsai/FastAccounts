"""Offline delta revaluation, baseline integration, access and browser checks."""

from tests.migration_catalogue import catalogue, catalogue_after

import json
import socket
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from core_utils import decimal
from exchange_rates import ExchangeRateService
from fx_revaluation import FxRevaluationService
from ledger import PostingLine
from prepayments import PrepaymentService
from test_bulk_sending import ACTOR, sending
from test_fx_realised import setup, document, pay, entries, balance


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect

    def blocked(sock, address, *args, **kwargs):
        # Windows asyncio socketpair uses loopback to wake its local event loop.
        if isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}:
            return original(sock, address, *args, **kwargs)
        raise AssertionError('Live network is forbidden')
    monkeypatch.setattr(socket.socket, 'connect', blocked)


def rate(db, org, value='1.2', day='2026-01-31', currency='USD'):
    return ExchangeRateService(db).create(org['id'], rate_date=day, from_currency=currency,
        to_currency=org['base_currency'], rate=value, actor=ACTOR)


def run(db, org, day='2026-01-31'):
    return FxRevaluationService(db).run(org['id'], revaluation_date=day, actor=ACTOR)


@pytest.mark.parametrize('side', ['customer', 'supplier'])
@pytest.mark.parametrize('new_rate,delta', [('1.2', '-10'), ('1.0', '10')])
def test_trade_gain_loss_and_source_baseline(db, ee_org, side, new_rate, delta):
    data = setup(db, ee_org)
    doc = document(db, ee_org, data, side=side)
    original = entries(db, doc['posting_batch_id'])
    rate(db, ee_org, new_rate)
    result = run(db, ee_org)
    detail = result['documents'][0]
    assert detail['document_id'] == doc['id']
    assert decimal(detail['portion']) == 100 and decimal(detail['booked_base']) == 110
    assert decimal(detail['target']) == 100 * Decimal(new_rate)
    assert decimal(detail['delta']) == Decimal(delta)
    posted = entries(db, result['posting_batch_id'])
    assert len(posted) == 2
    control = next(r for r in posted if r['system_role'] == ('AR' if side == 'customer' else 'AP'))
    assert control['source_line_type'] == ('invoice' if side == 'customer' else 'bill')
    assert control['source_line_id'] == doc['id'] and control['contact_id'] == doc['contact_id']
    assert balance(db, ee_org['id'], 'FX_GAIN_LOSS') == Decimal(delta) * (1 if side == 'customer' else -1)
    assert entries(db, doc['posting_batch_id']) == original
    assert all(r['currency'] == r['transaction_currency'] == 'EUR' for r in posted)
    assert FxRevaluationService(db).list(ee_org['id']) == [result]
    event = db.one("SELECT * FROM audit_events WHERE action='fx_revaluation.posted'")
    assert event['actor'] == ACTOR and event['organisation_id'] == ee_org['id']
    assert json.loads(event['details_json'])['documents'] == result['documents']


def test_one_batch_aggregate_and_zero_delta(db, ee_org):
    data = setup(db, ee_org)
    ar = document(db, ee_org, data, rate='1.1')
    ap = document(db, ee_org, data, side='supplier', rate='1.3')
    zero = document(db, ee_org, data, rate='1.2')
    rate(db, ee_org)
    result = run(db, ee_org)
    rows = entries(db, result['posting_batch_id'])
    assert len(rows) == 3 and sum(r['system_role'] == 'FX_GAIN_LOSS' for r in rows) == 1
    assert {r['source_line_id'] for r in rows if r['source_line_id']} == {ar['id'], ap['id']}
    assert next(x for x in result['documents'] if x['document_id'] == zero['id'])['delta'] == '0.00'
    assert decimal(result['totals']['booked_base']) == decimal(result['totals']['target']) == 360
    assert decimal(result['totals']['delta']) == 0
    assert balance(db, ee_org['id'], 'FX_GAIN_LOSS') == -20


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_partial_paid_exclusions_and_later_settlement(db, ee_org, side):
    data = setup(db, ee_org)
    partial = document(db, ee_org, data, side=side)
    settled = document(db, ee_org, data, side=side)
    document(db, ee_org, data, side=side, currency='EUR', rate='9')
    document(db, ee_org, data, side=side, posted=False)
    pay(ee_org, data, [(partial, '40'), (settled, '100')], side=side, rate='1.1')
    rate(db, ee_org)
    result = run(db, ee_org)
    assert len(result['documents']) == 1
    detail = result['documents'][0]
    assert [decimal(detail[k]) for k in ('portion', 'booked_base', 'target', 'delta')] == [60, 66, 72, -6]
    # Even the original effective rate must use the new baseline for partial payments.
    first = pay(ee_org, data, [(partial, '20')], side=side, rate='1.1')
    allocation = db.one('SELECT * FROM payment_allocations WHERE payment_id=?', (first['id'],))
    assert decimal(allocation['booked_base_amount']) == 24
    final = pay(ee_org, data, [(partial, '40')], side=side, rate='1.3')
    assert decimal(db.one('SELECT * FROM payment_allocations WHERE payment_id=?', (final['id'],))['booked_base_amount']) == 48
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == (100 if side == 'customer' else -100)


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_repeats_converge_and_date_refused(db, ee_org, side):
    data = setup(db, ee_org)
    doc = document(db, ee_org, data, side=side)
    rate(db, ee_org)
    first = run(db, ee_org)
    with pytest.raises(ValueError, match='already exists'):
        run(db, ee_org)
    empty = run(db, ee_org, '2026-02-01')
    assert empty['status'] == 'Empty' and empty['posting_batch_id'] is None
    assert empty['documents'][0]['delta'] == '0.00'
    pay(ee_org, data, [(doc, '25')], side=side, rate='1.2')
    rate(db, ee_org, '1.4', '2026-02-28')
    second = run(db, ee_org, '2026-02-28')
    assert [decimal(second['documents'][0][k]) for k in ('booked_base', 'target', 'delta')] == [90, 105, -15]
    last = pay(ee_org, data, [(doc, '75')], side=side, rate='1.4')
    entries(db, last['posting_batch_id'])
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0
    assert len(FxRevaluationService(db).list(ee_org['id'])) == 3
    assert db.scalar("SELECT COUNT(*) FROM posting_batches WHERE voucher_type='fx_revaluation'") == 2
    assert first['posting_batch_id'] != second['posting_batch_id']


def test_exact_direction_historical_rate_and_fallback(db, ee_org):
    data = setup(db, ee_org)
    doc = document(db, ee_org, data, rate='9')
    service = ExchangeRateService(db)
    service.create(ee_org['id'], rate_date='2026-01-01', from_currency='EUR', to_currency='USD', rate='2', actor=ACTOR)
    rate(db, ee_org, '7', '2026-02-01')
    result = run(db, ee_org)
    assert result['documents'][0]['rate'] == '1' and decimal(result['documents'][0]['target']) == 100
    later = run(db, ee_org, '2026-02-02')
    assert decimal(later['documents'][0]['delta']) == -600
    assert later['documents'][0]['document_id'] == doc['id']


@pytest.mark.parametrize('failure', ['fx_role', 'locked', 'outside_period'])
def test_atomic_failure(db, ee_org, failure):
    data = setup(db, ee_org)
    document(db, ee_org, data)
    rate(db, ee_org)
    if failure == 'fx_role':
        with db.transaction() as tx:
            tx.execute("UPDATE accounts SET active=0 WHERE organisation_id=? AND system_role='FX_GAIN_LOSS'", (ee_org['id'],))
    if failure == 'locked':
        with db.transaction() as tx:
            tx.execute("UPDATE fiscal_periods SET status='Locked' WHERE organisation_id=?", (ee_org['id'],))
    before = {table: db.rows(f'SELECT * FROM {table} ORDER BY id') for table in ('posting_batches', 'gl_entries', 'audit_events')}
    with pytest.raises(ValueError):
        run(db, ee_org, '2035-01-31' if failure == 'outside_period' else '2026-01-31')
    assert not db.rows('SELECT * FROM fx_revaluations')
    assert before == {table: db.rows(f'SELECT * FROM {table} ORDER BY id') for table in before}


@pytest.mark.parametrize('side', ['customer', 'supplier'])
@pytest.mark.parametrize('event', ['refund', 'allocate'])
def test_prepayments_revalue_partial_and_clear(db, ee_org, side, event):
    data = setup(db, ee_org)
    docs, contact, bank, accounts = data
    rate(db, ee_org, '1.1', '2026-01-01')
    service = PrepaymentService(db)
    advance = service.create(ee_org['id'], side=side, contact_id=contact['id'], bank_account_id=bank['id'],
        document_date='2026-01-10', amount='100', idempotency_key='advance', actor=ACTOR)
    service.refund(ee_org['id'], advance['id'], refund_date='2026-01-20', amount='25', idempotency_key='first', actor=ACTOR)
    doc = document(db, ee_org, data, side=side, rate='1.1', amount='75') if event == 'allocate' else None
    rate(db, ee_org)
    result = run(db, ee_org)
    detail = next(x for x in result['documents'] if x['document_type'] == 'prepayment')
    assert [decimal(detail[k]) for k in ('portion', 'booked_base', 'target', 'delta')] == [75, Decimal('82.5'), 90, Decimal('-7.5')]
    rows = entries(db, result['posting_batch_id'])
    assert next(r for r in rows if r['source_line_id'] == advance['id'])['source_line_type'] == 'prepayment'
    # A partial event at the original rate must still consume the revalued amount.
    rate(db, ee_org, '1.1', '2026-02-01')
    for index, amount in enumerate(['25', '50']):
        if event == 'refund':
            posted = service.refund(ee_org['id'], advance['id'], refund_date='2026-02-02', amount=amount,
                                   idempotency_key=f'end-{index}', actor=ACTOR)
        else:
            posted = service.allocate(ee_org['id'], advance['id'], document_type='invoice' if side == 'customer' else 'bill',
                document_id=doc['id'], allocation_date='2026-02-02', amount=amount, idempotency_key=f'end-{index}', actor=ACTOR)
        entries(db, posted['posting_batch_id'])
    assert balance(db, ee_org['id'], 'CUSTOMER_PREPAYMENTS' if side == 'customer' else 'SUPPLIER_PREPAYMENTS') == 0
    if doc:
        assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0
    assert not run(db, ee_org, '2026-02-03')['documents']


def test_zero_remaining_base_excluded_and_empty_run(db, ee_org):
    data = setup(db, ee_org)
    doc = document(db, ee_org, data, rate='0.5', amount='0.02')
    pay(ee_org, data, [(doc, '0.01')], rate='1')
    rate(db, ee_org)
    result = run(db, ee_org)
    assert result['documents'] == [] and result['posting_batch_id'] is None and result['status'] == 'Empty'


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_revalued_cents_and_final_remainder(db, ee_org, side):
    data = setup(db, ee_org)
    doc = document(db, ee_org, data, side=side, amount='0.03', rate='1.5')
    rate(db, ee_org, '1.3333333333')
    result = run(db, ee_org)
    assert [decimal(result['documents'][0][k]) for k in ('booked_base', 'target', 'delta')] == [Decimal('0.05'), Decimal('0.04'), Decimal('0.01')]
    for _ in range(3):
        payment = pay(ee_org, data, [(doc, '0.01')], side=side, rate='1.5')
        entries(db, payment['posting_batch_id'])
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0


@pytest.mark.parametrize('side', ['customer', 'supplier'])
@pytest.mark.parametrize('new_rate,delta', [('1.2', '-10'), ('1.0', '10')])
def test_prepayment_gain_loss_base_document_offset(db, ee_org, side, new_rate, delta):
    data = setup(db, ee_org)
    _, contact, bank, _ = data
    rate(db, ee_org, '1.1', '2026-01-01')
    service = PrepaymentService(db)
    advance = service.create(ee_org['id'], side=side, contact_id=contact['id'], bank_account_id=bank['id'],
        document_date='2026-01-10', amount='100', idempotency_key='gain-loss', actor=ACTOR)
    doc = document(db, ee_org, data, side=side, currency='EUR')
    rate(db, ee_org, new_rate)
    result = run(db, ee_org)
    assert len(result['documents']) == 1 and decimal(result['documents'][0]['delta']) == Decimal(delta)
    assert balance(db, ee_org['id'], 'FX_GAIN_LOSS') == Decimal(delta) * (-1 if side == 'customer' else 1)
    service.allocate(ee_org['id'], advance['id'], document_type='invoice' if side == 'customer' else 'bill',
        document_id=doc['id'], allocation_date='2026-02-01', amount='100', idempotency_key='offset', actor=ACTOR)
    assert balance(db, ee_org['id'], 'CUSTOMER_PREPAYMENTS' if side == 'customer' else 'SUPPLIER_PREPAYMENTS') == 0
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0


def test_signed_fx_cancels_without_zero_line(db, ee_org):
    data = setup(db, ee_org)
    document(db, ee_org, data)
    document(db, ee_org, data, side='supplier')
    rate(db, ee_org)
    result = run(db, ee_org)
    posted = entries(db, result['posting_batch_id'])
    assert len(posted) == 2 and {r['system_role'] for r in posted} == {'AR', 'AP'}
    assert decimal(result['totals']['fx_gain_loss']) == 0


def test_actual_entries_and_tenant_rate_take_precedence(db, ee_org, uk_org):
    data = setup(db, ee_org)
    doc = document(db, ee_org, data, rate='8', posted=False)
    batch = data[0].ledger.post(organisation_id=ee_org['id'], voucher_type='invoice', voucher_id=doc['id'],
        voucher_code='SYN-BASELINE', posting_date='2026-01-10', currency='USD', exchange_rate=Decimal('1.1'), actor=ACTOR,
        lines=[PostingLine(data[3]['AR'], debit=Decimal('100'), source_line_type='invoice', source_line_id=doc['id']),
               PostingLine(data[3]['SALES'], credit=Decimal('100'), source_line_type='invoice', source_line_id=doc['id'])])
    foreign = document(db, uk_org, setup(db, uk_org), rate='7')
    rate(db, uk_org, '9')
    rate(db, ee_org, '1.2')
    with db.transaction() as tx:
        tx.execute("UPDATE invoices SET posting_batch_id=?,status='Issued' WHERE organisation_id=? AND id=?",
                   (batch['id'], ee_org['id'], doc['id']))
    result = run(db, ee_org)
    assert len(result['documents']) == 1 and decimal(result['documents'][0]['booked_base']) == 110
    assert result['documents'][0]['document_id'] != foreign['id']
    assert FxRevaluationService(db).list(uk_org['id']) == []


def test_no_ledger_baseline_is_not_invented(db, ee_org):
    data = setup(db, ee_org)
    doc = document(db, ee_org, data, posted=False)
    with db.transaction() as tx:
        tx.execute("UPDATE invoices SET status='Issued' WHERE organisation_id=? AND id=?", (ee_org['id'], doc['id']))
    assert run(db, ee_org)['documents'] == []
    booked = document(db, ee_org, data)
    with db.transaction() as tx:
        tx.execute("UPDATE invoices SET paid_total=50,status='Part Paid' WHERE organisation_id=? AND id=?",
                   (ee_org['id'], booked['id']))
    rate(db, ee_org, '1.2', '2026-02-01')
    result = run(db, ee_org, '2026-02-01')
    assert [decimal(result['documents'][0][key]) for key in ('portion', 'booked_base', 'target', 'delta')] == [50, 110, 60, 50]
    pay(ee_org, data, [(booked, '50')], rate='1.2')
    assert balance(db, ee_org['id'], 'AR') == 0


def test_concurrent_same_date_refusal(db, ee_org):
    from concurrent.futures import ThreadPoolExecutor
    document(db, ee_org, setup(db, ee_org))
    rate(db, ee_org)

    def attempt():
        try:
            return run(db, ee_org)['status']
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(lambda _: attempt(), range(2))) == ['A revaluation already exists for this date', 'Posted']
    assert db.scalar('SELECT COUNT(*) FROM fx_revaluations') == 1
    assert db.scalar("SELECT COUNT(*) FROM posting_batches WHERE voucher_type='fx_revaluation'") == 1


@pytest.mark.parametrize('role', ['owner', 'administrator', 'accountant', 'approver', 'viewer', 'outsider'])
def test_api_roles_history_and_tenancy(sending, role):
    d = sending
    url = f"/organisations/{d['oid']}/fx-revaluations"
    headers = {'X-Test-User': ACTOR if role == 'owner' else role + '@example.test'}
    response = d['client'].post(url, json={'revaluation_date': '2026-01-31'}, headers=headers)
    assert response.status_code == (201 if role in {'owner', 'administrator'} else 403), response.text
    assert d['client'].get(url, headers=headers).status_code == (403 if role == 'outsider' else 200)
    if response.status_code == 201:
        assert d['client'].get(url).json() == [response.json()]
        assert d['client'].post(url, json={'revaluation_date': '2026-01-31'}, headers=headers).status_code == 422
        assert d['client'].get(f"/organisations/{d['other']['id']}/fx-revaluations").json() == []
    if role != 'owner':
        foreign = f"/organisations/{d['other']['id']}/fx-revaluations"
        assert d['client'].get(foreign, headers=headers).status_code == 403
        assert d['client'].post(foreign, json={'revaluation_date': '2026-01-31'}, headers=headers).status_code == 403


@pytest.mark.parametrize('payload', [{}, {'revaluation_date': '2026-02-30'}, {'revaluation_date': '20260131'},
    {'revaluation_date': '2026-1-31'}, {'revaluation_date': None}, {'revaluation_date': 20260131},
    {'revaluation_date': '2026-01-31', 'extra': True}])
def test_api_strict_validation(sending, payload):
    d = sending
    assert d['client'].post(f"/organisations/{d['oid']}/fx-revaluations", json=payload).status_code == 422
    assert not d['db'].rows('SELECT * FROM fx_revaluations')


def test_auth_csrf_wiring(sending):
    from api_app import api, current_user, require_csrf, User
    from web_app import app
    d = sending
    url = f"/organisations/{d['oid']}/fx-revaluations"
    with TestClient(app) as client:
        assert client.get('/api' + url).status_code == 401
        assert client.post('/api' + url, json={'revaluation_date': '2026-01-31'}).status_code == 401
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        with TestClient(app) as client:
            token = client.get('/api/csrf').json()['csrf_token']
            for headers in [{}, {'X-CSRF-Token': 'wrong'}]:
                assert client.post('/api' + url, json={'revaluation_date': '2026-01-31'}, headers=headers).status_code == 403
            assert client.post('/api' + url, json={'revaluation_date': '2026-01-31'}, headers={'X-CSRF-Token': token}).status_code == 201
    finally:
        api.dependency_overrides.clear()
    for route in [r for r in api.routes if '/fx-revaluations' in r.path]:
        assert (require_csrf in [x.call for x in route.dependant.dependencies]) == ('POST' in route.methods)


def test_migration_rerun_tenant_constraints_and_roles(db, ee_org, uk_org):
    root = Path(__file__).resolve().parents[1]
    assert db.scalar('SELECT COUNT(*) FROM schema_migrations') == len(catalogue())
    assert db.migrate() == []
    sql = (root / 'migrations/sqlite/0026_fx_revaluations.sql').read_text(encoding='utf-8')
    with db.transaction() as tx:
        tx.connection.executescript(sql)
        tx.connection.executescript(sql)
    for org, code in [(ee_org, '6990'), (uk_org, '7900')]:
        assert db.one("SELECT code FROM accounts WHERE organisation_id=? AND system_role='FX_GAIN_LOSS'", (org['id'],))['code'] == code
    assert f'"{catalogue()[-1]}"]' in (Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    data = setup(db, ee_org)
    doc = document(db, ee_org, data)
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as tx:
            tx.execute("INSERT INTO fx_revaluations VALUES ('foreign',?, '2026-01-31',?,'Posted',?,'synthetic')",
                       (uk_org['id'], doc['posting_batch_id'], ACTOR))


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
@pytest.mark.parametrize('role', ['owner', 'viewer'])
def test_settings_revaluation_offline_browser(monkeypatch, language, role):
    playwright = pytest.importorskip('playwright.sync_api')
    from web import i18n
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    root = Path(__file__).resolve().parents[1]
    runs, calls, errors = [], [], []
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
            if path == '/api/organisations/org/fx-revaluations':
                if method == 'POST':
                    calls.append((route.request.post_data_json, route.request.headers.get('x-csrf-token')))
                    runs.append(dict(revaluation_date='2026-01-31', status='Posted', posting_batch_id='synthetic-batch', documents=[
                        dict(document='SYN-INV-1', currency='USD', portion='60.00', booked_base='66.00', target='72.00', delta='-6.00')]))
                    return route.fulfill(json=runs[-1], status=201)
                return route.fulfill(body=json.dumps(runs), content_type='application/json')
            if path.startswith('/api/'):
                return route.fulfill(body='[]', content_type='application/json')
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#exchange-rates')
        section = page.locator('[data-fx-revaluation]')
        playwright.expect(section.locator('h2')).to_have_text(words['Revalue balances'])
        if role == 'viewer':
            playwright.expect(section.locator('button[type=submit]')).to_be_disabled()
            playwright.expect(section.locator('[name=revaluation_date]')).to_be_disabled()
            assert not calls
        else:
            section.locator('[name=revaluation_date]').fill('2026-01-31')
            section.locator('button[type=submit]').click()
            playwright.expect(section.locator('[data-fx-result]')).to_contain_text('SYN-INV-1')
            playwright.expect(section.locator('[data-fx-result]')).to_contain_text('-6.00')
            playwright.expect(section.locator('[data-fx-history]')).to_contain_text('synthetic-batch')
            assert calls == [({'revaluation_date': '2026-01-31'}, 'synthetic-token')]
            page.reload()
            playwright.expect(page.locator('[data-fx-result]')).to_contain_text('SYN-INV-1')
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.locator('#app-content').evaluate('el => el.scrollWidth <= el.clientWidth')
        assert not errors
        browser.close()
