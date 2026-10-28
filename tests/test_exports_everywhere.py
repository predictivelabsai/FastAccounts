"""Offline CSV contracts, report parity, access and workspace downloads."""
import csv
from decimal import Decimal
from io import StringIO
from pathlib import Path
import socket
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from banking import BankingService
from documents import DocumentService
from ledger import LedgerService, PostingLine
from objects import ObjectService
from organisations import OrganisationService
from quotes import QuoteService
from web import i18n

ROOT = Path(__file__).resolve().parents[1]
ACTOR = 'owner@example.test'
LIST_HEADERS = {
    'contacts': ['Name', 'Type', 'Email', 'Country', 'VAT number', 'Registration number',
                 'Address', 'IBAN', 'Payment terms (days)'],
    'quotes': ['Number', 'Customer', 'Quote date', 'Valid until', 'Status', 'Currency',
               'Subtotal', 'Tax', 'Total', 'Notes'],
    'bank-transactions': ['Date', 'Value date', 'Counterparty', 'Reference', 'Amount', 'Currency', 'Status'],
    'objects': ['Code', 'Name', 'Object type', 'Active'],
}
ACCOUNT_HEADERS = ['Code', 'Account', 'Type', 'Debit', 'Credit', 'Balance']
REPORT_HEADERS = {
    'trial-balance': ACCOUNT_HEADERS, 'profit-and-loss': ACCOUNT_HEADERS, 'balance-sheet': ACCOUNT_HEADERS,
    'general-ledger': ['Date', 'Code', 'Account', 'Reference', 'Description', 'Debit', 'Credit',
                       'Currency', 'Contact', 'Status', 'Project', 'Location', 'Person', 'Object'],
    'cash-flow': ['Description', 'Inflows', 'Outflows', 'Balance', 'Currency'],
    'receivables-aging': ['Number', 'Contact', 'Date', 'Due date', 'Currency', 'Days overdue', 'Classification', 'Outstanding'],
    'payables-aging': ['Number', 'Contact', 'Date', 'Due date', 'Currency', 'Days overdue', 'Classification', 'Outstanding'],
}
QUERIES = {tab: ({'as_at': '2026-01-31'} if tab in {'balance-sheet', 'receivables-aging', 'payables-aging'}
                 else {'date_from': '2026-01-01', 'date_to': '2026-01-31'} if tab == 'cash-flow'
                 else {'start': '2026-01-01', 'end': '2026-01-31'}) for tab in REPORT_HEADERS}
PATHS = [f'{kind}/export.csv' for kind in LIST_HEADERS] + [f'reports/{tab}.csv' for tab in REPORT_HEADERS]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect
    def blocked(sock, address, *args, **kwargs):
        if isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}:
            return original(sock, address, *args, **kwargs)
        raise AssertionError('Live network is forbidden')
    monkeypatch.setattr(socket.socket, 'connect', blocked)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import database
    from api_app import api
    monkeypatch.delenv('DB_URL', raising=False)
    monkeypatch.setenv('FASTACCOUNTS_DB', str(tmp_path / 'exports.sqlite'))
    monkeypatch.setenv('FASTACCOUNTS_DATA_DIR', str(tmp_path / 'evidence'))
    monkeypatch.setenv('FASTACCOUNTS_ALLOW_TEST_AUTH', 'true')
    database.reset_database_cache()
    db = database.get_database()
    db.migrate()
    service = OrganisationService(db)
    org = service.create(name='Synthetic exports company', country_code='EE', entity_type='EE_OU', owner_email=ACTOR)
    other = service.create(name='Synthetic other company', country_code='EE', entity_type='EE_OU', owner_email='other@example.test')
    for role in ['administrator', 'accountant', 'approver', 'viewer']:
        service.add_member(org['id'], ACTOR, role + '@example.test', role)
    docs = DocumentService(db)
    for book, name in [(org, '=HYPERLINK(1)'), (other, 'PRIVATE OTHER CONTACT')]:
        oid = book['id']
        contact = docs.create_contact(oid, name=name, country_code='EE', address='Street, "House"', contact_type='both')
        sales = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (oid,))
        expense = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND account_type='Expense' ORDER BY code LIMIT 1", (oid,))
        dimension = ObjectService(db).create(oid, object_type='project', code='P1', name=name, actor=ACTOR)
        for day in ['2026-01-10', '2026-02-10']:
            line = dict(description='Service, "quoted"', account_id=sales, unit_price='12.34', projects_project_id=dimension['id'])
            invoice = docs.create_invoice(oid, contact_id=contact['id'], issue_date=day, due_date=day,
                                          lines=[line], actor=ACTOR)
            docs.issue_invoice(invoice['id'], actor=ACTOR)
            bill = docs.create_bill(oid, contact_id=contact['id'], supplier_number=day, bill_date=day, due_date=day,
                                    lines=[dict(description='Synthetic cost', account_id=expense, unit_price='7.89')], actor=ACTOR)
            docs.approve_bill(bill['id'], actor=ACTOR)
            accounts = {r['system_role']: r['id'] for r in db.rows('SELECT * FROM accounts WHERE organisation_id=?', (oid,))}
            LedgerService(db).post(organisation_id=oid, posting_date=day, voucher_type='journal',
                voucher_id=day, voucher_code='Synthetic capital ' + day, actor=ACTOR, currency='EUR',
                lines=[PostingLine(accounts['BANK'], debit=Decimal('9.87')),
                       PostingLine(accounts['CAPITAL'], credit=Decimal('9.87'))])
        QuoteService(db).create(oid, actor=ACTOR, contact_id=contact['id'], quote_date='2026-01-10',
                                valid_until='2026-12-31', notes='Offer, "quoted"',
                                lines=[dict(description='Synthetic offer', account_id=sales, unit_price='12.34')])
        bank = db.one('SELECT id FROM bank_accounts WHERE organisation_id=? LIMIT 1', (oid,))
        if not bank:
            bank = docs.create_bank_account(oid, name='Synthetic bank', currency='EUR')
        BankingService(db).import_csv(oid, bank['id'],
            b'date,amount,currency,counterparty,reference\n2026-01-02,-1.23,EUR,Synthetic,early\n2026-02-02,2.34,EUR,Synthetic,late\n', actor=ACTOR)
    with TestClient(api, headers={'X-Test-User': ACTOR}) as client:
        yield dict(db=db, org=org, other=other, client=client, base=f"/organisations/{org['id']}")
    database.reset_database_cache()


