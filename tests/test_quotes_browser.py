"""Offline quote creation, editing and closing flows in all four locales."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

playwright = pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_quotes_workspace_lifecycle(monkeypatch, language):
    from web import i18n
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_ALLOW_TEST_AUTH', 'true')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    root = Path(__file__).resolve().parents[1]
    records, calls = [], []
    contact = dict(id='customer', name='Synthetic <customer>', contact_type='customer')
    account = dict(id='sales', code='4010', name='Synthetic sales', account_type='Income', active=1)
    tax = dict(id='tax', code='VAT', rate=24, kind='standard', active=1)
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
            method = route.request.method
            base = '/api/organisations/org'
            if path == '/api/organisations':
                return route.fulfill(json=[dict(id='org', name='Synthetic company', country_code='EE', base_currency='EUR')])
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token':'synthetic-token'})
            if path == base + '/contacts':
                return route.fulfill(json=[contact])
            if path == base + '/accounts':
                return route.fulfill(json=[account])
            if path == base + '/tax-codes':
                return route.fulfill(json=[tax])
            if path == base + '/quotes' and method == 'GET':
                return route.fulfill(json=records, content_type='application/json')
            if path.startswith(base + '/quotes'):
                payload = route.request.post_data_json if method in {'POST','PATCH'} else None
                if method != 'GET':
                    calls.append((method, path, payload, route.request.headers.get('x-csrf-token')))
                if path == base + '/quotes':
                    record = dict(id=f'q{len(records)+1}', quote_number=f'QUO-{len(records)+1:06d}', status='Draft',
                                  contact_name=contact['name'], currency='EUR', subtotal=100, tax_total=0, total=100, **payload)
                    record['line_amount_type'] = record.pop('amount_type')
                    for line in record['lines']:
                        line['gross_amount'] = 50
                    records.append(record)
                    return route.fulfill(json=record, status=201)
                parts = path[len(base+'/quotes/'):].split('/')
                record = next(x for x in records if x['id'] == parts[0])
                if method == 'PATCH':
                    record.update(payload)
                    record['line_amount_type'] = record.pop('amount_type')
                    for line in record['lines']:
                        line['gross_amount'] = 50
                elif len(parts) == 2:
                    action = parts[1]
                    record['status'] = {'send':'Sent','accept':'Accepted','decline':'Declined','expire-status':'Expired','convert':'Converted'}[action]
                    if action == 'convert':
                        record['converted_invoice_id'] = 'invoice'
                        return route.fulfill(json={'id':'invoice','number':'INV-000001','status':'Issued'})
                return route.fulfill(json=record)
            if path.startswith('/api/'):
                return route.fulfill(json=[])
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js','/static/app.css'):
                return route.fulfill(path=str(root/path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#quotes')
        page.wait_for_function("document.querySelector('#app-content').getAttribute('aria-busy') === null")
        assert 'Unable to load this view' not in page.locator('#app-content').inner_text(), page.locator('#app-content').inner_text()
        playwright.expect(page.locator('#app-content h1')).to_have_text(words['Quotes'])
        playwright.expect(page.locator('[data-view=quotes]')).to_have_text(i18n.catalog(language)['nav']['quotes'])
        page.locator('#app-content [data-action=newQuote]').first.click()
        dialog = page.get_by_role('dialog')
        dialog.locator('[name=quote_date]').fill('2099-01-01')
        dialog.locator('[name=valid_until]').fill('2099-01-31')
        dialog.locator('[name=notes]').fill('Synthetic <offer>')
        dialog.locator('[name=description_0]').fill('Service <one>')
        dialog.locator('[name=unit_price_0]').fill('42.1234')
        dialog.locator('[name=tax_code_id_0]').select_option('tax')
        dialog.get_by_role('button', name=words['Add line'], exact=True).click()
        dialog.locator('[name=description_1]').fill('Service two')
        dialog.locator('[name=quantity_1]').fill('2.125')
        dialog.locator('[name=unit_price_1]').fill('15')
        dialog.get_by_role('button', name=words['Add line'], exact=True).click()
        dialog.locator('[data-quote-line="2"] [data-action=removeQuoteLine]').click()
        dialog.get_by_role('button', name=words['Create draft'], exact=True).click()
        playwright.expect(dialog).to_have_count(0)
        assert len(calls[0][2]['lines']) == 2
        assert calls[0][2]['lines'][0]['unit_price'] == '42.1234'
        assert calls[0][2]['lines'][1]['quantity'] == '2.125'
        assert calls[0][2]['lines'][0]['tax_code_id'] == 'tax'
        page.locator('[data-action=editQuote]').click()
        dialog = page.get_by_role('dialog')
        assert dialog.locator('[name=description_0]').input_value() == 'Service <one>'
        assert dialog.locator('[name=tax_code_id_0]').input_value() == 'tax'
        dialog.locator('[name=notes]').fill('Edited synthetic offer')
        dialog.locator('[name=description_1]').fill('Edited service two')
        dialog.get_by_role('button', name=words['Save'], exact=True).click()
        playwright.expect(dialog).to_have_count(0)
        assert calls[-1][0] == 'PATCH' and calls[-1][2]['notes'] == 'Edited synthetic offer'
        assert records[0]['quote_number'] == 'QUO-000001'
        page.locator('[data-action=viewQuote]').click()
        dialog = page.get_by_role('dialog')
        playwright.expect(dialog).to_contain_text(words['Quote lines'])
        playwright.expect(dialog).to_contain_text('Service <one>')
        playwright.expect(dialog).to_contain_text('Edited service two')
        dialog.get_by_role('button', name=words['Close'], exact=True).click()
        page.locator('[data-action=sendQuote]').click()
        page.get_by_role('dialog').get_by_role('button', name=words['Confirm'], exact=True).click()
        playwright.expect(page.locator('[data-action=acceptQuote]')).to_be_visible()
        playwright.expect(page.locator('[data-action=editQuote]')).to_have_count(0)
        page.locator('[data-action=acceptQuote]').click()
        playwright.expect(page.locator('[data-action=convertQuote]')).to_be_visible()
        page.locator('[data-action=convertQuote]').click()
        playwright.expect(page.get_by_role('dialog')).to_contain_text(words['This creates and issues a sales invoice with an immutable ledger posting.'])
        page.get_by_role('dialog').get_by_role('button', name=words['Confirm'], exact=True).click()
        playwright.expect(page.locator('#app-content')).to_contain_text(words['Converted'])
        playwright.expect(page.locator('[data-action=convertQuote]')).to_have_count(0)
        # Decline and expiry expose no accept or convert action after closing.
        for state, action, expected in [('Sent','declineQuote','Declined'), ('Draft','expireQuote','Expired')]:
            records.append({**records[0], 'id':f'q{len(records)+1}', 'quote_number':f'QUO-{len(records)+1:06d}',
                            'status':state, 'valid_until':'2000-01-01' if action == 'expireQuote' else '2099-01-31'})
            page.reload()
            page.locator(f'[data-action={action}]').click()
            playwright.expect(page.locator('#app-content')).to_contain_text(words[expected])
            playwright.expect(page.locator('[data-action=acceptQuote]')).to_have_count(0)
            playwright.expect(page.locator('[data-action=convertQuote]')).to_have_count(0)
        assert all(call[3] == 'synthetic-token' for call in calls)
        page.set_viewport_size({'width':390, 'height':844})
        assert page.locator('#app-content').evaluate('el => el.scrollWidth <= el.clientWidth')
        assert not errors
        browser.close()
