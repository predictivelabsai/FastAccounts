"""Objects management, tagging and report controls in all four locales."""
from pathlib import Path
from datetime import date, timedelta
from urllib.parse import urlsplit, parse_qs

import pytest
from fastapi.testclient import TestClient

playwright = pytest.importorskip('playwright.sync_api')


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_objects_workspace(monkeypatch, language):
    from web import i18n
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_ALLOW_TEST_AUTH', 'true')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    root = Path(__file__).resolve().parents[1]
    records, calls, reports, pending = [], [], [], []
    hold_document = False
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
            parsed = urlsplit(route.request.url)
            path, method = parsed.path, route.request.method
            base = '/api/organisations/org'
            if path == '/api/organisations':
                return route.fulfill(json=[dict(id=oid, name='Synthetic ' + oid, country_code='EE', base_currency='EUR', role='owner') for oid in ('org', 'other')])
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic-token'})
            if path == base + '/objects' and method == 'GET':
                return route.fulfill(json=records, content_type='application/json')
            if path.startswith(base + '/objects'):
                payload = route.request.post_data_json
                calls.append((method, payload, route.request.headers.get('x-csrf-token')))
                if method == 'POST':
                    record = dict(id='project', **payload)
                    records.append(record)
                elif method == 'PATCH':
                    records[0].update(payload)
                else:
                    records.clear()
                    return route.fulfill(json={'deleted': True})
                return route.fulfill(json=records[0], status=201 if method == 'POST' else 200)
            if path == base + '/contacts':
                return route.fulfill(json=[dict(id='customer', name='Synthetic customer', contact_type='both')])
            if path == base + '/accounts':
                return route.fulfill(json=[dict(id='sales', code='3000', name='Synthetic sales', account_type='Income'),
                                           dict(id='expense', code='4000', name='Synthetic expense', account_type='Expense')])
            if path == base + '/tax-codes':
                return route.fulfill(json=[dict(id='tax', code='ZERO', rate='0', kind='standard')])
            if path in (base + '/invoices', base + '/bills') and method == 'POST':
                calls.append((method, route.request.post_data_json, route.request.headers.get('x-csrf-token')))
                if hold_document:
                    pending.append(route)
                    return
                return route.fulfill(json={'id': 'draft'}, status=201)
            if '/reports/' in path:
                reports.append((path.rsplit('/', 1)[1], parse_qs(parsed.query)))
                if path.endswith('profit-and-loss'):
                    data = dict(accounts=[], income='10.01', expenses='0.00', profit='10.01', start='2026-01-01', end='2026-01-31')
                    if parse_qs(parsed.query).get('compare', ['none'])[0] != 'none':
                        data.update(compare='previous', comparative=data.copy())
                    return route.fulfill(json=data)
                return route.fulfill(json=[], content_type='application/json')
            if path.startswith('/api/'):
                return route.fulfill(json=[], content_type='application/json')
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#objects')
        page.wait_for_function("document.querySelector('#app-content').getAttribute('aria-busy') === null")
        playwright.expect(page.locator('#app-content h1')).to_have_text(words['Objects'])
        playwright.expect(page.locator('[data-view=objects]')).to_have_text(i18n.t('nav.objects', language))
        page.locator('[data-action=newObject]').click()
        dialog = page.get_by_role('dialog')
        checkbox = dialog.locator('.check input[name=active]')
        size = checkbox.bounding_box()
        assert 12 <= size['width'] <= 20 and 12 <= size['height'] <= 20
        playwright.expect(checkbox).to_be_checked()
        dialog.locator('[name=code]').fill('SYNTHETIC')
        dialog.locator('[name=name]').fill('Synthetic <project>')
        dialog.locator('[name=notes]').fill('Synthetic note')
        dialog.get_by_role('button', name=words['Save'], exact=True).click()
        playwright.expect(dialog).to_have_count(0)
        assert calls[0][1] == dict(object_type='project', code='SYNTHETIC', name='Synthetic <project>', notes='Synthetic note', active=True)
        assert page.locator('#app-content project').count() == 0
        for view, action in [('invoices', 'newInvoice'), ('bills', 'bill')]:
            # Open the document form through its existing navigation and action.
            page.locator(f'[data-view={view}]').click()
            page.locator(f'[data-action={action}]').first.click()
            dialog = page.get_by_role('dialog')
            issue = dialog.locator('[name=issue_date]' if view == 'invoices' else '[name=bill_date]')
            due = dialog.locator('[name=due_date]')
            assert due.input_value() == (date.fromisoformat(issue.input_value()) + timedelta(days=14)).isoformat()
            issue.fill('2026-12-25')
            playwright.expect(due).to_have_value('2027-01-08')
            due.fill('2027-02-01')
            issue.fill('2026-12-26')
            playwright.expect(due).to_have_value('2027-02-01')
            playwright.expect(dialog.locator('[name=projects_project_id]')).to_have_value('')
            dialog.locator('[name=projects_project_id]').select_option('project')
            assert dialog.locator('[name=projects_person_id] option').count() == 1
            dialog.locator('[name=description]').fill('Synthetic service')
            dialog.locator('[name=unit_price]').fill('10.01')
            dialog.locator('[data-action=addLine]').click()
            playwright.expect(dialog.get_by_role('group', name=words['Line {number}'].replace('{number}', '1'), exact=True)).to_be_visible()
            playwright.expect(dialog.get_by_role('group', name=words['Line {number}'].replace('{number}', '2'), exact=True)).to_be_visible()
            playwright.expect(dialog.locator('[data-line-index="1"] [data-action=removeLine]')).to_have_attribute(
                'aria-label', words['Remove line {number}'].replace('{number}', '2'))
            dialog.locator('[name=description_1]').fill('Synthetic second line')
            dialog.locator('[name=quantity_1]').fill('2')
            dialog.locator('[name=unit_price_1]').fill('3.25')
            dialog.locator('[name=projects_project_id_1]').select_option('project')
            dialog.locator('[data-action=addLine]').click()
            dialog.locator('[data-line-index="2"] [data-action=removeLine]').click()
            playwright.expect(dialog.locator('[data-line-index]')).to_have_count(2)
            playwright.expect(dialog.locator('[data-line-index="0"] [data-action=removeLine]')).to_have_count(0)
            assert '16' in dialog.locator('[data-net-total]').inner_text()
            if view == 'bills':
                dialog.locator('[name=supplier_number]').fill('SYNTHETIC-001')
            dialog.get_by_role('button', name=words['Create draft'], exact=True).click()
            playwright.expect(dialog.locator('[name=unit_price]')).to_have_count(0)
            assert calls[-1][1]['lines'][0]['projects_project_id'] == 'project'
            assert calls[-1][1]['lines'][0]['projects_object_id'] is None
            assert [line['description'] for line in calls[-1][1]['lines']] == ['Synthetic service', 'Synthetic second line']
            assert calls[-1][1]['lines'][1]['projects_project_id'] == 'project'
            assert calls[-1][1]['lines'][1]['quantity'] == '2'
            assert calls[-1][1]['due_date'] == '2027-02-01'
            dialog.get_by_role('button', name=words['Close'], exact=True).click()
        page.locator('[data-view=invoices]').click()
        page.locator('[data-action=newInvoice]').first.click()
        playwright.expect(page.locator('.dialog')).to_have_count(1)
        page.evaluate("location.hash = 'bills'")
        playwright.expect(page.locator('.dialog')).to_have_count(0)
        page.go_back()
        playwright.expect(page.locator('[data-action=newInvoice]').first).to_be_visible()
        playwright.expect(page.locator('.dialog')).to_have_count(0)
        page.locator('[data-action=newInvoice]').first.click()
        page.locator('.dialog [name=description]').fill('Synthetic pending line')
        page.locator('.dialog [name=unit_price]').fill('1.00')
        hold_document = True
        page.locator('.dialog [type=submit]').click()
        page.wait_for_function("document.querySelector('.dialog').dataset.pending === 'true'")
        page.evaluate("location.hash = 'bills'")
        playwright.expect(page.locator('#app-content h1')).to_have_text(words['Bills'])
        playwright.expect(page.locator('.dialog')).to_have_count(1)
        assert len(pending) == 1
        pending.pop().fulfill(json={'id': 'draft'}, status=201)
        playwright.expect(page.locator('.dialog')).to_have_count(0)
        hold_document = False
        page.locator('[data-action=bill]').first.click()
        playwright.expect(page.locator('.dialog')).to_have_count(1)
        page.evaluate("document.querySelector('#org-trigger').click(); document.querySelector('[data-org=other]').click()")
        playwright.expect(page.locator('.dialog')).to_have_count(0)
        page.locator('#org-trigger').click()
        page.locator('[data-org=org]').click()
        page.locator('[data-view=accounting]').click()
        page.locator('[data-report=profit-and-loss]').click()
        form = page.locator('#report-dates')
        form.locator('[name=object_id]').select_option('project')
        form.locator('[name=compare]').select_option('previous')
        form.get_by_role('button', name=words['Apply'], exact=True).click()
        page.wait_for_function("document.querySelector('#report-result .report-heading') !== null")
        assert reports[-1][1]['object_id'] == ['project'] and reports[-1][1]['compare'] == ['previous']
        page.locator('[data-report=general-ledger]').click()
        try:
            page.wait_for_function("document.querySelector('#report-result .report-heading') !== null", timeout=1500)
        except playwright.Error:
            pytest.fail(str((reports, errors, page.locator('#toasts').inner_text(), page.locator('#report-result').inner_text())))
        assert reports[-1][0] == 'general-ledger' and reports[-1][1]['object_id'] == ['project']
        page.locator('[data-view=objects]').click()
        page.locator('[data-action=editObject]').click()
        dialog = page.get_by_role('dialog')
        dialog.locator('[name=active]').uncheck()
        dialog.get_by_role('button', name=words['Save'], exact=True).click()
        playwright.expect(dialog).to_have_count(0)
        assert calls[-1][0] == 'PATCH' and calls[-1][1]['active'] is False
        playwright.expect(page.locator('#app-content')).to_contain_text(words['Inactive'])
        page.set_viewport_size({'width': 375, 'height': 844})
        page.locator('[data-action=editObject]').click()
        dialog = page.get_by_role('dialog')
        assert dialog.evaluate('el => el.scrollWidth <= el.clientWidth')
        dialog.get_by_role('button', name=words['Cancel'], exact=True).click()
        page.locator('[data-action=deleteObject]').click()
        dialog = page.get_by_role('dialog')
        playwright.expect(dialog).to_contain_text(words['Delete this object? Objects in use must be deactivated instead.'])
        dialog.get_by_role('button', name=words['Confirm'], exact=True).click()
        playwright.expect(dialog).to_have_count(0)
        assert calls[-1][0] == 'DELETE' and not records
        assert all(call[2] == 'synthetic-token' for call in calls)
        assert not errors
        browser.close()
