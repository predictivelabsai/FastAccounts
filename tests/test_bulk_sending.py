"""Synthetic, offline bulk invoice delivery and workspace acceptance checks."""
from __future__ import annotations

import base64
import json
import socket
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

import automation
from bulk_sending import BulkSendingService, MAX_BULK_INVOICES
from database import reset_database_cache
from documents import DocumentService
from organisations import OrganisationService

ACTOR = 'owner@example.test'


@pytest.fixture
def sending(db, uk_org, ee_org, monkeypatch, tmp_path):
    docs = DocumentService(db)
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    monkeypatch.setenv('FASTACCOUNTS_DATA_DIR', str(tmp_path / 'evidence'))
    monkeypatch.setenv('POSTMARK_API_TOKEN', 'synthetic-token')
    monkeypatch.setenv('FROM_EMAIL', 'sender@example.invalid')
    monkeypatch.setenv('FASTACCOUNTS_ALLOW_TEST_AUTH', 'true')
    reset_database_cache()
    calls, clients = [], []
    failures = set()

    def respond(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if payload['To'] in failures:
            return httpx.Response(200, json={'ErrorCode': 300, 'Message': 'Email provider rejected the message'})
        return httpx.Response(200, json={'MessageID': f'synthetic-{len(calls)}'})

    def factory():
        client = httpx.Client(transport=httpx.MockTransport(respond))
        clients.append(client)
        return client

    monkeypatch.setattr(automation, 'HTTP_CLIENT_FACTORY', factory)

    def create(*, book=uk_org, status='Issued', email='customer@example.invalid', kind='invoice'):
        contact = docs.create_contact(book['id'], name='Synthetic customer <safe>',
                                      country_code=book['country_code'], email=email)
        account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (book['id'],))
        invoice = docs.create_invoice(book['id'], contact_id=contact['id'], issue_date='2026-01-10',
                                      document_type=kind, actor=ACTOR,
                                      lines=[dict(account_id=account, unit_price='12.34')])
        if status != 'Draft':
            invoice = docs.issue_invoice(invoice['id'], actor=ACTOR)
        if status in {'Part Paid', 'Paid'}:
            bank = docs.create_bank_account(book['id'], name='Synthetic bank ' + invoice['id'], currency=book['base_currency'])
            docs.record_payment(book['id'], payment_type='customer_receipt', contact_id=contact['id'],
                                bank_account_id=bank['id'], payment_date='2026-01-10',
                                amount='1.00' if status == 'Part Paid' else '12.34', actor=ACTOR,
                                allocations=[dict(document_id=invoice['id'], amount='1.00' if status == 'Part Paid' else '12.34')])
            invoice = docs.invoice(invoice['id'])
        return invoice

    for role in ['administrator', 'accountant', 'approver', 'viewer']:
        OrganisationService(db).add_member(uk_org['id'], ACTOR, role + '@example.test', role)
    from api_app import api
    with TestClient(api, headers={'X-Test-User': ACTOR}) as client:
        # TestClient's Windows event-loop socket pair is created before this guard.
        def blocked(*args, **kwargs):
            raise AssertionError('Live network is forbidden')
        socket_connect = socket.socket.connect
        def guarded_connect(sock, address):
            if isinstance(address, tuple) and address[0] == '127.0.0.1':
                return socket_connect(sock, address)
            return blocked(sock, address)
        monkeypatch.setattr(socket.socket, 'connect', guarded_connect)
        yield dict(db=db, docs=docs, create=create, client=client, calls=calls, clients=clients,
                   failures=failures, oid=uk_org['id'], other=ee_org,
                   url=f"/organisations/{uk_org['id']}/invoices/send-bulk")
    reset_database_cache()


