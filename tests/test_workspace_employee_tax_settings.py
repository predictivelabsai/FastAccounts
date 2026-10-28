"""Offline browser coverage for the employee tax-election editor."""
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from organisations import OrganisationService
from payroll import PayrollService
from payroll_tax_settings import EmployeeTaxSettingsService
from web import i18n

ACTOR = 'owner@example.test'


@pytest.mark.parametrize('language,width', [('en', 1280), ('et', 375), ('lv', 375), ('lt', 1280)])
def test_employee_tax_dialog_crud_and_frozen_rows(db, ee_org, monkeypatch, language, width):
    _exercise(db, ee_org, monkeypatch, language, width, viewer=False)


@pytest.mark.parametrize('width', [375, 1280])
def test_employee_tax_dialog_viewer_is_read_only(db, ee_org, monkeypatch, width):
    _exercise(db, ee_org, monkeypatch, 'et', width, viewer=True)


def _exercise(db, ee_org, monkeypatch, language, width, viewer):
    from web_app import app
    playwright = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    payroll = PayrollService(db)
    person = payroll.save_employee(ee_org['id'], actor=ACTOR, name='Synthetic tax settings employee',
                                   gross_salary='2000', personal_id='49001010018')
    run = payroll.create_run(ee_org['id'], period='2026-09', actor=ACTOR)
    payroll.approve(ee_org['id'], run['id'], actor=ACTOR)
    actor = ACTOR
    if viewer:
        actor = 'viewer@example.test'
        OrganisationService(db).add_member(ee_org['id'], ACTOR, actor, 'viewer')
    root = Path(__file__).resolve().parents[1]
    labels = i18n.catalog(language)['workspace']
    errors = []
    with TestClient(app) as client, playwright.sync_playwright() as runtime:
        html = client.get('/auth/test?email=' + actor).text
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': 900})
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
            if path.startswith('/static/') and (root / path.lstrip('/')).is_file():
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#payroll')
        page.locator('#app-content tr').filter(has_text=person['name']).get_by_role('button', name=labels['Edit'], exact=True).click()
        dialog = page.get_by_role('dialog')
        playwright.expect(dialog.get_by_role('heading', name=labels['Tax settings'], exact=True)).to_be_visible()
        histories = dialog.locator('.tax-history')
        playwright.expect(histories).to_have_count(3)
        playwright.expect(histories.get_by_text(labels['Used in approved payroll'], exact=True)).to_have_count(3)
        assert dialog.get_by_label(labels['Date of birth'], exact=True).input_value() == '1990-01-01'
        if viewer:
            assert dialog.locator('input:enabled,select:enabled,[type=submit]:enabled').count() == 0
            assert dialog.get_by_role('button', name=labels['Add tax setting'], exact=True).count() == 0
            assert dialog.get_by_role('button', name=labels['Delete'], exact=True).count() == 0
        else:
            histories.nth(0).get_by_role('button', name=labels['Add tax setting'], exact=True).click()
            editor = dialog.locator('[data-tax-editor]')
            editor.get_by_label(labels['Effective from'], exact=True).fill('2026-10-15')
            editor.get_by_role('combobox', name=labels['Tax-free income application'], exact=True).select_option('limited')
            editor.get_by_label(labels['Monthly limit'], exact=True).fill('300')
            editor.get_by_role('button', name=labels['Save tax setting'], exact=True).click()
            playwright.expect(histories.nth(0).get_by_text('2026-10-15', exact=True)).to_be_visible()
            added = histories.nth(0).locator('tr').filter(has_text='2026-10-15')
            added.get_by_role('button', name=labels['Edit'], exact=True).click()
            editor.get_by_label(labels['Monthly limit'], exact=True).fill('200')
            editor.get_by_role('button', name=labels['Save tax setting'], exact=True).click()
            playwright.expect(editor.locator('form')).to_have_count(0)
            settings = EmployeeTaxSettingsService(db).list(ee_org['id'], person['id'])
            assert next(r for r in settings if r['start_date'] == '2026-10-15')['amount'] == '200.00'
            if language == 'et':
                histories.nth(0).scroll_into_view_if_needed()
                (root / '.tmp').mkdir(exist_ok=True)
                page.screenshot(path=str(root / '.tmp' / 'employee-tax-settings-et-mobile.png'))
            added.get_by_role('button', name=labels['Delete'], exact=True).click()
            playwright.expect(histories.nth(0).get_by_text('2026-10-15', exact=True)).to_have_count(0)
            # Contact writes still use the employee form, preserving approved elections.
            dialog.get_by_label(labels['Phone'], exact=True).fill('+372 555 0100')
            dialog.get_by_role('button', name=labels['Save'], exact=True).click()
            playwright.expect(page.get_by_role('dialog')).to_have_count(0)
            assert payroll.employees(ee_org['id'])[0]['phone'] == '+372 555 0100'
        assert not errors
        browser.close()

