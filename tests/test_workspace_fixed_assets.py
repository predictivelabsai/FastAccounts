"""Critical fixed asset workspace dialogs with fake API responses."""
import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_workspace_asset_acquisition_run_and_disposal(monkeypatch, language):
    playwright = pytest.importorskip('playwright.sync_api')
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    root = Path(__file__).resolve().parents[1]
    groups = [dict(id='group', name='Synthetic equipment', annual_percentage='20', frequency='monthly')]
    assets, runs, calls, errors = [], [], [], []
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip('Install Playwright Chromium to run browser regressions')
            raise
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            method = route.request.method
            if path.startswith('/api/'):
                payload = json.loads(route.request.post_data or '{}')
                calls.append((path, method, payload))
                if path == '/api/csrf':
                    return route.fulfill(json={'csrf_token': 'synthetic-token'})
                if path == '/api/organisations':
                    return route.fulfill(json=[dict(id='ee', name='Synthetic Books', country_code='EE', base_currency='EUR', role='owner')])
                if path.endswith('/asset-groups'):
                    if method == 'POST':
                        groups.append(dict(id='custom', **payload))
                    return route.fulfill(json=groups if method == 'GET' else groups[-1])
                if path.endswith('/bank-accounts'):
                    return route.fulfill(json=[dict(id='bank', name='Synthetic bank', currency='EUR')])
                if path.endswith('/fixed-assets'):
                    if method == 'POST':
                        assets.append(dict(id='asset', status='Active', accumulated_depreciation='0.00', carrying_value=payload['acquisition_cost'], **payload))
                        return route.fulfill(json=assets[-1])
                    total = dict(acquisition_cost='1200.00' if assets else '0.00', accumulated_depreciation='20.00' if runs else '0.00', carrying_value=assets[0]['carrying_value'] if assets else '0.00')
                    return route.fulfill(json=dict(assets=assets, groups=[dict(name='Synthetic equipment', **total)], totals=total))
                if path.endswith('/fixed-assets/schedule'):
                    return route.fulfill(body=json.dumps([dict(name='Synthetic desk', frequency='monthly', next_due_date='2026-11-30', amount='20.00')] if assets and assets[0]['status'] == 'Active' else []), content_type='application/json')
                if path.endswith('/fixed-assets/runs'):
                    if method == 'POST':
                        runs.append(dict(id='run', status='Posted', posting_batch_id='batch', **payload))
                        assets[0].update(accumulated_depreciation='20.00', carrying_value='1180.00')
                    return route.fulfill(body=json.dumps(runs if method == 'GET' else runs[-1]), content_type='application/json')
                if path.endswith('/dispose'):
                    assets[0].update(status='Disposed', carrying_value='0.00')
                    return route.fulfill(json=assets[0])
                return route.fulfill(json=[])
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#fixed-assets')
        playwright.expect(page.locator('.app-nav[data-view="fixed-assets"]')).to_be_visible()
        playwright.expect(page.locator('[data-action="acquireAsset"]')).to_be_enabled()
        page.locator('[data-action="addAssetGroup"]').click()
        page.locator('.dialog [name="name"]').fill('Synthetic custom group')
        page.locator('.dialog [name="frequency"]').select_option('quarterly')
        page.locator('.dialog [type="submit"]').click()
        playwright.expect(page.locator('.dialog')).to_have_count(0)
        page.locator('[data-action="acquireAsset"]').click()
        page.locator('.dialog [name="name"]').fill('Synthetic desk')
        page.locator('.dialog [name="acquisition_date"]').fill('2026-10-01')
        page.locator('.dialog [name="acquisition_cost"]').fill('1200.00')
        page.locator('.dialog [type="submit"]').click()
        playwright.expect(page.locator('.dialog')).to_have_count(0)
        playwright.expect(page.locator('#app-content tbody').first).to_contain_text('Synthetic desk')
        page.locator('[data-action="runDepreciation"]').click()
        page.locator('.dialog [name="period_date"]').fill('2026-10-31')
        page.locator('.dialog [type="submit"]').click()
        playwright.expect(page.locator('.dialog')).to_have_count(0)
        playwright.expect(page.locator('#app-content')).to_contain_text('batch')
        page.locator('[data-action="disposeAsset"]').click()
        page.locator('.dialog [name="disposal_date"]').fill('2026-10-31')
        page.locator('.dialog [name="disposal_amount"]').fill('900.00')
        page.locator('.dialog [type="submit"]').click()
        playwright.expect(page.locator('.dialog')).to_have_count(0)
        playwright.expect(page.locator('[data-action="disposeAsset"]')).to_have_count(0)
        acquisitions = [payload for path, method, payload in calls if path.endswith('/fixed-assets') and method == 'POST']
        assert len(acquisitions) == 1 and acquisitions[0]['idempotency_key']
        assert not errors
        browser.close()
