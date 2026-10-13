"""Intercepted CSV upload, review, commit and discard in all four locales."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

playwright = pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
@pytest.mark.parametrize('kind', ['contacts', 'items'])
def test_staged_master_data_flow(monkeypatch, language, kind):
    from web import i18n
    from web_app import app

    monkeypatch.setenv('FASTACCOUNTS_ALLOW_TEST_AUTH', 'true')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    root = Path(__file__).resolve().parents[1]
    calls = []
    batch = dict(id='batch', kind=kind, status='staged', total_rows=3, error_count=1, warning_count=1, rows=[
        dict(row_number=2, parsed={'name': 'Synthetic <customer>'}, error='', warning='', entity_id=None),
        dict(row_number=3, parsed={'name': 'Bad'}, error='Invalid email', warning='', entity_id=None),
        dict(row_number=4, parsed={'name': 'Existing'}, error='', warning='Existing record will be skipped', entity_id=None),
    ])
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
            if path == '/api/organisations':
                return route.fulfill(json=[dict(id='org', name='Synthetic company', country_code='EE', base_currency='EUR')])
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic-token'})
            if path == '/api/organisations/org/imports':
                payload = route.request.post_data_json
                calls.append(payload)
                batch['status'] = 'staged'
                return route.fulfill(json=batch)
            if path.endswith('/imports/batch/commit') or path.endswith('/imports/batch/discard'):
                action = path.rsplit('/', 1)[1]
                calls.append(action)
                batch['status'] = 'committed' if action == 'commit' else 'discarded'
                if action == 'commit':
                    batch['rows'][0]['entity_id'] = 'synthetic-created-id'
                    batch['rows'][2]['warning'] = 'Existing record skipped'
                return route.fulfill(json=batch)
            if path.endswith('/imports/batch'):
                return route.fulfill(json=batch)
            if path.startswith('/api/'):
                return route.fulfill(json=[])
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#imports')
        assert not errors
        playwright.expect(page.locator('#app-content h1')).to_have_text(words['Data import'])
        page.get_by_role('button', name=words['Import'], exact=True).click()
        page.locator('[name=kind]').select_option(kind)
        content = 'name,contact_type\nSynthetic,both\n' if kind == 'contacts' else 'code,name\nSYN,Synthetic\n'
        page.locator('[name=csv_file]').set_input_files({'name': 'synthetic.csv', 'mimeType': 'text/csv', 'buffer': content.encode()})
        page.get_by_role('button', name=words['Stage import'], exact=True).click()
        playwright.expect(page.locator('#app-content')).to_contain_text(words['Staged import'])
        assert calls[0] == {'kind': kind, 'csv_content': content}
        playwright.expect(page.locator('#app-content')).to_contain_text('Synthetic <customer>')
        playwright.expect(page.locator('#app-content')).to_contain_text(words['Invalid email'])
        playwright.expect(page.locator('#app-content')).to_contain_text(words['Existing record will be skipped'])
        page.get_by_role('button', name=words['Import valid rows'], exact=True).click()
        playwright.expect(page.locator('#app-content')).to_contain_text(words['Import committed'])
        playwright.expect(page.locator('#app-content')).to_contain_text('synthetic-created-id')
        assert calls[-1] == 'commit'
        assert page.get_by_role('button', name=words['Import valid rows'], exact=True).count() == 0
        page.goto('http://workspace.test/app#imports')
        page.get_by_role('button', name=words['Import'], exact=True).click()
        page.locator('[name=kind]').select_option(kind)
        page.locator('[name=csv_content]').fill(content)
        page.get_by_role('button', name=words['Stage import'], exact=True).click()
        playwright.expect(page.locator('#app-content')).to_contain_text(words['Staged import'])
        page.get_by_role('button', name=words['Discard import'], exact=True).click()
        playwright.expect(page.locator('#app-content')).to_contain_text(words['Import discarded'])
        assert calls[-1] == 'discard'
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.locator('#app-content').evaluate('el => el.scrollWidth <= el.clientWidth')
        assert not errors
        browser.close()
