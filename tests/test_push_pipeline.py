"""Offline reviewed journal export contracts and tenant boundaries."""
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from connectors.base import ConnectorResult
from connectors.providers import ProviderError
from core_utils import money
from integration_service import AccountMappingService, IntegrationService
from ledger import LedgerService
from organisations import OrganisationService
from payroll import PayrollService
from push_service import PushService

ACTOR = 'owner@example.test'


@pytest.fixture
def source(db, ee_org, monkeypatch):
    payroll = PayrollService(db)
    payroll.save_employee(ee_org['id'], actor=ACTOR, name='Synthetic worker', gross_salary='2000.13')
    run = payroll.create_run(ee_org['id'], period='2026-07', actor=ACTOR)
    run = payroll.approve(ee_org['id'], run['id'], actor=ACTOR)
    mappings = AccountMappingService(db)
    for account in db.rows('SELECT code,name FROM accounts WHERE organisation_id=?', (ee_org['id'],)):
        for provider in ('smartaccounts', 'merit'):
            mappings.create(ee_org['id'], provider, local_account_code=account['code'],
                            external_account_code='X' + account['code'], status='Confirmed', actor=ACTOR)
    IntegrationService(db).configure(ee_org['id'], 'smartaccounts', credentials={}, config={}, actor=ACTOR)
    IntegrationService(db).configure(ee_org['id'], 'merit', credentials={}, config={}, actor=ACTOR)

    class FakeConnector:
        retries = 2
        calls = []
        error = None

        def push(self, object_type, records):
            self.calls.append((object_type, records))
            assert self.retries == 0
            assert object_type == 'gl_batch'
            assert all(isinstance(line['debit'], Decimal) and isinstance(line['credit'], Decimal) for line in records[0]['lines'])
            assert all('account_code' not in line and line['external_account_code'].startswith('X') for line in records[0]['lines'])
            if self.error:
                raise self.error
            return ConnectorResult('smartaccounts', 'push', True, False, 'Synthetic acknowledgement', records=({'external_id': 'remote-1'},))

    fake = FakeConnector()
    monkeypatch.setattr('connectors.registry.connector_for', lambda *args, **kwargs: fake)
    return ee_org['id'], run, fake, PushService(db)


def prepare(source, object_type='pay_runs', provider='smartaccounts'):
    oid, run, _, service = source
    return service.prepare(oid, provider, object_type, run['id'] if object_type == 'pay_runs' else run['posted_batch_id'], ACTOR)


def test_mapping_gap_lists_all_missing_and_suggested_codes(db, source):
    oid, run, fake, service = source
    with db.transaction() as tx:
        tx.execute("UPDATE account_mappings SET status='Suggested' WHERE organisation_id=? AND local_account_code='6110'", (oid,))
        tx.execute("UPDATE account_mappings SET status='Disabled' WHERE organisation_id=? AND local_account_code='6120'", (oid,))
    with pytest.raises(ValueError) as error:
        prepare(source)
    assert '6110' in str(error.value) and '6120' in str(error.value)
    assert not fake.calls
    assert service.list(oid) == []


def test_review_gate_and_exact_decimal_roundtrip(db, source):
    oid, run, fake, service = source
    push = prepare(source)
    with pytest.raises(ValueError, match='reviewed'):
        service.execute(oid, push['id'], ACTOR)
    assert not fake.calls
    payload = json.loads(push['payload_json'], parse_float=Decimal)
    entries = db.rows('SELECT debit,credit FROM gl_entries WHERE organisation_id=? AND posting_batch_id=? ORDER BY line_number', (oid, run['posted_batch_id']))
    assert payload['doc_no'] == 'PAY-2026-07'
    for line, entry in zip(payload['lines'], entries, strict=True):
        assert isinstance(line['debit'], str) and isinstance(line['credit'], str)
        assert money(line['debit']) == money(entry['debit'])
        assert money(line['credit']) == money(entry['credit'])
    service.review(oid, push['id'], ACTOR)
    result = service.execute(oid, push['id'], ACTOR)
    assert result['status'] == 'Completed'
    assert result['write_count'] == result['read_count'] == len(entries)
    assert result['reviewed_by'] == ACTOR and result['reviewed_at']
    mapping = db.one("SELECT * FROM external_mappings WHERE organisation_id=? AND provider='smartaccounts' AND object_type='gl_batch' AND local_id=?", (oid, run['id']))
    assert mapping['external_id'] == 'remote-1'
    assert (mapping['ownership'], mapping['direction']) == ('fastaccounts', 'export')
    assert sum((line['debit'] for line in fake.calls[0][1][0]['lines']), Decimal(0)) == sum((line['credit'] for line in fake.calls[0][1][0]['lines']), Decimal(0))


