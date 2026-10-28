"""Offline document appearance, tenant access, PDF and workspace regressions."""
import json
import socket
import sqlite3
import struct
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from documents import DocumentService
from organisations import OrganisationService
from web import i18n

ROOT = Path(__file__).resolve().parents[1]
ACTOR = 'owner@example.test'
SETTINGS = dict(accent_colour='#CC2233', footer_text='Thank you for your business.')


def png():
    def chunk(kind, content):
        return struct.pack('>I', len(content)) + kind + content + struct.pack('>I', zlib.crc32(kind + content))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 1, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0\0\xff\0')) + chunk(b'IEND', b'')


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original = socket.socket.connect
    def blocked(sock, address, *args, **kwargs):
        if isinstance(address, tuple) and address[0] in {'127.0.0.1', '::1'}:
            return original(sock, address, *args, **kwargs)
        raise AssertionError('Live network is forbidden')
    monkeypatch.setattr(socket.socket, 'connect', blocked)


@pytest.fixture
def env(tmp_path, monkeypatch):
    import database
    monkeypatch.delenv('DB_URL', raising=False)
    monkeypatch.setenv('FASTACCOUNTS_DB', str(tmp_path / 'appearance.sqlite'))
    monkeypatch.setenv('FASTACCOUNTS_DATA_DIR', str(tmp_path / 'evidence'))
    monkeypatch.setenv('FASTACCOUNTS_ALLOW_TEST_AUTH', 'true')
    database.reset_database_cache()
    db = database.get_database()
    db.migrate()
    organisations = OrganisationService(db)
    org = organisations.create(name='Synthetic appearance company', country_code='EE', entity_type='EE_OU', owner_email=ACTOR)
    other = organisations.create(name='Synthetic other company', country_code='EE', entity_type='EE_OU', owner_email='other@example.test')
    for role in ['administrator', 'accountant', 'approver', 'viewer']:
        organisations.add_member(org['id'], ACTOR, role + '@example.test', role)
    docs = DocumentService(db)
    def invoice(book=org, count=1, kind='invoice'):
        contact = docs.create_contact(book['id'], name='Synthetic customer', country_code='EE')
        account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (book['id'],))
        return docs.create_invoice(book['id'], contact_id=contact['id'], issue_date='2026-01-10', document_type=kind,
            lines=[dict(description='Synthetic service', account_id=account, unit_price='12.34') for _ in range(count)], actor=ACTOR)
    from api_app import api
    with TestClient(api, headers={'X-Test-User': ACTOR}) as client:
        yield dict(db=db, client=client, docs=docs, org=org, other=other, invoice=invoice,
                   url=f"/organisations/{org['id']}/document-settings")
    database.reset_database_cache()


def upload(d, content=None, filename='logo.png', content_type='image/png', **kwargs):
    return d['client'].post(d['url'] + '/logo', files={'file': (filename, png() if content is None else content, content_type)}, **kwargs)


@pytest.mark.parametrize('change', [{'accent_colour': '#xyz123'}, {'accent_colour': 'CC2233'}, {'accent_colour': '#1234567'},
    {'footer_text': 'a' * 501}, {'extra': True}])
def test_validation_without_writes(env, change):
    d = env
    assert d['client'].put(d['url'], json=SETTINGS | change).status_code == 422
    assert d['db'].scalar('SELECT COUNT(*) FROM document_settings') == 0
    assert d['db'].scalar("SELECT COUNT(*) FROM audit_events WHERE action='document_settings.updated'") == 0


@pytest.mark.parametrize('role', ['owner', 'administrator', 'accountant', 'approver', 'viewer', 'outsider'])
def test_read_write_roles(env, role):
    d = env
    headers = {'X-Test-User': ACTOR if role == 'owner' else role + '@example.test'}
    assert d['client'].get(d['url'], headers=headers).status_code == (403 if role == 'outsider' else 200)
    expected = 200 if role in {'owner', 'administrator'} else 403
    assert d['client'].put(d['url'], json=SETTINGS, headers=headers).status_code == expected
    assert upload(d, headers=headers).status_code == expected
    assert d['client'].delete(d['url'] + '/logo', headers=headers).status_code == expected


