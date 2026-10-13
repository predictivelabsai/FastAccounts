"""Local intercepted cash-flow and comparative views in every supported locale."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

playwright = pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_cash_flow_and_comparisons_in_workspace(monkeypatch, language):
    from web import i18n
    from web_app import app

    monkeypatch.setenv('FASTACCOUNTS_ALLOW_TEST_AUTH', 'true')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    root = Path(__file__).resolve().parents[1]
    requests = []
    cash_flow = dict(base_currency='EUR', opening_balance='10.00', closing_balance='15.00',
        inflows='5.00', outflows='0.00', buckets={'other': {'inflows': '5', 'outflows': '0', 'net': '5'},
        'internal': {'inflows': '2', 'outflows': '2', 'net': '0'}}, accounts=[dict(code='1010', name='Synthetic bank',
        opening_balance='10', closing_balance='15', movements=[dict(date='2024-02-29', document_number='J1',
        memo='Synthetic memo <visible>', contact_id='synthetic-contact', amount='5', allocations={'other': '5'})])])
    account = dict(code='4010', name='Synthetic sales', account_type='Income', debit=0, credit=45, balance=-45)
    profit = dict(start='2024-02-01', end='2024-02-29', income=45, expenses=0, profit=45, accounts=[account])
    sheet = dict(as_at='2024-02-29', assets=45, liabilities=0, equity=0, current_earnings=45,
                 liabilities_and_equity=45, accounts=[{**account, 'account_type': 'Asset'}])
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip('Install Playwright Chromium to run browser regressions')
            raise
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            url = urlsplit(route.request.url)
            path, query = url.path, parse_qs(url.query)
            if path == '/api/organisations':
                return route.fulfill(json=[dict(id='org', name='Synthetic company', country_code='EE', base_currency='EUR')])
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic-token'})
            if '/reports/' in path:
                requests.append((path.rsplit('/', 1)[1], query))
                if path.endswith('/cash-flow'):
                    return route.fulfill(json=cash_flow)
                if path.endswith('/profit-and-loss') or path.endswith('/balance-sheet'):
                    source = profit if path.endswith('/profit-and-loss') else sheet
                    data = {**source}
                    if query.get('compare', ['none']) != ['none']:
                        data['accounts'] = [{**a, 'comparative_balance': -21} for a in source['accounts']]
                        data['comparative'] = {**source, 'start': '2024-01-01', 'end': '2024-01-31',
                                               'as_at': '2024-01-31'} if 'as_at' in source else {**source, 'start': '2024-01-01', 'end': '2024-01-31'}
                    return route.fulfill(json=data)
                return route.fulfill(json=[], content_type='application/json')
            if path.startswith('/api/'):
                return route.fulfill(json=[], content_type='application/json')
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#cash-flow')
        playwright.expect(page.locator('#app-content h1')).to_have_text(words['Cash-flow statement'])
        playwright.expect(page.locator('#report-result')).to_contain_text(words['Opening balance'])
        playwright.expect(page.locator('#report-result')).to_contain_text('Synthetic memo <visible>')
        playwright.expect(page.locator('#report-result')).to_contain_text('synthetic-contact')
        playwright.expect(page.locator('#report-comparison')).to_be_hidden()
        page.locator('[name=start]').fill('2024-02-01')
        page.locator('[name=end]').fill('2024-02-29')
        page.get_by_role('button', name=words['Apply'], exact=True).click()
        page.wait_for_function("document.querySelector('#report-result table') !== null")
        assert requests[-1] == ('cash-flow', {'date_from': ['2024-02-01'], 'date_to': ['2024-02-29']})

        for report in ['profit-and-loss', 'balance-sheet']:
            page.locator(f'[data-report="{report}"]').click()
            playwright.expect(page.locator('#report-comparison')).to_be_visible()
            for mode in ['previous', 'prior_year', 'ytd']:
                page.locator('[name=compare]').select_option(mode)
                page.locator('[name=end]').fill('2024-02-29')
                page.locator('[name=period]').select_option('month')
                page.get_by_role('button', name=words['Apply'], exact=True).click()
                playwright.expect(page.locator('#report-result')).to_contain_text(words['Comparative period'])
                assert requests[-1][0] == report
                assert requests[-1][1]['compare'] == [mode]
                assert requests[-1][1]['start'] == ['2024-02-01']
            page.locator('[name=compare]').select_option('none')
            page.get_by_role('button', name=words['Apply'], exact=True).click()
            playwright.expect(page.locator('#report-result')).not_to_contain_text(words['Comparative period'])
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.locator('#app-content').evaluate('el => el.scrollWidth <= el.clientWidth')
        assert not errors
        browser.close()
