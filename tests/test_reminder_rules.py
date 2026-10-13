"""Synthetic reminder configuration, worker, access and workspace checks."""
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from automation import AutomationService
from reminder_rules import DEFAULT_STAGES, ReminderRuleService
from test_bulk_sending import ACTOR, sending  # Reuse the guarded MockTransport boundary.

RULE = dict(enabled=True, stages={'1': 3, '2': 10}, stop_stage=None)


def url(data):
    return f"/organisations/{data['oid']}/reminder-rules"


def day(invoice, offset):
    return date.fromisoformat(invoice['due_date']) + timedelta(days=offset)


@pytest.mark.parametrize('offset', [-4, -3, 0, 6, 7, 13, 14, 90])
def test_absent_row_preserves_exact_default_ladder(sending, offset):
    d = sending
    invoice = d['create']()
    service = AutomationService(d['db'])
    result = service.reminders_due(d['oid'], today=day(invoice, offset))
    expected = [(stage, (day(invoice, days)).isoformat()) for stage, days in DEFAULT_STAGES if days <= offset]
    assert [(x['stage'], x['target_date']) for x in result] == expected
    assert all(x['invoice_id'] == invoice['id'] and not x['sent'] for x in result)
    assert d['db'].scalar('SELECT COUNT(*) FROM reminder_rules') == 0
    assert d['client'].get(url(d)).json()['configured'] is False


def test_default_sends_unchanged_wording_and_deduplicates(sending):
    d = sending
    invoice = d['create']()
    worker = AutomationService(d['db'])
    results = worker.process_reminders(today=day(invoice, 14), organisation_ids=[d['oid']])
    assert [x['ladder_stage'] for x in results] == [0, 1, 2]
    assert [x['status'] for x in results] == ['Sent'] * 3
    assert worker.process_reminders(today=day(invoice, 90), organisation_ids=[d['oid']]) == []
    assert len(d['calls']) == 3
    assert all(x['Subject'] == f"Payment reminder: invoice {invoice['number']}" for x in d['calls'])
    assert all(x['TextBody'] == f"Payment reminder for invoice {invoice['number']}: {invoice['currency']} 12.34 outstanding, due {invoice['due_date']}. Please arrange payment." for x in d['calls'])


@pytest.mark.parametrize('stop,expected', [(None, [0, 1, 2]), (0, [0]), (1, [0, 1]), (2, [0, 1, 2])])
def test_configured_offsets_and_inclusive_stop(sending, stop, expected):
    d = sending
    invoice = d['create']()
    response = d['client'].put(url(d), json=RULE | {'stop_stage': stop})
    assert response.status_code == 200, response.text
    assert response.json()['configured'] is True
    worker = AutomationService(d['db'])
    early = worker.reminders_due(d['oid'], today=day(invoice, 3))
    assert [x['stage'] for x in early] == [x for x in expected if x < 2]
    due = worker.reminders_due(d['oid'], today=day(invoice, 10))
    assert [x['stage'] for x in due] == expected
    assert [x['target_date'] for x in due] == [day(invoice, {0: -3, 1: 3, 2: 10}[x]).isoformat() for x in expected]
    before = d['db'].rows('SELECT * FROM gl_entries ORDER BY id')
    assert [x['ladder_stage'] for x in worker.process_reminders(today=day(invoice, 90), organisation_ids=[d['oid']])] == expected
    assert worker.process_reminders(today=day(invoice, 90), organisation_ids=[d['oid']]) == []
    assert len(d['calls']) == len(expected)
    assert d['db'].rows('SELECT * FROM gl_entries ORDER BY id') == before


def test_disabled_rules_and_invoice_opt_out_keep_other_tenant_unchanged(sending):
    d = sending
    invoice, foreign = d['create'](), d['create'](book=d['other'])
    rules, worker = ReminderRuleService(d['db']), AutomationService(d['db'])
    rules.save(d['oid'], actor=ACTOR, **(RULE | {'enabled': False}))
    assert worker.process_reminders(today=day(invoice, 90), organisation_ids=[d['oid']]) == []
    assert not d['calls']
    assert [x['stage'] for x in worker.reminders_due(d['other']['id'], today=day(foreign, 90))] == [0, 1, 2]
    assert rules.get(d['other']['id'])['configured'] is False
    rules.save(d['oid'], actor=ACTOR, **RULE)
    worker.set_reminders_opt_out(invoice['id'], d['oid'], reminders_disabled=True, actor=ACTOR)
    assert worker.reminders_due(d['oid'], today=day(invoice, 90)) == []
    worker.set_reminders_opt_out(invoice['id'], d['oid'], reminders_disabled=False, actor=ACTOR)
    assert [x['stage'] for x in worker.reminders_due(d['oid'], today=day(invoice, 3))] == [0, 1]