def test_changed_payload_refuses_review_and_execution(db, source):
    oid, _, fake, service = source
    push = prepare(source)
    service.review(oid, push['id'], ACTOR)
    with db.transaction() as tx:
        tx.execute("UPDATE account_mappings SET external_account_code='CHANGED' WHERE organisation_id=? AND provider='smartaccounts' AND local_account_code='6110'", (oid,))
    with pytest.raises(ValueError, match='prepared payload changed; prepare again'):
        service.execute(oid, push['id'], ACTOR)
    with pytest.raises(ValueError, match='prepared payload changed; prepare again'):
        service.review(oid, push['id'], ACTOR)
    assert service.get(oid, push['id'])['reviewed_at'] is None
    assert prepare(source)['status'] == 'Review Required'
    assert not fake.calls


@pytest.mark.parametrize('error', [ProviderError('Synthetic provider outage'), ValueError('Synthetic invalid wire record')])
def test_failure_and_explicit_reexecution(db, source, error):
    oid, _, fake, service = source
    push = prepare(source)
    service.review(oid, push['id'], ACTOR)
    fake.error = error
    failed = service.execute(oid, push['id'], ACTOR)
    assert (failed['status'], failed['conflict_count'], failed['write_count']) == ('Failed', 1, 0)
    assert failed['error_message'] == str(error)
    assert len(fake.calls) == 1
    assert db.scalar('SELECT COUNT(*) FROM external_mappings WHERE organisation_id=?', (oid,)) == 0
    fake.error = None
    completed = service.execute(oid, push['id'], ACTOR)
    assert completed['status'] == 'Completed' and completed['conflict_count'] == 1
    assert completed['error_message'] is None and len(fake.calls) == 2


def test_already_pushed_and_journal_alias_refused(source):
    oid, _, fake, service = source
    push = prepare(source)
    service.review(oid, push['id'], ACTOR)
    service.execute(oid, push['id'], ACTOR)
    for object_type in ('pay_runs', 'journals'):
        new = prepare(source, object_type)
        service.review(oid, new['id'], ACTOR)
        with pytest.raises(ValueError, match='already been pushed'):
            service.execute(oid, new['id'], ACTOR)
    assert len(fake.calls) == 1


def test_lists_dedupe_and_tenant_scoping(db, source, uk_org):
    oid, run, _, service = source
    push = prepare(source)
    other = prepare(source, provider='merit')
    assert service.list(oid, 'smartaccounts') == [push]
    assert service.list(oid, object_type='journals') == []
    assert len(service.list(oid, pay_run_id=run['id'])) == 2
    assert PayrollService(db).pushes(oid, run['id']) == service.list(oid, pay_run_id=run['id'])
    assert service.list(uk_org['id']) == []
    for method in (service.get, service.review, service.execute):
        with pytest.raises(KeyError):
            method(uk_org['id'], push['id'], *([] if method == service.get else [ACTOR]))
    with pytest.raises(KeyError):
        service.list(uk_org['id'], pay_run_id=run['id'])
    with pytest.raises(ValueError, match='already pending'):
        prepare(source)
    # Voucher aliases are stored canonically as batch IDs.
    journal = service.prepare(oid, 'smartaccounts', 'journals', 'PAY-2026-07', ACTOR)
    assert journal['local_ref'] == run['posted_batch_id']
    with pytest.raises(ValueError, match='already pending'):
        prepare(source, 'journals')
    assert other['provider'] == 'merit'


def test_pay_run_gates(db, source, uk_org):
    oid, run, _, service = source
    payroll = PayrollService(db)
    draft = payroll.create_run(oid, period='2026-08', actor=ACTOR)
    with pytest.raises(ValueError, match='Approved'):
        service.prepare(oid, 'smartaccounts', 'pay_runs', draft['id'], ACTOR)
    with db.transaction() as tx:
        tx.execute("UPDATE pay_runs SET status='Approved' WHERE organisation_id=? AND id=?", (oid, draft['id']))
    with pytest.raises(ValueError, match='posted ledger batch'):
        service.prepare(oid, 'smartaccounts', 'pay_runs', draft['id'], ACTOR)
    with pytest.raises(ValueError, match='Estonian organisation with EUR'):
        service.prepare(uk_org['id'], 'smartaccounts', 'journals', run['posted_batch_id'], ACTOR)
    with db.transaction() as tx:
        tx.execute("UPDATE organisations SET base_currency='GBP' WHERE id=?", (oid,))
    with pytest.raises(ValueError, match='EUR'):
        prepare(source)