def download(d, path, **kwargs):
    return d['client'].get(d['base'] + '/' + path, **kwargs)


def records(response, headers):
    assert response.status_code == 200, response.text
    assert response.headers['content-type'].startswith('text/csv')
    assert response.headers['content-disposition'].startswith('attachment; filename=')
    assert response.content.startswith(b'\xef\xbb\xbf')
    reader = csv.DictReader(StringIO(response.content.decode('utf-8-sig')))
    assert reader.fieldnames == headers
    return list(reader)


@pytest.mark.parametrize('kind', LIST_HEADERS)
def test_list_contract_content_and_order(env, kind):
    d = env
    rows = records(download(d, kind + '/export.csv'), LIST_HEADERS[kind])
    source = download(d, kind).json()
    assert len(rows) == len(source)
    assert 'PRIVATE OTHER CONTACT' not in str(rows)
    if kind == 'contacts':
        assert rows[0]['Name'] == "'=HYPERLINK(1)"
        assert rows[0]['Address'] == 'Street, "House"'
    elif kind == 'quotes':
        assert rows[0]['Customer'] == "'=HYPERLINK(1)"
        assert rows[0]['Status'] == source[0]['status'] == 'Draft'
        assert rows[0]['Total'] == '12.34' and rows[0]['Notes'] == 'Offer, "quoted"'
    elif kind == 'bank-transactions':
        assert [r['Date'] for r in rows] == [r['booking_date'] for r in source]
        assert [r['Reference'] for r in rows] == [r['reference'] for r in source] == ['late', 'early']
        assert rows[1]['Amount'] == '-1.23' and rows[0]['Value date'] == ''
    else:
        assert rows[0]['Name'] == "'=HYPERLINK(1)" and rows[0]['Active'] == '1'