def test_defaults_upsert_audit_and_isolation(env):
    from document_settings import DocumentSettingsService
    d = env
    initial = d['client'].get(d['url']).json()
    assert all(initial[key] is None for key in ['accent_colour', 'footer_text', 'logo_attachment_id'])
    assert d['client'].get(d['url'] + '/logo').status_code == 404
    for settings in [SETTINGS, dict(accent_colour=None, footer_text=None)]:
        response = d['client'].put(d['url'], json=settings)
        assert response.status_code == 200, response.text
        assert all(response.json()[key] == value for key, value in settings.items())
    assert d['db'].scalar('SELECT COUNT(*) FROM document_settings') == 1
    events = d['db'].rows("SELECT * FROM audit_events WHERE action='document_settings.updated'")
    assert len(events) == 2
    assert all(row['organisation_id'] == d['org']['id'] and row['actor'] == ACTOR and row['object_id'] == d['org']['id'] for row in events)
    assert all(DocumentSettingsService(d['db']).get(d['other']['id'])[key] is None for key in SETTINGS)
    foreign = f"/organisations/{d['other']['id']}/document-settings"
    assert d['client'].get(foreign).status_code == 403
    assert d['client'].put(foreign, json=SETTINGS).status_code == 403
    assert d['client'].post(foreign + '/logo', files={'file': ('logo.png', png(), 'image/png')}).status_code == 403
    assert d['client'].delete(foreign + '/logo').status_code == 403
    assert d['client'].get(foreign + '/logo').status_code == 403


def test_logo_round_trip_delete_and_integrity(env):
    d = env
    assert upload(d).status_code == 200
    settings = d['client'].get(d['url']).json()
    attachment = d['db'].one('SELECT * FROM attachments WHERE id=?', (settings['logo_attachment_id'],))
    assert attachment['organisation_id'] == d['org']['id'] and attachment['owner_type'] == 'organisation'
    path = Path(attachment['storage_path'])
    response = d['client'].get(d['url'] + '/logo')
    assert response.status_code == 200 and response.content == png()
    assert response.headers['content-type'].startswith('image/png')
    assert d['client'].put(d['url'], json=SETTINGS).json()['logo_attachment_id'] == attachment['id']
    invoice = d['invoice']()
    assert b'/Subtype /Image' in d['docs'].invoice_pdf(invoice['id'])
    path.write_bytes(b'corrupt')
    assert d['client'].get(d['url'] + '/logo').status_code == 422
    assert b'/Subtype /Image' not in d['docs'].invoice_pdf(invoice['id'])
    assert d['client'].delete(d['url'] + '/logo').status_code == 200
    assert d['client'].get(d['url']).json()['logo_attachment_id'] is None
    assert d['client'].get(d['url'] + '/logo').status_code == 404
    assert not path.exists() and not d['db'].one('SELECT id FROM attachments WHERE id=?', (attachment['id'],))
    assert d['client'].get(d['url']).json()['footer_text'] == SETTINGS['footer_text']


@pytest.mark.parametrize('content,filename,content_type', [(b'wrong', 'logo.png', 'image/png'),
    (b'\xff\xd8\xffbad', 'logo.png', 'image/png'), (png(), 'logo.jpg', 'image/jpeg'),
    (png(), 'logo.jpg', 'image/png'), (png(), 'logo.svg', 'image/svg+xml'),
    (b'\x89PNG\r\n' + b'a' * (512 * 1024), 'logo.png', 'image/png')], ids=['wrong', 'wrong-png-magic', 'wrong-jpeg-magic', 'extension', 'svg', 'oversize'])
def test_rejected_logos_leave_no_storage(env, content, filename, content_type):
    d = env
    assert upload(d, content, filename, content_type).status_code == 422
    assert d['db'].scalar('SELECT COUNT(*) FROM attachments') == 0
    assert d['db'].scalar('SELECT COUNT(*) FROM document_settings') == 0


@pytest.mark.parametrize('kind', ['invoice', 'credit_note'])
def test_pdf_default_deterministic_and_accent_footer(env, kind):
    d = env
    invoice = d['invoice'](kind=kind)
    default = d['docs'].invoice_pdf(invoice['id'])
    assert default.startswith(b'%PDF') and b'/Subtype /Image' not in default
    assert d['docs'].invoice_pdf(invoice['id']) == default
    assert d['client'].put(d['url'], json=dict(accent_colour=None, footer_text=None)).status_code == 200
    assert d['docs'].invoice_pdf(invoice['id']) == default
    for values in [dict(accent_colour='#FF0000', footer_text=None), dict(accent_colour=None, footer_text=SETTINGS['footer_text']), SETTINGS]:
        assert d['client'].put(d['url'], json=values).status_code == 200
        assert d['docs'].invoice_pdf(invoice['id']) != default
    foreign = d['invoice'](book=d['other'])
    assert d['docs'].invoice_pdf(foreign['id']) == d['docs'].invoice_pdf(foreign['id'])