def test_reversal_journal_prepare_review_execute(db, source):
    oid, run, fake, service = source
    reversed_batch = LedgerService(db).reverse(run['posted_batch_id'], reversal_date='2026-07-31', actor=ACTOR, reason='Synthetic correction')
    push = service.prepare(oid, 'smartaccounts', 'journals', reversed_batch['id'], ACTOR)
    assert json.loads(push['payload_json'])['doc_no'] == 'REV-PAY-2026-07'
    service.review(oid, push['id'], ACTOR)
    assert service.execute(oid, push['id'], ACTOR)['status'] == 'Completed'
    assert fake.calls[0][1][0]['doc_no'] == 'REV-PAY-2026-07'


def test_merit_chunk_acknowledgements_are_retained(db, source, monkeypatch):
    from ledger import PostingLine

    oid, _, _, service = source
    accounts = db.rows("SELECT id FROM accounts WHERE organisation_id=? AND code IN ('6110','2210') ORDER BY code", (oid,))
    batch = LedgerService(db).post(organisation_id=oid, voucher_type='manual_journal', voucher_id='synthetic-large',
                                  voucher_code='GL-LARGE', posting_date='2026-07-31', actor=ACTOR, currency='EUR',
                                  lines=[PostingLine(accounts[0]['id'], debit=Decimal('0.01')) for _ in range(251)]
                                  + [PostingLine(accounts[1]['id'], credit=Decimal('0.01')) for _ in range(251)])
    class ChunkConnector:
        def push(self, object_type, records):
            assert object_type == 'gl_batch' and len(records[0]['lines']) == 502
            return ConnectorResult('merit', 'push', True, False, 'Synthetic chunks',
                                   records=({'GLBId': 'chunk-1'}, {'GLBId': 'chunk-2'}))
    monkeypatch.setattr('connectors.registry.connector_for', lambda *args, **kwargs: ChunkConnector())
    push = service.prepare(oid, 'merit', 'journals', batch['id'], ACTOR)
    service.review(oid, push['id'], ACTOR)
    result = service.execute(oid, push['id'], ACTOR)
    assert (result['status'], result['write_count']) == ('Completed', 502)
    mapping = db.one("SELECT * FROM external_mappings WHERE organisation_id=? AND provider='merit' AND local_id=?", (oid, batch['id']))
    assert mapping['external_id'] == 'chunk-1'
    assert json.loads(mapping['external_version']) == {'external_ids': ['chunk-1', 'chunk-2']}


def test_missing_acknowledgement_id_fails_without_retry(source, monkeypatch):
    oid, _, _, service = source
    class UnacknowledgedConnector:
        calls = 0
        def push(self, *args):
            self.calls += 1
            return ConnectorResult('smartaccounts', 'push', True, False, 'Synthetic missing ID', records=({},))
    fake = UnacknowledgedConnector()
    monkeypatch.setattr('connectors.registry.connector_for', lambda *args, **kwargs: fake)
    push = prepare(source)
    service.review(oid, push['id'], ACTOR)
    result = service.execute(oid, push['id'], ACTOR)
    assert (result['status'], result['conflict_count']) == ('Failed', 1)
    assert fake.calls == 1


def test_api_roles_and_tenant_boundaries(db, source, uk_org, monkeypatch):
    oid, run, fake, _ = source
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    from api_app import api
    client = TestClient(api)
    root = f'/organisations/{oid}'
    orgs = OrganisationService(db)
    for role in ('accountant', 'approver', 'viewer'):
        orgs.add_member(oid, ACTOR, f'{role}@example.test', role)
    accountant = {'X-Test-User': 'accountant@example.test'}
    approver = {'X-Test-User': 'approver@example.test'}
    viewer = {'X-Test-User': 'viewer@example.test'}
    url = root + f"/integrations/smartaccounts/push/pay-runs/{run['id']}/prepare"
    assert client.post(url, json={}, headers=viewer).status_code == 403
    push = client.post(url, json={}, headers=accountant)
    assert push.status_code == 200, push.text
    push_id = push.json()['id']
    assert client.get(root + f'/pushes/{push_id}', headers=viewer).status_code == 200
    assert client.get(root + '/integrations/smartaccounts/pushes', headers=viewer).json()[0]['id'] == push_id
    assert client.get(root + f"/pay-runs/{run['id']}/pushes", headers=viewer).json()[0]['id'] == push_id
    assert client.post(root + f'/pushes/{push_id}/execute', headers=accountant).status_code == 422
    assert client.post(root + f'/pushes/{push_id}/review', headers=approver).status_code == 200
    assert client.post(root + f'/pushes/{push_id}/execute', headers=approver).status_code == 403
    assert client.post(root + f'/pushes/{push_id}/execute', headers=accountant).json()['status'] == 'Completed'
    assert client.get(f"/organisations/{uk_org['id']}/pushes/{push_id}", headers={'X-Test-User': ACTOR}).status_code == 404
    assert len(fake.calls) == 1