def send(data, ids, **kwargs):
    response = data['client'].post(data['url'], json={'invoice_ids': ids}, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()['results']


@pytest.mark.parametrize('country', ['UK', 'EE'])
def test_multiple_sends_reuse_body_pdf_and_existing_audit(sending, country):
    d = sending
    book = d['other'] if country == 'EE' else None
    invoices = [d['create'](**({'book': book} if book else {})) for _ in range(2)]
    if book:
        d['oid'] = book['id']
        d['url'] = f"/organisations/{book['id']}/invoices/send-bulk"
    before = d['db'].rows('SELECT * FROM gl_entries ORDER BY id')
    results = send(d, [x['id'] for x in invoices])
    assert [r['status'] for r in results] == ['sent', 'sent']
    assert len(d['calls']) == 2 and all(c.is_closed for c in d['clients'])
    for invoice, result, payload in zip(invoices, results, d['calls']):
        assert payload['Subject'] == f"Invoice {invoice['number']} from {d['db'].scalar('SELECT name FROM organisations WHERE id=?', (d['oid'],))}"
        assert payload['TextBody'] == f"Please find invoice {invoice['number']} for {invoice['currency']} 12.34 attached."
        delivery = d['db'].one('SELECT * FROM invoice_deliveries WHERE id=?', (result['delivery_id'],))
        assert delivery['status'] == 'Sent' and delivery['created_by'] == ACTOR
        events = d['db'].rows("SELECT details_json FROM audit_events WHERE object_id=? AND action='invoice.delivery'", (delivery['id'],))
        assert {json.loads(e['details_json'])['status'] for e in events} == {'Prepared', 'Sent'}
        assert all(json.loads(e['details_json'])['attachment_id'] == result['attachment_id'] for e in events)
        attachment, pdf = d['docs'].evidence_download(d['oid'], result['attachment_id'])
        assert attachment['owner_id'] == invoice['id'] and attachment['content_type'] == 'application/pdf'
        assert pdf.startswith(b'%PDF') and pdf == base64.b64decode(payload['Attachments'][0]['Content'])
        detail = d['client'].get(f"/organisations/{d['oid']}/invoices/{invoice['id']}").json()
        assert detail['deliveries'][0]['attachment_id'] == result['attachment_id']
        assert 'request_key' not in detail['deliveries'][0]
    assert d['db'].rows('SELECT * FROM gl_entries ORDER BY id') == before


def test_independent_failures_and_tenant_isolation(sending):
    d = sending
    foreign = d['create'](book=d['other'])
    credit = d['create'](kind='credit_note')
    draft = d['create'](status='Draft')
    paid = d['create'](status='Paid')
    no_email = d['create'](email='  ')
    rejected = d['create'](email='reject@example.invalid')
    d['failures'].add('reject@example.invalid')
    good = d['create'](status='Part Paid')
    results = send(d, ['missing', foreign['id'], credit['id'], draft['id'], paid['id'], no_email['id'], rejected['id'], good['id']])
    assert [r['reason'] for r in results] == [
        'Invoice not found', 'Invoice not found', 'Only sales invoices can be sent in bulk',
        'Only Issued or Part Paid invoices can be sent in bulk',
        'Only Issued or Part Paid invoices can be sent in bulk', 'Contact has no email address',
        'Email provider rejected the message', None]
    assert [r['status'] for r in results] == ['failed'] * 7 + ['sent']
    assert len(d['calls']) == 2
    assert d['db'].scalar('SELECT COUNT(*) FROM invoice_deliveries') == 2
    assert results[-2]['delivery_id'] and results[-2]['attachment_id']
    assert d['db'].scalar('SELECT COUNT(*) FROM invoice_deliveries WHERE organisation_id=?', (d['other']['id'],)) == 0
    with pytest.raises(KeyError):
        d['docs'].evidence_download(d['other']['id'], results[-1]['attachment_id'])


def test_duplicate_ids_and_retry_key(sending):
    d = sending
    invoice = d['create']()
    headers = {'Idempotency-Key': 'synthetic-request'}
    first = send(d, [invoice['id'], invoice['id']], headers=headers)
    assert first[0]['status'] == 'sent'
    assert first[1]['reason'] == 'Duplicate invoice ID in this request'
    assert send(d, [invoice['id']], headers=headers)[0] == first[0]
    assert len(d['calls']) == 1 and d['db'].scalar('SELECT COUNT(*) FROM invoice_deliveries') == 1
    assert send(d, [invoice['id']], headers={'Idempotency-Key': 'intentional-resend'})[0]['status'] == 'sent'
    assert len(d['calls']) == 2


def test_failed_retry_key_does_not_resend(sending):
    d = sending
    invoice = d['create'](email='reject@example.invalid')
    d['failures'].add('reject@example.invalid')
    headers = {'Idempotency-Key': 'failed-request'}
    first = send(d, [invoice['id']], headers=headers)
    d['failures'].clear()
    assert send(d, [invoice['id']], headers=headers) == first
    assert len(d['calls']) == 1


def test_prepared_retry_is_not_blindly_resent(sending, monkeypatch):
    d = sending
    invoice = d['create']()
    from delivery_repository import DeliveryRepository
    original = DeliveryRepository.finish
    monkeypatch.setattr(DeliveryRepository, 'finish', lambda *args: (_ for _ in ()).throw(RuntimeError('Synthetic persistence failure')))
    headers = {'Idempotency-Key': 'interrupted-request'}
    first = send(d, [invoice['id']], headers=headers)
    assert first[0]['status'] == 'failed'
    monkeypatch.setattr(DeliveryRepository, 'finish', original)
    retry = send(d, [invoice['id']], headers=headers)[0]
    assert retry['reason'] == 'Delivery outcome is unknown. Review delivery history before retrying.'
    assert retry['delivery_id'] and retry['attachment_id'] and len(d['calls']) == 1


@pytest.mark.parametrize('payload', [{'invoice_ids': []}, {'invoice_ids': ['x'] * 51},
                                    {'invoice_ids': ['x'], 'extra': True}, {'invoice_ids': [123]}])
def test_request_validation_before_sending(sending, payload):
    d = sending
    assert d['client'].post(d['url'], json=payload).status_code == 422
    assert not d['calls'] and d['db'].scalar('SELECT COUNT(*) FROM invoice_deliveries') == 0


def test_cap_boundary_and_service_guard(sending):
    d = sending
    assert len(send(d, ['missing'] * MAX_BULK_INVOICES)) == MAX_BULK_INVOICES
    with pytest.raises(ValueError):
        BulkSendingService(d['db']).send(d['oid'], ['x'] * (MAX_BULK_INVOICES + 1), actor=ACTOR)
    assert not d['calls']


@pytest.mark.parametrize('role,allowed', [('owner', True), ('administrator', True), ('accountant', True),
                                        ('viewer', False), ('approver', False), ('outsider', False)])
def test_role_gates(sending, role, allowed):
    d = sending
    invoice = d['create']()
    email = ACTOR if role == 'owner' else role + '@example.test'
    response = d['client'].post(d['url'], json={'invoice_ids': [invoice['id']]}, headers={'X-Test-User': email})
    assert response.status_code == (200 if allowed else 403)
    assert len(d['calls']) == int(allowed)


def test_csrf_required(sending):
    from api_app import api, current_user, User
    from web_app import app
    d = sending
    invoice = d['create']()
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        with TestClient(app) as client:
            token = client.get('/api/csrf').json()['csrf_token']
            for headers in [{}, {'X-CSRF-Token': 'wrong'}]:
                assert client.post('/api' + d['url'], json={'invoice_ids': [invoice['id']]}, headers=headers).status_code == 403
            assert not d['calls']
            assert client.post('/api' + d['url'], json={'invoice_ids': [invoice['id']]}, headers={'X-CSRF-Token': token}).status_code == 200
    finally:
        api.dependency_overrides.clear()


def test_disconnected_mailer_is_per_invoice_failure(sending, monkeypatch):
    d = sending
    monkeypatch.delenv('POSTMARK_API_TOKEN')
    results = send(d, [d['create']()['id'], d['create']()['id']])
    assert [r['reason'] for r in results] == ['Email delivery is not connected'] * 2
    assert not d['calls']


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_locale_section_appended_and_merged(language):
    from web import i18n
    raw = json.loads((i18n.LOCALES_DIR / f'{language}.json').read_text(encoding='utf-8'))
    assert list(raw)[-2:] == ['bulk_sending', 'reminder_rules']
    assert set(raw['bulk_sending']) == {'nav', 'views', 'workspace'}
    for key, value in raw['bulk_sending']['workspace'].items():
        assert i18n.catalog(language)['workspace'][key] == value
        assert '\u2014' not in value


@pytest.mark.parametrize('language', ['en', 'et', 'lt', 'lv'])
def test_workspace_confirmation_results_and_history(monkeypatch, language):
    playwright = pytest.importorskip('playwright.sync_api')
    from web import i18n
    from web_app import app
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', language)
    html = TestClient(app).get('/auth/test').text
    words = i18n.catalog(language)['workspace']
    calls, errors = [], []
    invoices = [dict(id=str(i), number=f'INV-{i}', contact_name='Synthetic <customer>',
                     issue_date='2026-01-10', currency='EUR', total='12.34', paid_total='0',
                     document_type='invoice', status=status) for i, status in enumerate(['Issued', 'Part Paid', 'Draft', 'Paid'])]
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        page = browser.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(Path(__file__).resolve().parents[1] / path.lstrip('/')))
            if path == '/api/organisations':
                return route.fulfill(json=[dict(id='org', name='Synthetic', country_code='EE', base_currency='EUR', role='accountant')])
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic'})
            if path.endswith('/invoices/send-bulk'):
                calls.append((route.request.post_data_json, route.request.headers))
                return route.fulfill(json={'results': [dict(invoice_id='0', status='sent'),
                    dict(invoice_id='1', status='failed', reason='Contact has no email address')]})
            if path.endswith('/invoices/0'):
                return route.fulfill(json=invoices[0] | {'deliveries': [dict(created_at='2026-10-12', recipient='customer@example.invalid', status='Sent', attachment_id='pdf-id')]})
            if path.endswith('/invoices'):
                return route.fulfill(json=invoices)
            if path.startswith('/api/'):
                return route.fulfill(json=[], content_type='application/json')
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#invoices')
        send_button = page.locator('[data-action=sendBulk]')
        playwright.expect(send_button).to_be_disabled()
        playwright.expect(page.locator('[data-select-invoice="2"]')).to_be_disabled()
        playwright.expect(page.locator('[data-select-invoice="3"]')).to_be_disabled()
        for i in ['0', '1']:
            page.locator(f'[data-select-invoice="{i}"]').check()
        send_button.click()
        assert not calls
        page.locator('.dialog [data-action=cancel]').click()
        assert not calls
        send_button.click()
        page.locator('.dialog [data-action=confirm]').click()
        result = page.get_by_role('dialog', name=words['Email results'])
        playwright.expect(result).to_be_visible()
        playwright.expect(result).to_contain_text(words['Sent'])
        playwright.expect(result).to_contain_text(words['Contact has no email address'])
        assert calls[0][0] == {'invoice_ids': ['0', '1']}
        assert calls[0][1]['x-csrf-token'] == 'synthetic' and calls[0][1]['idempotency-key']
        assert page.locator('#app-content customer').count() == 0
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        result.locator('[data-close]').click()
        playwright.expect(send_button).to_be_disabled()
        page.locator('[data-action=invoiceAttachments][data-id="0"]').click()
        playwright.expect(page.get_by_role('heading', name=words['Email history'])).to_be_visible()
        playwright.expect(page.locator('.dialog a[href$="/attachments/pdf-id/download"]')).to_be_visible()
        assert not errors
        browser.close()