@pytest.mark.parametrize('status', ['Draft', 'Paid'])
def test_existing_status_gates(sending, status):
    d = sending
    invoice = d['create'](status=status)
    ReminderRuleService(d['db']).save(d['oid'], actor=ACTOR, **RULE)
    assert AutomationService(d['db']).reminders_due(d['oid'], today=day(invoice, 90)) == []


@pytest.mark.parametrize('change', [
    {'stages': {'1': 10, '2': 3}}, {'stages': {'1': 3, '2': 3}},
    {'stages': {'1': 0, '2': 10}}, {'stages': {'1': -1, '2': 10}},
    {'stages': {'1': 3, '2': 15}}, {'stages': {'1': 3, 'unknown': 10}},
    {'stages': {'1': 3, '2': 10, '0': -3}}, {'stages': {'1': 3}},
    {'stages': {'1': '3', '2': 10}}, {'stages': {'1': True, '2': 10}},
    {'stages': {'1': 3.5, '2': 10}}, {'stages': None},
    {'stop_stage': 3}, {'stop_stage': 'unknown'}, {'stop_stage': True},
    {'enabled': 1}, {'enabled': 'true'}, {'enabled': None}, {'extra': True},
])
def test_validation_rejects_without_writes(sending, change):
    d = sending
    assert d['client'].put(url(d), json=RULE | change).status_code == 422
    assert d['db'].scalar('SELECT COUNT(*) FROM reminder_rules') == 0
    assert d['db'].scalar("SELECT COUNT(*) FROM audit_events WHERE action='reminder_rules.updated'") == 0
    assert not d['calls']


@pytest.mark.parametrize('role', ['owner', 'administrator', 'accountant', 'approver', 'viewer', 'outsider'])
def test_read_and_write_roles(sending, role):
    d = sending
    headers = {'X-Test-User': ACTOR if role == 'owner' else role + '@example.test'}
    assert d['client'].get(url(d), headers=headers).status_code == (403 if role == 'outsider' else 200)
    response = d['client'].put(url(d), headers=headers, json=RULE)
    assert response.status_code == (200 if role in {'owner', 'administrator'} else 403)


def test_auth_csrf_and_tenant_isolation(sending):
    from api_app import api, current_user, require_csrf, User
    from web_app import app
    d = sending
    with TestClient(app) as client:
        assert client.get('/api' + url(d)).status_code == 401
        assert client.put('/api' + url(d), json=RULE).status_code == 401
    foreign_url = f"/organisations/{d['other']['id']}/reminder-rules"
    headers = {'X-Test-User': 'administrator@example.test'}
    assert d['client'].get(foreign_url, headers=headers).status_code == 403
    assert d['client'].put(foreign_url, headers=headers, json=RULE).status_code == 403
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        with TestClient(app) as client:
            token = client.get('/api/csrf').json()['csrf_token']
            for headers in [{}, {'X-CSRF-Token': 'wrong'}]:
                assert client.put('/api' + url(d), json=RULE, headers=headers).status_code == 403
            assert d['db'].scalar('SELECT COUNT(*) FROM reminder_rules') == 0
            assert client.put('/api' + url(d), json=RULE, headers={'X-CSRF-Token': token}).status_code == 200
    finally:
        api.dependency_overrides.clear()
    for route in [r for r in api.routes if r.path.endswith('/reminder-rules')]:
        assert (current_user if route.methods == {'GET'} else require_csrf) in [x.call for x in route.dependant.dependencies]


