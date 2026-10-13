"""Offline periodised purchase creation and posting in all four locales."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

playwright = pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_periodised_workspace(monkeypatch, language):
    from web import i18n
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_ALLOW_TEST_AUTH', 'true')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    root = Path(__file__).resolve().parents[1]
    records, calls = [], []
    bill = dict(id='bill', document_type='bill', supplier_number='SYNTHETIC-001', contact_name='Synthetic <supplier>')
    account = dict(id='expense', code='6010', name='Synthetic expense', account_type='Expense', active=1)
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
            path, method = urlsplit(route.request.url).path, route.request.method
            base = '/api/organisations/org'
            if path == '/api/organisations':
                return route.fulfill(json=[dict(id='org', name='Synthetic company', country_code='EE', base_currency='EUR')])
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic-token'})
            if path == base + '/bills':
                return route.fulfill(json=[bill])
            if path == base + '/accounts':
                return route.fulfill(json=[account])
            if path == base + '/purchase-schedules' and method == 'GET':
                return route.fulfill(json=records, content_type='application/json')
            if path.startswith(base + '/purchase-schedules'):
                payload = route.request.post_data_json if route.request.post_data else None
                if method != 'GET':
                    calls.append((method, path, payload, route.request.headers.get('x-csrf-token')))
                if path == base + '/purchase-schedules':
                    record = dict(id='schedule', status='Active', supplier_number=bill['supplier_number'],
                        contact_name=bill['contact_name'], currency='EUR', net_amount='1200.01',
                        posted_periods=0, cancelled_amount='0.00', periods=[
                            dict(id='p1', period_date='2026-01-31', net_amount='100.01', status='Pending'),
                            dict(id='p2', period_date='2026-02-28', net_amount='100.00', status='Pending')], **payload)
                    records.append(record)
                    return route.fulfill(json=record, status=201)
                record = records[0]
                if path.endswith('/post'):
                    record['posted_periods'] = 1
                    record['periods'][0]['status'] = 'Posted'
                if path.endswith('/cancel'):
                    record['status'] = 'Cancelled'
                    record['cancelled_amount'] = '1100.00'
                    record['periods'][1]['status'] = 'Cancelled'
                if method == 'PATCH':
                    record.update(payload)
                return route.fulfill(json=record)
            if path.startswith('/api/'):
                return route.fulfill(json=[])
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#periodised')
        page.wait_for_function("document.querySelector('#app-content').getAttribute('aria-busy') === null")
        assert words['Unable to load this view'] not in page.locator('#app-content').inner_text(), page.locator('#app-content').inner_text()
        playwright.expect(page.locator('#app-content h1')).to_have_text(words['Periodised'])
        playwright.expect(page.locator('[data-view=periodised]')).to_have_text(i18n.catalog(language)['nav']['periodised'])
        page.locator('#app-content [data-action=newPurchaseSchedule]').first.click()
        dialog = page.get_by_role('dialog')
        playwright.expect(dialog).to_contain_text(words['VAT stays on the original bill. Portions transfer net expense only.'])
        dialog.locator('[name=start_period]').fill('2026-01-31')
        dialog.locator('[name=number_of_periods]').fill('12')
        dialog.locator('[name=split_rule]').select_option('equal_last')
        dialog.locator('[name=notes]').fill('Synthetic <insurance>')
        dialog.get_by_role('button', name=words['Create schedule'], exact=True).click()
        playwright.expect(dialog).to_have_count(0)
        assert calls[0][2]['number_of_periods'] == 12 and calls[0][2]['split_rule'] == 'equal_last'
        assert calls[0][2]['bill_id'] == 'bill' and calls[0][2]['expense_account_id'] == 'expense'
        assert calls[0][2]['notes'] == 'Synthetic <insurance>'
        playwright.expect(page.locator('#app-content')).to_contain_text('Synthetic <supplier>')
        assert page.locator('#app-content supplier').count() == 0
        page.locator('[data-action=viewPurchaseSchedule]').click()
        dialog = page.get_by_role('dialog')
        playwright.expect(dialog).to_contain_text(words['Purchase periods'])
        playwright.expect(dialog).to_contain_text(words['Pending'])
        dialog.get_by_role('button', name=words['Close'], exact=True).click()
        page.locator('[data-action=postPurchaseSchedule]').click()
        dialog = page.get_by_role('dialog')
        playwright.expect(dialog).to_contain_text(words['Post balanced net expense transfers for all due portions. VAT stays on the original bill.'])
        dialog.get_by_role('button', name=words['Confirm'], exact=True).click()
        playwright.expect(page.locator('#app-content')).to_contain_text('1 / 12')
        page.locator('[data-action=cancelPurchaseSchedule]').click()
        dialog = page.get_by_role('dialog')
        playwright.expect(dialog).to_contain_text(words['Future portions stop. Any remaining deferred cost needs accountant review.'])
        dialog.get_by_role('button', name=words['Confirm'], exact=True).click()
        playwright.expect(page.locator('#app-content')).to_contain_text(words['Cancelled'])
        playwright.expect(page.locator('[data-action=postPurchaseSchedule]')).to_have_count(0)
        playwright.expect(page.locator('[data-action=cancelPurchaseSchedule]')).to_have_count(0)
        records[0]['status'] = 'Draft'
        page.reload()
        page.locator('[data-action=activatePurchaseSchedule]').click()
        playwright.expect(page.locator('[data-action=postPurchaseSchedule]')).to_be_visible()
        assert calls[-1][0] == 'PATCH' and calls[-1][2] == {'status': 'Active'}
        assert all(c[3] == 'synthetic-token' for c in calls)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.locator('#app-content').evaluate('el => el.scrollWidth <= el.clientWidth')
        assert not errors
        browser.close()
