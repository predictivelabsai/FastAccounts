"""Statement download dialog regressions with intercepted browser requests."""
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

playwright = pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('language,currency', [('en', 'GBP'), ('et', 'EUR')])
def test_contact_statement_download_dialog(monkeypatch, language, currency):
    from web import i18n
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_ALLOW_TEST_AUTH', 'true')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    root = Path(__file__).resolve().parents[1]
    requests = []
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
            path = url.path
            if path == '/api/organisations':
                return route.fulfill(json=[dict(id='org', name='Synthetic company', country_code='EE' if currency == 'EUR' else 'UK', base_currency=currency)])
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic-token'})
            if path.endswith('/contacts'):
                return route.fulfill(json=[dict(id='contact', name='Synthetic Õun OÜ', contact_type='both', country_code='EE')])
            if path.endswith('/statement'):
                requests.append(parse_qs(url.query))
                if len(requests) == 1:
                    return route.fulfill(status=422, json={'detail': 'Statement start must be on or before its end'})
                return route.fulfill(json={'closing_balance': '10.00'})
            if path.endswith('/statement.pdf'):
                return route.fulfill(body=b'%PDF-1.4\nsynthetic', content_type='application/pdf',
                    headers={'Content-Disposition': 'attachment; filename="statement-synthetic.pdf"'})
            if path.startswith('/api/'):
                return route.fulfill(json=[])
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#contacts')
        page.get_by_role('button', name=words['Statement of account'], exact=True).click()
        dialog = page.get_by_role('dialog')
        dialog.locator('[name=date_from]').fill('2026-10-02')
        dialog.locator('[name=date_to]').fill('2026-10-01')
        dialog.locator('[name=side]').select_option('supplier')
        if currency == 'GBP':
            dialog.locator('[name=eur_rate]').fill('1.15')
        submit = dialog.get_by_role('button', name=words['Download statement PDF'], exact=True)
        submit.click()
        playwright.expect(dialog.locator('.form-error')).to_have_text(words['Statement start must be on or before its end'])
        dialog.locator('[name=date_from]').fill('2026-10-01')
        page.set_viewport_size({'width': 390, 'height': 844})
        assert dialog.evaluate('el => el.scrollWidth <= el.clientWidth')
        with page.expect_download() as download:
            submit.click()
        assert download.value.suggested_filename == 'statement-synthetic.pdf'
        playwright.expect(page.get_by_role('dialog')).to_have_count(0)
        assert requests[-1]['side'] == ['supplier']
        assert requests[-1]['date_from'] == requests[-1]['date_to'] == ['2026-10-01']
        if currency == 'GBP':
            assert requests[-1]['eur_rate'] == ['1.15']
        assert not errors
        browser.close()