def test_upsert_audit_and_idempotent_migration(sending):
    d = sending
    service = ReminderRuleService(d['db'])
    service.save(d['oid'], actor=ACTOR, **RULE)
    changed = RULE | {'enabled': False, 'stop_stage': 1}
    service.save(d['oid'], actor=ACTOR, **changed)
    assert d['db'].scalar('SELECT COUNT(*) FROM reminder_rules') == 1
    events = d['db'].rows("SELECT * FROM audit_events WHERE action='reminder_rules.updated' ORDER BY created_at,id")
    assert len(events) == 2
    assert all(x['organisation_id'] == d['oid'] and x['actor'] == ACTOR and x['object_id'] == d['oid'] for x in events)
    assert {json.loads(x['details_json'])['enabled'] for x in events} == {True, False}
    before = d['db'].rows('SELECT * FROM reminder_rules')
    assert d['db'].migrate() == []
    connection = d['db'].connect()
    try:
        sql = (Path(__file__).resolve().parents[1] / 'migrations/sqlite/0024_reminder_rules.sql').read_text()
        connection.executescript(sql)
        connection.executescript(sql)
    finally:
        connection.close()
    assert d['db'].rows('SELECT * FROM reminder_rules') == before
    assert d['db'].rows('PRAGMA foreign_key_check') == []
    with pytest.raises(KeyError):
        service.save('missing', actor=ACTOR, **RULE)
    with pytest.raises(sqlite3.IntegrityError), d['db'].transaction() as tx:
        tx.execute('UPDATE reminder_rules SET stage_1_days=stage_2_days WHERE organisation_id=?', (d['oid'],))


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_locale_appended_and_merged(language):
    from web import i18n
    raw = json.loads((i18n.LOCALES_DIR / f'{language}.json').read_text(encoding='utf-8'))
    assert list(raw)[-3:] == ['invoice_exports', 'bulk_sending', 'reminder_rules']
    assert set(raw['reminder_rules']) == {'nav', 'views', 'workspace'}
    for key, value in raw['reminder_rules']['workspace'].items():
        assert i18n.catalog(language)['workspace'][key] == value
        assert '\u2014' not in value


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
@pytest.mark.parametrize('role', ['owner', 'viewer'])
def test_settings_card_offline_browser(monkeypatch, language, role):
    playwright = pytest.importorskip('playwright.sync_api')
    from web import i18n
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    root = Path(__file__).resolve().parents[1]
    rules = ReminderRuleService._payload(None)
    calls, errors = [], []
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as exc:
            if "Executable doesn't exist" in str(exc):
                pytest.skip('Install Playwright Chromium to run browser regressions')
            raise
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            path, method = urlsplit(route.request.url).path, route.request.method
            if path == '/api/organisations':
                return route.fulfill(json=[dict(id='org', name='Synthetic company', country_code='EE', base_currency='EUR', role=role)])
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic-token'})
            if path == '/api/organisations/org/reminder-rules':
                if method == 'PUT':
                    payload = route.request.post_data_json
                    calls.append((payload, route.request.headers.get('x-csrf-token')))
                    rules.update(ReminderRuleService._payload(dict(enabled=payload['enabled'], stage_1_days=payload['stages']['1'],
                                                                  stage_2_days=payload['stages']['2'], stop_stage=payload['stop_stage'])))
                return route.fulfill(json=rules)
            if path.startswith('/api/'):
                return route.fulfill(json=[])
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#reminder-rules')
        playwright.expect(page.locator('#app-content h1')).to_have_text(words['Reminders'])
        playwright.expect(page.locator('[data-view=reminder-rules]')).to_have_text(i18n.t('nav.reminder_rules', language))
        playwright.expect(page.locator('#reminder-preview')).to_contain_text(words['3 days before due'])
        save = page.locator('#app-content button[type=submit]')
        if role == 'viewer':
            playwright.expect(save).to_be_disabled()
            playwright.expect(page.locator('[name=enabled]')).to_be_disabled()
            playwright.expect(page.locator('[name=stage_1_days]')).to_be_disabled()
            playwright.expect(page.locator('[name=stop_stage]')).to_be_disabled()
            assert not calls
        else:
            page.locator('[name=stage_1_days]').fill('3')
            page.locator('[name=stage_2_days]').fill('10')
            page.locator('[name=stop_stage]').select_option('1')
            save.click()
            playwright.expect(page.locator('#reminder-preview')).to_contain_text(words['{days} days overdue'].replace('{days}', '3'))
            assert words['{days} days overdue'].replace('{days}', '10') not in page.locator('#reminder-preview').inner_text()
            assert calls == [(RULE | {'stop_stage': 1}, 'synthetic-token')]
            page.locator('[name=enabled]').uncheck()
            save.click()
            playwright.expect(page.locator('#reminder-preview')).to_contain_text(words['Automatic reminders are disabled.'])
            assert calls[-1][0]['enabled'] is False
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.locator('#app-content').evaluate('el => el.scrollWidth <= el.clientWidth')
        assert not errors
        browser.close()