@pytest.mark.parametrize('tab', REPORT_HEADERS)
def test_report_contract_and_json_parity(env, tab):
    d = env
    query = QUERIES[tab]
    data = download(d, 'reports/' + tab, params=query).json()
    rows = records(download(d, 'reports/' + tab + '.csv', params=query), REPORT_HEADERS[tab])
    if tab == 'trial-balance':
        assert len(rows) == len(data)
        assert [r['Code'] for r in rows] == [r['code'] for r in data]
        assert [Decimal(r['Balance']) for r in rows] == [Decimal(str(r['balance'])) for r in data]
    elif tab in {'profit-and-loss', 'balance-sheet'}:
        details = [r for r in rows if r['Code']]
        assert len(details) == len(data['accounts'])
        key, label = ('profit', 'Profit') if tab == 'profit-and-loss' else ('current_earnings', 'Current earnings')
        assert Decimal(next(r['Balance'] for r in rows if r['Account'] == label)) == Decimal(str(data[key]))
        assert download(d, 'reports/' + tab + '.csv', params=query | {'compare': 'prior_year'}).content == download(d, 'reports/' + tab + '.csv', params=query).content
    elif tab == 'general-ledger':
        assert len(rows) == len(data) == 6
        assert [r['Reference'] for r in rows] == [r['voucher_code'] for r in data]
        assert any(r['Contact'] == "'=HYPERLINK(1)" for r in rows)
    elif tab.endswith('-aging'):
        assert len(rows) == len(data['items']) == 1
        assert Decimal(rows[0]['Outstanding']) == Decimal(str(data['items'][0]['outstanding']))
    else:
        assert len(rows) == len(data['buckets']) + 3
        assert Decimal(rows[0]['Balance']) == Decimal(str(data['opening_balance']))
        assert Decimal(rows[-1]['Balance']) == Decimal(str(data['closing_balance']))
        assert Decimal(next(r['Inflows'] for r in rows if r['Description'] == 'Total')) == Decimal('9.87')


@pytest.mark.parametrize('path', PATHS)
def test_viewer_outsider_and_tenant_isolation(env, path):
    d = env
    tab = path.removeprefix('reports/').removesuffix('.csv')
    params = QUERIES.get(tab, {})
    assert download(d, path, params=params, headers={'X-Test-User': 'viewer@example.test'}).status_code == 200
    assert download(d, path, params=params, headers={'X-Test-User': 'outsider@example.test'}).status_code == 403
    foreign = d['client'].get(f"/organisations/{d['other']['id']}/{path}", params=params)
    assert foreign.status_code in {403, 404}
    assert 'PRIVATE OTHER CONTACT' not in foreign.text