def test_footer_drawn_on_every_overflow_page(env, monkeypatch):
    from reportlab.pdfgen.canvas import Canvas
    d = env
    invoice = d['invoice'](count=80)
    d['client'].put(d['url'], json=SETTINGS)
    calls = []
    original = Canvas.drawString
    def draw(canvas, x, y, text, *args, **kwargs):
        if text == SETTINGS['footer_text']:
            calls.append((canvas.getPageNumber(), x, y, canvas._fontname, canvas._fontsize))
        return original(canvas, x, y, text, *args, **kwargs)
    monkeypatch.setattr(Canvas, 'drawString', draw)
    assert d['docs'].invoice_pdf(invoice['id']).startswith(b'%PDF')
    assert len(calls) >= 3
    assert [row[0] for row in calls] == list(range(1, len(calls) + 1))
    assert all(row[2:] == (40, 'Helvetica', 7.5) for row in calls)


def test_evidence_organisation_owner_and_rejections(env):
    d = env
    with d['db'].transaction() as tx:
        d['docs']._evidence_owner(tx, d['org']['id'], 'organisation', d['org']['id'])
        with pytest.raises(KeyError):
            d['docs']._evidence_owner(tx, d['org']['id'], 'organisation', d['other']['id'])
        with pytest.raises(ValueError, match='invoice, bill, journal or organisation'):
            d['docs']._evidence_owner(tx, d['org']['id'], 'user', ACTOR)


def test_concurrent_put_keeps_one_complete_state(env):
    d = env
    writes = [SETTINGS, dict(accent_colour='#123456', footer_text='Second complete state')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda values: d['client'].put(d['url'], json=values), writes))
    assert all(result.status_code == 200 for result in results)
    final = d['client'].get(d['url']).json()
    assert {key: final[key] for key in SETTINGS} in writes
    assert d['db'].scalar('SELECT COUNT(*) FROM document_settings') == 1
    assert d['db'].scalar("SELECT COUNT(*) FROM audit_events WHERE action='document_settings.updated'") == 2


def test_csrf_auth_routes(env):
    from api_app import api, current_user, require_csrf, User
    from web_app import app
    d = env
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        with TestClient(app) as client:
            token = client.get('/api/csrf').json()['csrf_token']
            for headers in [{}, {'X-CSRF-Token': 'wrong'}]:
                assert client.put('/api' + d['url'], json=SETTINGS, headers=headers).status_code == 403
                assert client.post('/api' + d['url'] + '/logo', files={'file': ('logo.png', png(), 'image/png')}, headers=headers).status_code == 403
                assert client.delete('/api' + d['url'] + '/logo', headers=headers).status_code == 403
            assert client.put('/api' + d['url'], json=SETTINGS, headers={'X-CSRF-Token': token}).status_code == 200
    finally:
        api.dependency_overrides.clear()
    with TestClient(app) as client:
        assert client.get('/api' + d['url']).status_code == 401
    for route in [r for r in api.routes if '/document-settings' in r.path]:
        assert (current_user if route.methods == {'GET'} else require_csrf) in [x.call for x in route.dependant.dependencies]