@pytest.mark.parametrize('role,viewport', [('owner', {'width': 1440, 'height': 1000}), ('approver', {'width': 390, 'height': 844})])
def test_browser_reviewed_push_and_mapping_controls(db, source, monkeypatch, role, viewport):
    """Render the real API through intercepted browser requests, entirely offline."""
    from pathlib import Path
    from urllib.parse import urlsplit

    playwright = pytest.importorskip('playwright.sync_api')
    oid, run, fake, service = source
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    monkeypatch.setenv('FASTACCOUNTS_DEFAULT_LANG', 'en')
    from api_app import api
    from web_app import app

    email = ACTOR
    if role != 'owner':
        email = f'{role}@example.test'
        OrganisationService(db).add_member(oid, ACTOR, email, role)
    headers = {'X-Test-User': email}
    root = Path(__file__).resolve().parents[1]
    html = TestClient(app).get('/auth/test').text
    api_client = TestClient(api)
    page_errors = []
    with playwright.sync_playwright() as runtime:
        try:
            browser = runtime.chromium.launch()
        except playwright.Error as error:
            if "Executable doesn't exist" in str(error):
                pytest.skip('Install Playwright Chromium to run browser regressions')
            raise
        page = browser.new_page(viewport=viewport)
        page.on('pageerror', lambda error: page_errors.append(str(error)))

        def respond(route):
            path = urlsplit(route.request.url).path
            if path == '/api/csrf':
                return route.fulfill(json={'csrf_token': 'synthetic-token'})
            if path.startswith('/api/'):
                response = api_client.request(route.request.method, path[4:], headers={**headers, 'Content-Type': 'application/json'},
                                              content=route.request.post_data)
                return route.fulfill(status=response.status_code, body=response.content,
                                     content_type=response.headers.get('content-type', 'application/json'))
            if path == '/app':
                return route.fulfill(body=html, content_type='text/html')
            if path in ('/static/app.js', '/static/app.css'):
                return route.fulfill(path=str(root / path.lstrip('/')))
            return route.fulfill(status=404)

        page.route('**/*', respond)
        page.goto('http://workspace.test/app#payroll')
        prepare_button = page.locator('[data-action="preparePush"][data-provider="smartaccounts"]').first
        playwright.expect(prepare_button).to_be_enabled()
        prepare_button.click()
        playwright.expect(page.locator('[data-action="executePush"]').first).to_be_disabled()
        page.locator('summary').filter(has_text='View prepared journal').first.click()
        playwright.expect(page.locator('#app-content')).to_contain_text('X6110')
        page.locator('[data-action="reviewPush"]').first.click()
        playwright.expect(page.locator('#app-content')).to_contain_text('Reviewed')
        execute = page.locator('[data-action="executePush"]').first
        if role == 'owner':
            playwright.expect(execute).to_be_enabled()
            execute.click()
            page.locator('.dialog [data-action="confirm"]').click()
            playwright.expect(page.locator('#app-content')).to_contain_text('Completed')
            assert len(fake.calls) == 1
        else:
            playwright.expect(execute).to_be_disabled()
            assert not fake.calls
        page.evaluate("location.hash = 'integrations/accounting/smartaccounts'")
        playwright.expect(page.locator('#app-content h1')).to_have_text('SmartAccounts')
        playwright.expect(page.locator('#app-content')).to_contain_text('PAY-2026-07')
        page.locator('[data-action="glReconciliation"]').click()
        playwright.expect(page.locator('#gl-reconciliation h3')).to_have_text('GL reconciliation')
        if role == 'owner':
            with db.transaction() as tx:
                tx.execute("UPDATE account_mappings SET status='Suggested' WHERE organisation_id=? AND provider='smartaccounts' AND local_account_code='6110'", (oid,))
            page.locator('[data-action="suggestMappings"]').click()
            playwright.expect(page.locator('#mapping-suggestions')).to_contain_text('X6110')
            page.locator('[data-action="confirmSuggestion"]').click()
            playwright.expect(page.locator('#toasts .toast.error')).to_have_count(0)
            playwright.expect(page.locator('#mapping-suggestions')).to_be_empty()
            assert AccountMappingService(db).resolve(oid, 'smartaccounts', '6110')['status'] == 'Confirmed'
            page.locator('[data-action="editMapping"]').first.click()
            page.locator('[name="external_account_name"]').fill('Synthetic account label')
            page.locator('.dialog button[type="submit"]').click()
            playwright.expect(page.locator('#app-content')).to_contain_text('Synthetic account label')
        else:
            playwright.expect(page.locator('[data-action="addMapping"]')).to_be_disabled()
        assert not page_errors
        browser.close()
