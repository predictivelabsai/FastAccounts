"""Bank feed status browser checks with fully intercepted requests."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

playwright = pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
@pytest.mark.parametrize('connection_status', ['Connected', 'Reauth Required', 'Expired while loading'])
def test_daily_feed_status_and_renewal_warning(monkeypatch, language, connection_status):
    from web import i18n
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_ALLOW_TEST_AUTH', 'true')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    root = Path(__file__).resolve().parents[1]
    state = {'connection_status': connection_status, 'worker_enabled': True,
             'schedules': [{'gocardless_account_id': 'synthetic-account', 'active': 1,
                            'last_pull_at': '2026-10-12T05:00:00Z', 'last_result': 'Success',
                            'last_error_message': None}]}
    initial_status = 'Connected' if connection_status == 'Expired while loading' else connection_status
    state['connection_status'] = initial_status
    calls = []
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
            path = urlsplit(route.request.url).path
            if path.startswith('/api/'):
                calls.append(path)
            if path == '/api/organisations':
                return route.fulfill(json=[{'id': 'org', 'name': 'Synthetic company', 'country_code': 'EE', 'base_currency': 'EUR'}])
            if path == '/api/integrations':
                return route.fulfill(json=[{'key': 'open_banking', 'name': 'GoCardless', 'logo': '', 'registry_status': 'Adapter ready'}])
            if path == '/api/organisations/org/integrations':
                return route.fulfill(json=[{'provider': 'open_banking', 'status': initial_status, 'config': {}}])
            if path == '/api/email-status':
                return route.fulfill(json={'connected': False})
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic-token'})
            if path.endswith('/pull-status'):
                return route.fulfill(json=state)
            if path.endswith('/accounts'):
                if connection_status == 'Expired while loading':
                    state['connection_status'] = 'Reauth Required'
                    return route.fulfill(status=422, json={'detail': 'GoCardless request failed. Re-link the bank to renew access.'})
                return route.fulfill(json=[{'gocardless_account_id': 'synthetic-account', 'bank_account_id': 'bank', 'balances': []}])
            if path.endswith('/bank-accounts'):
                return route.fulfill(json=[{'id': 'bank', 'name': 'Synthetic bank', 'currency': 'EUR'}])
            if path.endswith('/pull'):
                state['connection_status'] = 'Reauth Required'
                return route.fulfill(json={'imported': 0, 'skipped': 2})
            if path.startswith('/api/'):
                return route.fulfill(json=[])
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#integrations')
        status = page.locator('.bank-feed-status')
        playwright.expect(status).to_contain_text(words['Daily bank feed'])
        playwright.expect(status).to_contain_text('2026-10-12T05:00:00Z')
        playwright.expect(status).to_contain_text(words['Last pull result'] + ': ' + words['Success'])
        if connection_status == 'Connected':
            page.get_by_role('button', name=words['Pull now'], exact=True).click()
        elif connection_status == 'Reauth Required':
            assert not any(path.endswith('/accounts') for path in calls)
        playwright.expect(status.get_by_role('alert')).to_have_text(words['Bank consent has expired. Re-link the bank to resume daily pulls.'])
        page.set_viewport_size({'width': 390, 'height': 844})
        assert status.evaluate('el => el.scrollWidth <= el.clientWidth')
        assert not errors
        browser.close()