def test_migration_rerun_preserves_data_and_checks(env):
    d = env
    d['client'].put(d['url'], json=SETTINGS)
    upload(d)
    original = d['db'].rows('SELECT * FROM document_settings')
    attachments = d['db'].rows('SELECT * FROM attachments')
    assert d['db'].scalar('SELECT COUNT(*) FROM schema_migrations') == 37
    for _ in range(2):
        with d['db'].transaction() as tx:
            tx.execute("DELETE FROM schema_migrations WHERE version='0028_document_settings'")
        assert d['db'].migrate() == ['0028_document_settings']
    assert d['db'].rows('SELECT * FROM document_settings') == original
    assert d['db'].rows('SELECT * FROM attachments') == attachments
    assert d['db'].rows('PRAGMA foreign_key_check') == []
    assert "'0027_mfa', '0028_document_settings', '0029_copilot', '0030_master_data_maintenance', '0031_master_data_groups', '0032_copilot_access', '0033_copilot_settings', '0034_payroll_demo_fixes', '0035_payroll_income_line', '0036_payroll_component_catalogue', '0037_employee_tax_settings', '0038_payroll_payday_rules', '0039_payroll_payouts', '0040_payroll_settlement_dates']" in (ROOT / '.github/workflows/ci.yml').read_text()
    for column, value in [('accent_colour', '#GG0000'), ('accent_colour', '#1234567'), ('footer_text', 'a' * 501)]:
        with pytest.raises(sqlite3.IntegrityError), d['db'].transaction() as tx:
            tx.execute(f'UPDATE document_settings SET {column}=? WHERE organisation_id=?', (value, d['org']['id']))


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_locale_tail_keys_merge_and_nav(language):
    raw = json.loads((i18n.LOCALES_DIR / f'{language}.json').read_text(encoding='utf-8'))
    english = json.loads((i18n.LOCALES_DIR / 'en.json').read_text(encoding='utf-8'))
    assert list(raw)[-(7):] == ['invoice_exports', 'bulk_sending', 'reminder_rules', 'fx_rates', 'document_settings', 'copilot', 'periods']
    assert set(raw['document_settings']) == set(english['document_settings']) == {'nav', 'views', 'workspace'}
    for section in ['nav', 'views', 'workspace']:
        assert set(raw['document_settings'][section]) == set(english['document_settings'][section])
        for key, value in raw['document_settings'][section].items():
            assert i18n.catalog(language)[section][key] == value
            assert '\u2014' not in value and '\u2019' not in value
    from web.public import workspace_page
    from fasthtml.common import to_xml
    html = to_xml(workspace_page({'email': ACTOR}, language))
    assert 'data-view="documents"' in html and i18n.t('nav.document_settings', language) in html


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
@pytest.mark.parametrize('role', ['owner', 'viewer'])
def test_settings_offline_browser(monkeypatch, language, role):
    playwright = pytest.importorskip('playwright.sync_api')
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    settings = dict(accent_colour=None, footer_text=None, logo_attachment_id='initial-logo', configured=True)
    calls, errors = [], []
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip('Install Playwright Chromium to run browser regressions')
            raise
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        def route(request_route):
            request = request_route.request
            path, method = urlsplit(request.url).path, request.method
            if path == '/api/organisations':
                return request_route.fulfill(json=[dict(id='org', name='Synthetic company', country_code='EE', base_currency='EUR', role=role)])
            if path == '/api/csrf':
                return request_route.fulfill(json={'csrf_token': 'synthetic-token'})
            if path == '/api/organisations/org/document-settings':
                if method == 'PUT':
                    calls.append((method, request.post_data_json, request.headers.get('x-csrf-token')))
                    settings.update(request.post_data_json)
                return request_route.fulfill(json=settings)
            if path == '/api/organisations/org/document-settings/logo':
                if method == 'GET':
                    return request_route.fulfill(body=png(), content_type='image/png')
                calls.append((method, request.post_data_buffer, request.headers.get('x-csrf-token')))
                settings['logo_attachment_id'] = 'uploaded-logo' if method == 'POST' else None
                return request_route.fulfill(json=settings)
            if path.startswith('/api/'):
                return request_route.fulfill(json=[])
            if path == '/app':
                return request_route.fulfill(body=html, content_type='text/html')
            if path in ['/static/app.js', '/static/app.css']:
                return request_route.fulfill(path=str(ROOT / path.lstrip('/')))
            return request_route.fulfill(status=404)
        page.route('**/*', route)
        page.goto('http://workspace.test/app#documents')
        playwright.expect(page.locator('#app-content h1')).to_have_text(words['Document appearance'])
        playwright.expect(page.locator('[data-view=documents]')).to_have_text(i18n.t('nav.document_settings', language))
        appearance, logo = page.locator('[data-document-appearance]'), page.locator('[data-document-logo]')
        playwright.expect(logo.locator('img')).to_be_visible()
        if role == 'viewer':
            for selector in ['input', 'textarea', 'button']:
                for element in page.locator('#app-content ' + selector).all():
                    playwright.expect(element).to_be_disabled()
            assert not calls
        else:
            appearance.locator('[name=use_accent_colour]').check()
            appearance.locator('[name=accent_colour]').fill('#cc2233')
            appearance.locator('[name=footer_text]').fill(SETTINGS['footer_text'])
            with page.expect_response(lambda response: response.request.method == 'GET' and urlsplit(response.url).path.endswith('/document-settings')):
                appearance.locator('button[type=submit]').click()
            playwright.expect(appearance.locator('[name=footer_text]')).to_have_value(SETTINGS['footer_text'])
            assert calls[0] == ('PUT', SETTINGS | {'accent_colour': '#cc2233'}, 'synthetic-token')
            logo.locator('[name=file]').set_input_files(dict(name='logo.png', mimeType='image/png', buffer=png()))
            logo.locator('button[type=submit]').click()
            playwright.expect(logo.locator('img')).to_have_attribute('src', '/api/organisations/org/document-settings/logo?v=uploaded-logo')
            assert calls[-1][0] == 'POST' and calls[-1][2] == 'synthetic-token' and png() in calls[-1][1]
            logo.locator('[data-action=removeDocumentLogo]').click()
            page.locator('[data-action=confirm]').click()
            playwright.expect(logo.locator('img')).to_have_count(0)
            assert calls[-1][0] == 'DELETE' and calls[-1][2] == 'synthetic-token'
            appearance.locator('[name=use_accent_colour]').uncheck()
            appearance.locator('button[type=submit]').click()
            playwright.expect(appearance.locator('[name=accent_colour]')).to_be_disabled()
            assert calls[-1][1]['accent_colour'] is None
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.locator('#app-content').evaluate('el => el.scrollWidth <= el.clientWidth')
        assert not errors
        browser.close()


