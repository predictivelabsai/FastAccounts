"""Browser regressions for country/currency gating and duplicate API errors."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize('language', ['en', 'et'])
def test_payroll_scope_and_single_error(monkeypatch, language):
    playwright = pytest.importorskip('playwright.sync_api')
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    assert 'workspace-app' in html, html[:500]
    root = Path(__file__).resolve().parents[1]
    organisations = [
        dict(id='uk', name='UK Books', country_code='UK', base_currency='GBP'),
        dict(id='ee-gbp', name='EE GBP Books', country_code='EE', base_currency='GBP'),
        dict(id='ee', name='EE EUR Books', country_code='EE', base_currency='EUR'),
    ]
    calls = []
    fail = False
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip('Install Playwright Chromium to run browser regressions')
            raise
        page = browser.new_page()

        def respond(route):
            from urllib.parse import urlsplit
            path = urlsplit(route.request.url).path
            if path.startswith('/api/'):
                calls.append(path)
                if path == '/api/csrf':
                    return route.fulfill(json={'csrf_token': 'synthetic-token'})
                if path == '/api/organisations':
                    return route.fulfill(json=organisations)
                if fail and path.endswith(('/employees', '/pay-runs')):
                    return route.fulfill(status=500, json={'detail': 'Synthetic payroll outage'})
                return route.fulfill(body="[]", content_type="application/json")
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app')
        playwright.expect(page.locator('.kpi')).to_have_count(4)
        nav = page.locator('.app-nav[data-view="payroll"]')
        for oid in ('uk', 'ee-gbp'):
            page.locator('#org-trigger').click()
            page.locator(f'[data-org="{oid}"]').click()
            playwright.expect(nav).to_have_attribute('aria-disabled', 'true')
            playwright.expect(nav).to_have_css('opacity', '0.45')
            playwright.expect(page.locator('.kpi').nth(3).locator('strong')).to_have_text('—')
            assert nav.get_attribute('title')
            # Bypass Playwright's aria-disabled actionability check to exercise a real click.
            nav.click(force=True)
            playwright.expect(page).to_have_url('http://workspace.test/app#payroll')
            playwright.expect(page.locator('#app-content .notice')).to_have_count(1)
            from web import i18n
            notice = ('Payroll is available only for Estonian organisations with EUR books. '
                      'Switch to an Estonian EUR organisation to manage payroll.')
            playwright.expect(page.locator('#app-content .notice')).to_have_text(
                i18n.catalog(language)['workspace'][notice])
            playwright.expect(page.locator('#toasts .toast')).to_have_count(0)
            assert not any(url.endswith(('/employees', '/pay-runs')) for url in calls)
            page.evaluate("location.hash = 'overview'")
            playwright.expect(page.locator('.kpi')).to_have_count(4)
        if language == 'et':
            assert nav.get_attribute('title') == 'Palgaarvestus on praegu saadaval ainult Eesti ettevõtetele.'
        page.locator('#org-trigger').click()
        page.locator('[data-org="ee"]').click()
        playwright.expect(nav).to_have_attribute('aria-disabled', 'false')
        playwright.expect(nav).to_have_css('opacity', '1')
        playwright.expect(nav).to_have_attribute('title', '')
        nav.click()
        playwright.expect(page.locator('[data-action="employee"]').first).to_be_visible()
        assert '/api/organisations/ee/employees' in calls
        assert '/api/organisations/ee/pay-runs' in calls
        page.evaluate("location.hash = 'overview'")
        playwright.expect(page.locator('.kpi')).to_have_count(4)
        fail = True
        nav.click()
        playwright.expect(page.locator('#toasts .toast')).to_have_count(1)
        playwright.expect(page.locator('#app-content h1')).to_be_visible()
        browser.close()


def test_estonian_demo_tax_names_and_unmatched_pill(db, monkeypatch):
    """Render the real seeded API data through the workspace JavaScript."""
    playwright = pytest.importorskip('playwright.sync_api')
    from seed import seed_demo
    from web_app import app

    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', 'et')
    ee = next(org for org in seed_demo() if org['country_code'] == 'EE')
    root = Path(__file__).resolve().parents[1]
    with TestClient(app) as client, playwright.sync_playwright() as p:
        html = client.get('/auth/test').text
        try:
            browser = p.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip('Install Playwright Chromium to run browser regressions')
            raise
        page = browser.new_page()

        def respond(route):
            from urllib.parse import urlsplit
            url = urlsplit(route.request.url)
            if url.path.startswith('/api/'):
                response = client.get(url.path + ('?' + url.query if url.query else ''))
                return route.fulfill(status=response.status_code, body=response.content,
                                     content_type='application/json')
            if url.path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if url.path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / url.path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app')
        playwright.expect(page.locator('.user-card strong')).to_have_text('Demo Kasutaja')
        playwright.expect(page.locator('.kpi')).to_have_count(4)
        page.locator('#org-trigger').click()
        page.locator(f'[data-org="{ee["id"]}"]').click()
        page.locator('.app-nav[data-view="tax"]').click()
        playwright.expect(page.locator('#app-content tbody tr')).to_have_count(8)
        expected = client.get(f'/api/organisations/{ee["id"]}/tax-codes').json()
        assert page.locator('#app-content tbody tr td:nth-child(2)').all_text_contents() == [
            row['name'] for row in expected]
        playwright.expect(page.get_by_text('Standardmäär 24%', exact=True)).to_be_visible()
        page.locator('.app-nav[data-view="banking"]').click()
        playwright.expect(page.locator('.status-pill').filter(has_text='Vastendamata').first).to_be_visible()
        assert 'Unmatched' not in page.locator('#app-content').inner_text()
        browser.close()
