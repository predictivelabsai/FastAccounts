"""Offline payment method editing and invoice link controls in all four locales."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

playwright = pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_payment_links_workspace(monkeypatch, language):
    from web import i18n
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_ALLOW_TEST_AUTH', 'true')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    root = Path(__file__).resolve().parents[1]
    records, calls = [], []
    invoice = dict(id='invoice', number='SYNTHETIC-001', contact_name='Synthetic <customer>',
                   status='Issued', issue_date='2026-01-01', due_date='2026-01-31', currency='EUR', total='10.01', paid_total='0.00')
    pay_url = 'https://pay.example.test/synthetic-token?amount=10.01&invoice=SYNTHETIC-001'
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
        page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async value => {window.copiedPaymentLink = value;}}});")

        def respond(route):
            path, method = urlsplit(route.request.url).path, route.request.method
            base = '/api/organisations/org'
            if path == '/api/organisations':
                return route.fulfill(json=[dict(id='org', name='Synthetic company', country_code='EE', base_currency='EUR', role='owner')])
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic-token'})
            if path == base + '/payment-methods' and method == 'GET':
                return route.fulfill(json=records, content_type='application/json')
            if path.startswith(base + '/payment-methods'):
                payload = route.request.post_data_json
                calls.append((method, payload, route.request.headers.get('x-csrf-token')))
                if method == 'POST':
                    record = dict(id='method', **payload)
                    records.append(record)
                else:
                    records[0].update(payload)
                return route.fulfill(json=records[0], status=201 if method == 'POST' else 200)
            if path == base + '/invoices':
                return route.fulfill(json=[invoice])
            if path == base + '/invoices/invoice':
                links = [dict(id='link', name=records[0]['name'], provider='everypay', url=pay_url)] if records and records[0]['enabled'] else []
                return route.fulfill(json=invoice | {'payment_links': links})
            if path.startswith('/api/'):
                return route.fulfill(json=[], content_type='application/json')
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#payment-methods')
        page.wait_for_function("document.querySelector('#app-content').getAttribute('aria-busy') === null")
        assert words['Unable to load this view'] not in page.locator('#app-content').inner_text(), page.locator('#app-content').inner_text()
        playwright.expect(page.locator('#app-content h1')).to_have_text(words['Payment methods'])
        playwright.expect(page.locator('[data-view=payment-methods]')).to_have_text(i18n.t('nav.payment_methods', language))
        page.locator('[data-action=newPaymentMethod]').click()
        dialog = page.get_by_role('dialog')
        dialog.locator('[name=provider]').select_option('everypay')
        dialog.locator('[name=name]').fill('Synthetic <EveryPay>')
        dialog.locator('[name=url_template]').fill('https://pay.example.test/{token}?amount={invoice_due}')
        dialog.locator('[name=currency]').fill('EUR')
        dialog.locator('[name=enabled]').check()
        dialog.get_by_role('button', name=words['Save'], exact=True).click()
        playwright.expect(dialog).to_have_count(0)
        assert calls[0][1] == dict(provider='everypay', name='Synthetic <EveryPay>',
            url_template='https://pay.example.test/{token}?amount={invoice_due}', currency='EUR', enabled=True)
        assert page.locator('#app-content EveryPay').count() == 0
        page.locator('[data-view=invoices]').click()
        page.locator('[data-action=invoiceAttachments]').click()
        dialog = page.get_by_role('dialog')
        playwright.expect(dialog).to_contain_text(words['Payment links'])
        playwright.expect(dialog.locator('[name=payment_link_0]')).to_have_value(pay_url)
        playwright.expect(dialog.locator(f'a[href="{pay_url}"]')).to_have_attribute('rel', 'noopener noreferrer')
        dialog.get_by_role('button', name=words['Copy link'], exact=True).click()
        page.wait_for_function('window.copiedPaymentLink !== undefined')
        assert page.evaluate('window.copiedPaymentLink') == pay_url
        assert page.locator('customer').count() == 0
        dialog.get_by_role('button', name=words['Close'], exact=True).click()
        page.locator('[data-view=payment-methods]').click()
        page.locator('[data-action=editPaymentMethod]').click()
        dialog = page.get_by_role('dialog')
        dialog.locator('[name=provider]').select_option('linkpay')
        dialog.locator('[name=enabled]').uncheck()
        dialog.get_by_role('button', name=words['Save'], exact=True).click()
        playwright.expect(dialog).to_have_count(0)
        assert calls[-1][0] == 'PATCH' and calls[-1][1]['enabled'] is False
        assert calls[-1][1]['provider'] == 'linkpay'
        page.locator('[data-view=invoices]').click()
        page.locator('[data-action=invoiceAttachments]').click()
        dialog = page.get_by_role('dialog')
        playwright.expect(dialog).to_contain_text(words['No payment links are available for this invoice.'])
        playwright.expect(dialog.get_by_role('button', name=words['Copy link'], exact=True)).to_be_disabled()
        page.set_viewport_size({'width': 390, 'height': 844})
        assert dialog.evaluate('el => el.scrollWidth <= el.clientWidth')
        assert all(call[2] == 'synthetic-token' for call in calls)
        assert not errors
        browser.close()