def test_jpeg_replacement_and_failed_upload_preserve_original(env, monkeypatch):
    from io import BytesIO
    pytest.importorskip('PIL')
    from PIL import Image
    from document_settings import DocumentSettingsService
    d = env
    upload(d)
    old = d['db'].one('SELECT * FROM attachments')
    output = BytesIO()
    Image.new('RGB', (2, 1), (40, 90, 140)).save(output, format='JPEG')
    jpeg = output.getvalue()
    assert upload(d, jpeg, 'logo.jpeg', 'image/jpeg').status_code == 200
    current = d['db'].one('SELECT * FROM attachments')
    assert current['id'] != old['id'] and not Path(old['storage_path']).exists()
    assert d['client'].get(d['url'] + '/logo').content == jpeg
    assert b'/Subtype /Image' in d['docs'].invoice_pdf(d['invoice']()['id'])
    settings_before = d['db'].rows('SELECT * FROM document_settings')
    audit_before = d['db'].rows('SELECT * FROM audit_events')
    def failed(*args, **kwargs):
        raise RuntimeError('Synthetic transaction failure')
    monkeypatch.setattr('document_settings.audit', failed)
    with pytest.raises(RuntimeError, match='Synthetic transaction failure'):
        DocumentSettingsService(d['db']).upload_logo(d['org']['id'], actor=ACTOR, filename='logo.png', content_type='image/png', content=png())
    assert d['db'].rows('SELECT * FROM document_settings') == settings_before
    assert d['db'].rows('SELECT * FROM attachments') == [current]
    assert d['db'].rows('SELECT * FROM audit_events') == audit_before
    assert Path(current['storage_path']).read_bytes() == jpeg
    assert list(Path(current['storage_path']).parent.iterdir()) == [Path(current['storage_path'])]


@pytest.mark.parametrize('broken', ['missing', 'unreadable', 'size'])
def test_broken_logo_does_not_fail_pdf(env, broken):
    from core_utils import sha256_bytes
    d = env
    upload(d)
    attachment = d['db'].one('SELECT * FROM attachments')
    path = Path(attachment['storage_path'])
    if broken == 'missing':
        path.unlink()
    elif broken == 'unreadable':
        content = b'\x89PNG\r\n\x1a\ninvalid image'
        path.write_bytes(content)
        with d['db'].transaction() as tx:
            tx.execute('UPDATE attachments SET sha256=?,size_bytes=? WHERE id=?', (sha256_bytes(content), len(content), attachment['id']))
    else:
        with d['db'].transaction() as tx:
            tx.execute('UPDATE attachments SET size_bytes=size_bytes+1 WHERE id=?', (attachment['id'],))
    result = d['docs'].invoice_pdf(d['invoice']()['id'])
    assert result.startswith(b'%PDF') and b'/Subtype /Image' not in result
