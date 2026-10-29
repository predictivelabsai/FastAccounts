from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from database import reset_database_cache
from organisations import OrganisationService
from web_app import app


def test_bureau_overview_matrix_and_invitation_flow(db, ee_org, monkeypatch):
    playwright = pytest.importorskip('playwright.sync_api')
    actor = 'owner@example.test'
    other = OrganisationService(db).create(name='Second bureau client', country_code='EE', entity_type='EE_OU',
                                            owner_email='other@example.test')
    OrganisationService(db).create(name='Unrelated bureau client', country_code='EE', entity_type='EE_OU',
                                   owner_email='outsider@example.test')
    with db.transaction() as tx:
        tx.execute('INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)',
                   ('bureau-accountant', other['id'], actor, 'accountant', '2026-01-01'))
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', 'en')
    reset_database_cache()
    errors = []
    with TestClient(app) as client, playwright.sync_playwright() as runtime:
        html = client.get('/auth/test?email=' + actor).text
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path.startswith('/api/'):
                response = client.request(route.request.method, path, content=route.request.post_data,
                    headers={'X-Test-User': actor, 'Content-Type': 'application/json'})
                return route.fulfill(status=response.status_code, body=response.content,
                    content_type=response.headers.get('content-type', 'application/json'))
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            root = Path(__file__).resolve().parents[1]
            if path.startswith('/static/') and (root / path.lstrip('/')).is_file():
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#bureau-overview')
        playwright.expect(page.get_by_role('heading', name='Companies overview', exact=True)).to_be_visible()
        playwright.expect(page.locator('#app-content')).to_contain_text(ee_org['name'])
        playwright.expect(page.locator('#app-content')).to_contain_text(other['name'])
        playwright.expect(page.locator('#app-content')).not_to_contain_text('Unrelated bureau client')
        page.evaluate("location.hash = 'bureau-memberships'")
        page.get_by_role('button', name='Manage membership', exact=True).first.click()
        dialog = page.get_by_role('dialog')
        dialog.locator('input[name="email"]').fill('new-member@example.test')
        dialog.locator('select[name="role"]').select_option('viewer')
        dialog.get_by_role('button', name='Create invitation', exact=True).click()
        playwright.expect(dialog).to_contain_text('Invitation created')
        playwright.expect(dialog.locator('code')).not_to_be_empty()
        assert not errors, errors
        browser.close()
