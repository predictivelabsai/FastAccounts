"""Browser regressions for recurring invoices and reminder delivery."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize('language', ['en', 'et'])
def test_workspace_automation(monkeypatch, language):
    playwright = pytest.importorskip('playwright.sync_api')
    from web import i18n
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    assert 'workspace-app' in html
    root = Path(__file__).resolve().parents[1]
    words = i18n.catalog(language)['workspace']
    notice = 'Email delivery is not connected. Set POSTMARK_API_TOKEN and FROM_EMAIL to send reminders.'
    schedule = dict(id='schedule', contact_name='Willow Design', name='Retainer', interval_kind='monthly',
                    next_run_date='2026-10-15', end_date=None, auto_email=False, active=True)
    invoice = dict(id='invoice', number='INV-001', contact_name='Willow Design', status='Issued',
                   due_date='2026-10-10', reminders_disabled=False, document_type='invoice')
    calls = []
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip('Install Playwright Chromium to run browser regressions')
            raise
        page = browser.new_page()

        def respond(route):
            path = urlsplit(route.request.url).path
            method = route.request.method
            if path.startswith('/api/'):
                payload = json.loads(route.request.post_data or '{}')
                calls.append((path, method, payload))
                if path == '/api/csrf':
                    return route.fulfill(json={'csrf_token': 'synthetic-token'})
                if path == '/api/organisations':
                    return route.fulfill(json=[dict(id='uk', name='UK Books', country_code='UK', base_currency='GBP')])
                if path.endswith('/invoice-schedules'):
                    return route.fulfill(json=[schedule] if method == 'GET' else schedule)
                if path.endswith('/invoice-schedules/schedule'):
                    if method == 'PATCH':
                        schedule.update(payload)
                    return route.fulfill(json={**schedule, 'runs': [dict(run_date='2026-10-08', invoice_number='INV-001', status='Issued', error_message=None)]})
                if path.endswith('/run-now'):
                    return route.fulfill(json={'runs': [dict(status='Issued')]})
                if path.endswith('/reminders/due'):
                    items = [] if invoice['reminders_disabled'] else [dict(invoice_id='invoice', number='INV-001', contact_name='Willow Design', due_date='2026-10-10', stage=0, sent=False, reminders_disabled=False)]
                    return route.fulfill(json={'email_connected': False, 'items': items})
                if path.endswith('/invoices'):
                    return route.fulfill(json=[invoice])
                if path.endswith('/send'):
                    return route.fulfill(status=422, json={'detail': notice})
                if path.endswith('/opt-out'):
                    invoice.update(payload)
                    return route.fulfill(json=payload)
                if path == '/api/email-status':
                    return route.fulfill(json=dict(connected=False, provider='postmark', from_email=''))
                return route.fulfill(body="[]", content_type="application/json")
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#recurring')
        playwright.expect(page.locator('.app-nav[data-view="recurring"]')).to_be_visible()
        playwright.expect(page.locator('#app-content tbody tr').first).to_contain_text('Retainer')
        expected_date = page.evaluate("new Intl.DateTimeFormat(document.querySelector('#workspace-app').dataset.lang === 'et' ? 'et-EE' : 'en-GB').format(new Date('2026-10-15T12:00:00'))")
        playwright.expect(page.locator('#app-content tbody tr').first).to_contain_text(expected_date)
        playwright.expect(page.locator('#app-content .notice')).to_have_text(words[notice])
        assert not any(path.endswith('/send') for path, _, _ in calls)
        page.locator('[data-action="sendReminder"]').click()
        playwright.expect(page.locator('#toasts .toast.error')).to_have_text(words[notice])
        page.locator('[data-action="skipReminder"]').click()
        playwright.expect(page.locator('[data-action="skipReminder"]')).to_have_attribute('aria-pressed', 'true')
        page.locator('[data-action="skipReminder"]').click()
        playwright.expect(page.locator('[data-action="skipReminder"]')).to_have_attribute('aria-pressed', 'false')
        page.locator('[data-action="toggleSchedule"]').click()
        playwright.expect(page.locator('[data-action="runSchedule"]')).to_be_disabled()
        page.locator('[data-action="toggleSchedule"]').click()
        playwright.expect(page.locator('[data-action="runSchedule"]')).to_be_enabled()
        page.locator('[data-action="runSchedule"]').click()
        playwright.expect(page.locator('#toasts')).to_contain_text(words['Invoices created: {count}'].replace('{count}', '1'))
        page.locator('[data-action="scheduleHistory"]').click()
        playwright.expect(page.locator('.dialog tbody')).to_contain_text('INV-001')
        page.locator('.dialog [data-close]').click()
        page.locator('[data-action="newSchedule"]').click()
        playwright.expect(page.locator('[name="interval_days"]')).to_be_hidden()
        page.locator('[name="interval_kind"]').select_option('custom_days')
        page.locator('[name="interval_days"]').fill('366')
        page.locator('.dialog [type="submit"]').click()
        playwright.expect(page.locator('[data-error="interval_days"]')).not_to_be_empty()
        assert not any(path.endswith('/invoice-schedules') and method == 'POST' for path, method, _ in calls)
        page.locator('[name="interval_days"]').fill('15')
        page.locator('.dialog [type="submit"]').click()
        playwright.expect(page.locator('.dialog')).to_have_count(0)
        creation = next(payload for path, method, payload in calls if path.endswith('/invoice-schedules') and method == 'POST')
        assert creation['interval_days'] == 15
        assert creation['auto_email'] is False
        assert creation['end_date'] is None
        page.locator('.app-nav[data-view="integrations"]').click()
        playwright.expect(page.locator('#app-content .status-pill')).to_have_text(words['Disconnected'])
        playwright.expect(page.locator('#app-content')).to_contain_text('Postmark')
        browser.close()


def test_automation_demo_seed_is_idempotent_and_uk_only(db, monkeypatch):
    from datetime import date, timedelta
    from seed import seed_demo
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    organisations = seed_demo()
    seed_demo()
    schedules = db.rows('SELECT * FROM invoice_schedules')
    assert len(schedules) == 1
    schedule = schedules[0]
    assert schedule['organisation_id'] == next(o['id'] for o in organisations if o['country_code'] == 'UK')
    assert schedule['name'] == 'Retainer – Willow Design'
    assert schedule['interval_kind'] == 'monthly'
    assert schedule['next_run_date'] == (date.today() + timedelta(days=7)).isoformat()
    assert not schedule['auto_email']
    invoice = db.one('SELECT * FROM invoices WHERE id=?', (schedule['template_invoice_id'],))
    assert invoice['status'] == 'Draft'
    assert len(db.rows("SELECT id FROM invoices WHERE reference='AUTOMATION-WILLOW-TEMPLATE'")) == 1