@pytest.mark.parametrize('tab', REPORT_HEADERS)
def test_report_date_filters_and_read_only(env, tab):
    d = env
    tables = d['db'].rows("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    before = {t['name']: d['db'].rows('SELECT * FROM "' + t['name'] + '"') for t in tables}
    query = {key: '2026-02-28' if key in {'end', 'as_at', 'date_to'} else '2026-02-01' for key in QUERIES[tab]}
    data = download(d, 'reports/' + tab, params=query).json()
    rows = records(download(d, 'reports/' + tab + '.csv', params=query), REPORT_HEADERS[tab])
    if tab in {'trial-balance', 'profit-and-loss', 'balance-sheet'}:
        accounts = data if isinstance(data, list) else data['accounts']
        assert [Decimal(r['Balance']) for r in rows if r['Code']] == [Decimal(str(r['balance'])) for r in accounts]
    elif tab == 'general-ledger':
        assert len(rows) == len(data) == 6
        assert all(r['Date'].startswith('2026-02') for r in rows)
    elif tab.endswith('-aging'):
        assert len(rows) == len(data['items']) == 2
    else:
        assert Decimal(rows[-1]['Balance']) == Decimal(str(data['closing_balance']))
        assert Decimal(rows[0]['Balance']) == Decimal('9.87')
        assert Decimal(rows[-1]['Balance']) == Decimal('19.74')
    for kind in LIST_HEADERS:
        assert download(d, kind + '/export.csv').status_code == 200
    assert {t['name']: d['db'].rows('SELECT * FROM "' + t['name'] + '"') for t in tables} == before
    assert d['db'].scalar('SELECT COUNT(*) FROM schema_migrations') == 41


@pytest.mark.parametrize('tab', ['trial-balance', 'profit-and-loss', 'general-ledger'])
def test_object_filter_uses_same_service(env, tab):
    d = env
    project = d['db'].scalar('SELECT id FROM objects WHERE organisation_id=?', (d['org']['id'],))
    query = QUERIES[tab] | {'object_id': project}
    data = download(d, 'reports/' + tab, params=query).json()
    rows = records(download(d, 'reports/' + tab + '.csv', params=query), REPORT_HEADERS[tab])
    if tab == 'general-ledger':
        assert len(rows) == len(data) == 1
    else:
        accounts = data if isinstance(data, list) else data['accounts']
        assert [Decimal(r['Balance']) for r in rows if r['Code']] == [Decimal(str(r['balance'])) for r in accounts]
    foreign = d['db'].scalar('SELECT id FROM objects WHERE organisation_id=?', (d['other']['id'],))
    assert download(d, 'reports/' + tab + '.csv', params=query | {'object_id': foreign}).status_code in {403, 404, 422}


@pytest.mark.parametrize('tab', REPORT_HEADERS)
def test_dates_required_and_invalid(env, tab):
    assert download(env, 'reports/' + tab + '.csv').status_code == 422
    bad = dict(QUERIES[tab])
    bad[next(iter(bad))] = '2026-02-30'
    assert download(env, 'reports/' + tab + '.csv', params=bad).status_code == 422


def test_unknown_report_and_report_role_parity(env):
    assert download(env, 'reports/missing.csv').status_code == 404
    for tab in REPORT_HEADERS:
        headers = {'X-Test-User': 'approver@example.test'}
        json_response = download(env, 'reports/' + tab, params=QUERIES[tab], headers=headers)
        assert download(env, 'reports/' + tab + '.csv', params=QUERIES[tab], headers=headers).status_code == json_response.status_code


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_workspace_export_links_and_applied_filters(monkeypatch, language):
    playwright = pytest.importorskip('playwright.sync_api')
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    for key in ['Export CSV', 'Export Excel']:
        assert key in i18n.catalog(language)['workspace']
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip('Install Playwright Chromium to run browser regressions')
            raise
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(request_route):
            path = urlsplit(request_route.request.url).path
            if path == '/api/organisations':
                return request_route.fulfill(json=[dict(id='org', name='Synthetic company', country_code='EE', base_currency='EUR', role='viewer')])
            if path == '/api/organisations/org/objects':
                return request_route.fulfill(json=[dict(id='project', code='P1', name='Synthetic', object_type='project', active=1)])
            if path.endswith('/reports/profit-and-loss'):
                return request_route.fulfill(json=dict(accounts=[], income='0', expenses='0', profit='0'))
            if path.endswith('/reports/balance-sheet'):
                return request_route.fulfill(json=dict(accounts=[], assets='0', liabilities='0', equity='0', current_earnings='0', liabilities_and_equity='0'))
            if path.endswith('/reports/cash-flow'):
                return request_route.fulfill(json=dict(base_currency='EUR', accounts=[], buckets={}, opening_balance='0', closing_balance='0', inflows='0', outflows='0'))
            if path.endswith('-aging'):
                return request_route.fulfill(json=dict(items=[], buckets={}, total='0'))
            if path.endswith('/reports/cash-summary'):
                return request_route.fulfill(json=dict(accounts=[], net_cash_movement='0'))
            if path.startswith('/api/'):
                return request_route.fulfill(json=[], content_type='application/json')
            if path == '/app':
                return request_route.fulfill(body=html, content_type='text/html')
            if path in ['/static/app.js', '/static/app.css']:
                return request_route.fulfill(path=str(ROOT / path.lstrip('/')))
            return request_route.fulfill(status=404)
        page.route('**/*', route)
        for view, target in [('contacts', 'contacts/export.csv'), ('quotes', 'quotes/export.csv'),
                             ('banking', 'bank-transactions/export.csv'), ('objects', 'objects/export.csv'),
                             ('payroll', 'reports/employees.xlsx')]:
            page.goto('http://workspace.test/app#' + view)
            playwright.expect(page.locator(f'#app-content a[href="/api/organisations/org/{target}"]')).to_be_visible()
        page.goto('http://workspace.test/app#accounting')
        export = page.locator('#report-exports a').first
        playwright.expect(export).to_have_attribute('href', re.compile('trial-balance.csv'))
        page.locator('#report-dates [name=start]').fill('2026-01-02')
        page.locator('#report-dates [name=end]').fill('2026-01-31')
        page.locator('#report-dates [name=object_id]').select_option('project')
        page.locator('#report-dates button').click()
        playwright.expect(export).to_have_attribute('href', re.compile('object_id=project'))
        query = parse_qs(urlsplit(export.get_attribute('href')).query)
        assert query == dict(start=['2026-01-02'], end=['2026-01-31'], object_id=['project'])
        page.locator('#report-dates [name=end]').fill('2026-02-28')
        assert parse_qs(urlsplit(export.get_attribute('href')).query) == query
        page.locator('[data-report=general-ledger]').click()
        workbook = page.locator('#report-exports a').last
        playwright.expect(workbook).to_have_attribute('href', re.compile('general_ledger.xlsx'))
        assert set(parse_qs(urlsplit(workbook.get_attribute('href')).query)) == {'date_from', 'date_to'}
        for tab in ['profit-and-loss', 'balance-sheet', 'cash-flow', 'receivables-aging', 'payables-aging']:
            page.locator(f'[data-report={tab}]').click()
            playwright.expect(export).to_have_attribute('href', re.compile(tab + '.csv'))
        page.locator('[data-report=cash-summary]').click()
        playwright.expect(page.locator('#report-exports a')).to_have_count(0)
        assert not errors
        browser.close()
