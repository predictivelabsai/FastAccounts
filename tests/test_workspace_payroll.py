"""Browser regressions for country/currency gating and duplicate API errors."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_payslip_accessible_names_include_employee(monkeypatch, language):
    playwright = pytest.importorskip('playwright.sync_api')
    from urllib.parse import urlsplit
    from web import i18n
    from web_app import app

    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    root = Path(__file__).resolve().parents[1]
    names = ['Synthetic Mari <one>', 'Synthetic Jaan']
    items = [dict(employee_name=name, gross='1000', income_tax='100', net='900', social_tax='330', employer_cost='1330', pension='0') for name in names]
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={'width': 375, 'height': 844})

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path.startswith('/static/'):
                file = root / path.lstrip('/')
                if file.is_file():
                    return route.fulfill(path=str(file))
            if path == '/api/organisations':
                return route.fulfill(json=[dict(id='org', name='Synthetic books', country_code='EE', base_currency='EUR', role='owner')])
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic'})
            if path.endswith('/pay-runs'):
                return route.fulfill(json=[dict(id='run', period='2026-10', status='Approved', total_gross='2000', total_net='1800', total_employer_cost='2660', items=items)])
            if path.startswith('/api/'):
                return route.fulfill(json=[], content_type="application/json")
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#payroll')
        page.locator('.run-detail summary').click()
        for index, name in enumerate(names):
            label = i18n.catalog(language)['workspace']['Payslip: {name}'].replace('{name}', name)
            link = page.get_by_role('link', name=label, exact=True)
            playwright.expect(link).to_be_visible()
            assert link.get_attribute('href').endswith(f'#page={index + 1}')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        browser.close()


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
            playwright.expect(page.locator('.kpi').nth(3).locator('strong')).to_have_text('–')
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


def test_bureau_employee_lifecycle_draft_components_and_declarations(db, ee_org, monkeypatch):
    """Exercise new SPA writes against the real API without a live server."""
    from urllib.parse import urlsplit
    from datetime import date
    import payroll as payroll_module
    from payroll import PayrollService
    from web_app import app
    playwright = pytest.importorskip('playwright.sync_api')
    actor = 'owner@example.test'
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', 'en')
    class DemoDay(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 23)
    monkeypatch.setattr(payroll_module, 'date', DemoDay)
    payroll = PayrollService(db)
    employee = payroll.save_employee(ee_org['id'], name='Synthetic bureau employee', gross_salary='2000', personal_id='49001010001', actor=actor)
    unused = payroll.save_employee(ee_org['id'], name='Synthetic unused employee', gross_salary='1000', actor=actor)
    payroll.save_employee(ee_org['id'], employee_id=unused['id'], active=False, actor=actor)
    run = payroll.create_run(ee_org['id'], period='2026-10', actor=actor)
    root = Path(__file__).resolve().parents[1]
    errors = []
    with TestClient(app) as client, playwright.sync_playwright() as runtime:
        html = client.get('/auth/test?email=' + actor).text
        browser = runtime.chromium.launch()
        page = browser.new_page(viewport={'width': 375, 'height': 844})
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path.startswith('/api/'):
                response = client.request(route.request.method, path,
                    content=route.request.post_data,
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
        page.get_by_role('button', name='Archive', exact=True).click()
        playwright.expect(page.locator('.archived-employees').get_by_text(employee['name'], exact=True)).to_be_visible()
        assert len(payroll.runs(ee_org['id'])[0]['items']) == 1
        archived = page.locator('.archived-employees tr').filter(has_text=employee['name'])
        archived.get_by_role('button', name='Delete', exact=True).click()
        page.get_by_role('button', name='Confirm', exact=True).click()
        playwright.expect(page.locator('#toasts')).to_contain_text('Archive the employee instead.')
        page.get_by_role('dialog').get_by_role('button', name='Cancel', exact=True).click()
        archived.get_by_role('button', name='Unarchive', exact=True).click()
        playwright.expect(page.get_by_role('button', name='Archive', exact=True)).to_be_visible()
        page.locator('.archived-employees tr').filter(has_text=unused['name']).get_by_role('button', name='Delete', exact=True).click()
        page.get_by_role('button', name='Confirm', exact=True).click()
        playwright.expect(page.locator('.archived-employees')).to_have_count(0)
        assert len(payroll.employees(ee_org['id'])) == 1
        page.get_by_role('button', name='Payment types', exact=True).click()
        page.get_by_role('button', name='Add payment type', exact=True).click()
        type_editor = page.get_by_role('dialog')
        type_editor.get_by_role('textbox', name='Name', exact=True).fill('Synthetic custom income')
        type_editor.get_by_label('Income tax', exact=True).check()
        type_editor.get_by_role('button', name='Save', exact=True).click()
        playwright.expect(page.get_by_role('dialog')).to_have_count(0)
        assert any(t['name'] == 'Synthetic custom income' and t['income_tax'] for t in payroll.component_types(ee_org['id']))
        page.get_by_role('button', name='Payroll accounts', exact=True).click()
        account_editor = page.get_by_role('dialog')
        account_editor.get_by_role('combobox', name='Salary payable', exact=True).select_option('2210')
        account_editor.get_by_role('button', name='Save', exact=True).click()
        playwright.expect(page.get_by_role('dialog')).to_have_count(0)
        assert next(m for m in payroll.posting_mappings(ee_org['id']) if m['role'] == 'PAYROLL_SALARY_PAYABLE')['account_code'] == '2210'
        page.get_by_role('button', name='Edit draft pay', exact=True).click()
        editor = page.get_by_role('dialog')
        editor.get_by_role('button', name='Add payment line', exact=True).click()
        assert editor.locator('.payment-line').count() == 1, (errors, editor.inner_html(), page.locator('#toasts').inner_text())
        editor.get_by_role('combobox', name='Payment type', exact=True).select_option(label='Parental-leave pay')
        editor.get_by_label('Amount', exact=True).fill('100')
        editor.get_by_label('Income tax', exact=True).uncheck()
        editor.get_by_label('Social tax', exact=True).check()
        editor.get_by_role('button', name='Save draft pay', exact=True).click()
        playwright.expect(page.locator('.component-summary')).to_contain_text('Parental-leave pay')
        item = payroll.runs(ee_org['id'])[0]['items'][0]
        assert (item['gross'], item['income_tax'], item['social_tax']) == ('2100.00', '424.16', '693.00')
        assert not item['components'][0]['income_tax'] and item['components'][0]['social_tax']
        page.get_by_role('button', name='Approve & post', exact=True).click()
        page.get_by_role('button', name='Confirm', exact=True).click()
        playwright.expect(page.get_by_role('button', name='Edit draft pay', exact=True)).to_have_count(0)
        page.locator('.payroll-declarations').get_by_role('button', name='Prepare TSD', exact=True).click()
        playwright.expect(page.get_by_role('dialog')).to_contain_text('TSD preparation for accountant')
        page.get_by_role('dialog').get_by_role('button', name='Close', exact=True).click()
        playwright.expect(page.locator('.payroll-declarations')).to_contain_text('Prepared')
        page.get_by_role('button', name='Reclassify TSD liabilities', exact=True).click()
        page.get_by_role('button', name='Confirm', exact=True).click()
        playwright.expect(page.locator('.payroll-declarations')).to_contain_text('Settled')
        assert payroll.runs(ee_org['id'])[0]['declaration_state'] == 'settled'
        earlier = payroll.create_run(ee_org['id'], period='2026-09', actor=actor)
        payroll.approve(ee_org['id'], earlier['id'], actor=actor)
        page.evaluate("location.hash = 'overview'")
        playwright.expect(page.locator('.notice.declaration-overdue')).to_have_text('Overdue payroll declarations: 1')
        assert page.locator('.notice.declaration-overdue a').get_attribute('href') == '#payroll'
        assert not errors
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        browser.close()
