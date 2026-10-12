"""Synthetic quote workflow, ledger, tenancy, migration and API regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from core_utils import money, new_id, utc_now
from database import Database, reset_database_cache
from documents import DocumentService
from quotes import QuoteService

ACTOR = 'owner@example.test'
STATES = ['Draft', 'Sent', 'Accepted', 'Declined', 'Expired', 'Converted']


@pytest.fixture
def offer(db, ee_org, monkeypatch):
    oid = ee_org['id']
    docs = DocumentService(db)
    contact = docs.create_contact(oid, name='Synthetic customer', country_code='EE', contact_type='customer')
    account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (oid,))
    tax = db.scalar("SELECT id FROM tax_codes WHERE organisation_id=? AND kind='standard' AND active=1", (oid,))
    day = db.scalar('SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1', (oid,))
    monkeypatch.setattr('quotes.today', lambda: day)
    data = dict(contact_id=contact['id'], quote_date=day, valid_until=day,
                notes='Synthetic offer', lines=[dict(description='Service A', quantity='2.1250', unit_price='42.1234',
                    account_id=account, tax_code_id=tax), dict(description='Service B', quantity='1', unit_price='10', account_id=account)])
    return QuoteService(db), oid, data


def set_state(service, oid, data, state):
    quote = service.create(oid, actor=ACTOR, **data)
    if state in {'Sent', 'Accepted', 'Declined', 'Converted'}:
        quote = service.send(oid, quote['id'], actor=ACTOR)
    if state in {'Accepted', 'Converted'}:
        quote = service.accept(oid, quote['id'], actor=ACTOR)
    if state == 'Declined':
        quote = service.decline(oid, quote['id'], actor=ACTOR)
    if state == 'Converted':
        service.convert(oid, quote['id'], actor=ACTOR)
        quote = service.get(oid, quote['id'])
    if state == 'Expired':
        with service.db.transaction() as tx:
            tx.execute("UPDATE quotes SET status='Expired' WHERE organisation_id=? AND id=?", (oid, quote['id']))
        quote = service.get(oid, quote['id'])
    return quote


@pytest.mark.parametrize('state', STATES)
@pytest.mark.parametrize('action', ['update', 'send', 'accept', 'decline', 'expire', 'convert'])
def test_every_status_transition(db, offer, monkeypatch, state, action):
    service, oid, data = offer
    quote = set_state(service, oid, data, state)
    if action == 'expire':
        next_day = (date.fromisoformat(data['valid_until']) + timedelta(days=1)).isoformat()
        monkeypatch.setattr('quotes.today', lambda: next_day)
    legal = {'update': {'Draft'}, 'send': {'Draft'}, 'accept': {'Sent'}, 'decline': {'Sent'},
             'expire': {'Draft', 'Sent'}, 'convert': {'Accepted', 'Converted'}}
    before = service.get(oid, quote['id'])
    ledger = db.rows('SELECT * FROM gl_entries ORDER BY id')
    if state not in legal[action]:
        with pytest.raises(ValueError):
            getattr(service, action)(oid, quote['id'], actor=ACTOR)
        assert service.get(oid, quote['id']) == before
        assert db.rows('SELECT * FROM gl_entries ORDER BY id') == ledger
    else:
        result = getattr(service, action)(oid, quote['id'], actor=ACTOR)
        expected = {'update': 'Draft', 'send': 'Sent', 'accept': 'Accepted', 'decline': 'Declined', 'expire': 'Expired', 'convert': 'Converted'}[action]
        after = service.get(oid, quote['id'])
        assert after['status'] == expected
        if action == 'accept':
            assert after['accepted_at'] and after['accepted_by'] == ACTOR
        if action != 'convert':
            assert db.rows('SELECT * FROM gl_entries ORDER BY id') == ledger
        else:
            assert result['id'] == after['converted_invoice_id']


@pytest.mark.parametrize('amount_type', ['exclusive', 'inclusive', 'no_tax'])
def test_conversion_matches_direct_invoice_and_is_idempotent(db, offer, amount_type):
    service, oid, data = offer
    data = {**data, 'amount_type': amount_type}
    quote = set_state(service, oid, data, 'Accepted')
    assert not db.rows('SELECT * FROM posting_batches')
    direct = service.documents.create_invoice(oid, contact_id=data['contact_id'], issue_date=data['quote_date'],
        amount_type=amount_type, lines=data['lines'], notes=data['notes'], actor=ACTOR)
    direct = service.documents.issue_invoice(direct['id'], actor=ACTOR)
    invoice = service.convert(oid, quote['id'], actor=ACTOR)
    for key in ['currency', 'status', 'subtotal', 'tax_total', 'total', 'due_date', 'line_amount_type', 'contact_id', 'notes']:
        assert invoice[key] == direct[key]
    for a, b in zip(invoice['lines'], direct['lines'], strict=True):
        assert {k:v for k,v in a.items() if k not in {'id','invoice_id'}} == {k:v for k,v in b.items() if k not in {'id','invoice_id'}}
    def postings(invoice):
        entries = db.rows('SELECT account_id,debit,credit FROM gl_entries WHERE posting_batch_id=? ORDER BY account_id', (invoice['posting_batch_id'],))
        assert sum((money(e['debit']) - money(e['credit']) for e in entries), Decimal(0)) == 0
        return entries
    assert postings(invoice) == postings(direct)
    assert direct['number'] == 'INV-000001' and invoice['number'] == 'INV-000002'
    before = db.rows('SELECT * FROM gl_entries ORDER BY id')
    assert service.convert(oid, quote['id'], actor=ACTOR) == invoice
    assert service.documents.invoice(invoice['id'], oid) == invoice
    assert db.rows('SELECT * FROM gl_entries ORDER BY id') == before
    assert db.scalar('SELECT COUNT(*) FROM invoices') == 2


def test_expiry_boundary_and_strict_stale_acceptance(db, offer, monkeypatch):
    service, oid, data = offer
    draft = service.create(oid, actor=ACTOR, **data)
    sent = set_state(service, oid, data, 'Sent')
    accepted = set_state(service, oid, data, 'Accepted')
    declined = set_state(service, oid, data, 'Declined')
    with pytest.raises(ValueError, match='still valid'):
        service.expire(oid, draft['id'], actor=ACTOR)
    assert service.expire_due(oid) == {'expired': 0}
    boundary_accept = service.accept(oid, sent['id'], actor=ACTOR)
    assert boundary_accept['status'] == 'Accepted'
    sent = set_state(service, oid, data, 'Sent')
    tomorrow = (date.fromisoformat(data['valid_until']) + timedelta(days=1)).isoformat()
    monkeypatch.setattr('quotes.today', lambda: tomorrow)
    with pytest.raises(ValueError, match='expired'):
        service.accept(oid, sent['id'], actor=ACTOR)
    with pytest.raises(ValueError, match='expired'):
        service.send(oid, draft['id'], actor=ACTOR)
    assert service.expire_due(oid) == {'expired': 2}
    assert service.expire_due(oid) == {'expired': 0}
    assert service.get(oid, draft['id'])['status'] == 'Expired'
    assert service.get(oid, sent['id'])['status'] == 'Expired'
    assert service.get(oid, declined['id'])['status'] == 'Declined'
    assert service.get(oid, accepted['id'])['status'] == 'Accepted'
    assert not db.rows('SELECT * FROM posting_batches')
    service.convert(oid, accepted['id'], actor=ACTOR)


def test_draft_editing_numbering_and_validation_rollback(db, offer):
    service, oid, data = offer
    a = service.create(oid, actor=ACTOR, **data)
    assert a['quote_number'] == 'QUO-000001'
    with pytest.raises(ValueError):
        service.create(oid, actor=ACTOR, **{**data, 'lines': []})
    b = service.create(oid, actor=ACTOR, **data)
    assert b['quote_number'] == 'QUO-000002'
    updated = service.update(oid, a['id'], actor=ACTOR, notes='Updated', lines=[{**data['lines'][0], 'quantity': '3'}])
    assert updated['quote_number'] == a['quote_number'] and updated['notes'] == 'Updated'
    assert len(updated['lines']) == 1 and updated['lines'][0]['quantity'] == 3
    with pytest.raises(ValueError):
        service.update(oid, a['id'], actor=ACTOR, lines=[{**data['lines'][0], 'account_id': 'missing'}])
    assert service.get(oid, a['id']) == updated
    assert db.scalar("SELECT next_number FROM document_sequences WHERE organisation_id=? AND document_type='invoice'", (oid,)) == 1


@pytest.mark.parametrize('changes', [dict(currency='USD'), dict(quote_date='bad'), dict(valid_until='1900-01-01'),
    dict(amount_type='bad'), dict(contact_id='missing')])
def test_header_guards(db, offer, changes):
    service, oid, data = offer
    with pytest.raises(ValueError):
        service.create(oid, actor=ACTOR, **{**data, **changes})
    assert not service.list(oid) and not db.rows('SELECT * FROM quote_lines')


def test_total_overflow_is_a_validation_error(db, offer):
    service, oid, data = offer
    with pytest.raises(ValueError, match='supported amount'):
        service.create(oid, actor=ACTOR, **{**data, 'lines': [{**data['lines'][0],
            'quantity':'9999999999999999', 'unit_price':'9999999999999999'}]})
    assert not service.list(oid)


@pytest.mark.parametrize('field,value', [('quantity', '0'), ('quantity', '-1'), ('unit_price','-1'),
    ('unit_price','NaN'), ('quantity','Infinity'), ('unit_price','abc'), ('unit_price','0.00001'),
    ('quantity','10000000000000000'), ('account_id','missing'), ('tax_code_id','missing')])
def test_line_guards(db, offer, field, value):
    service, oid, data = offer
    with pytest.raises(ValueError):
        service.create(oid, actor=ACTOR, **{**data, 'lines': [{**data['lines'][0], field: value}]})
    assert not service.list(oid)


def test_tenant_currency_and_database_foreign_keys(db, offer, uk_org):
    service, oid, data = offer
    quote = service.create(oid, actor=ACTOR, **data)
    foreign = uk_org['id']
    assert service.list(foreign) == []
    for action in ['get', 'update', 'send', 'accept', 'decline', 'expire', 'convert']:
        with pytest.raises(KeyError):
            getattr(service, action)(foreign, quote['id'], **({} if action == 'get' else {'actor': ACTOR}))
    customer = service.documents.create_contact(foreign, name='Foreign customer', country_code='UK', contact_type='customer')
    account = db.scalar("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (foreign,))
    tax = db.scalar('SELECT id FROM tax_codes WHERE organisation_id=? LIMIT 1', (foreign,))
    for changes in [dict(contact_id=customer['id']), dict(lines=[{**data['lines'][0], 'account_id': account}]),
                    dict(lines=[{**data['lines'][0], 'tax_code_id': tax}])]:
        with pytest.raises(ValueError):
            service.create(oid, actor=ACTOR, **{**data, **changes})
    for column, value in [('contact_id',customer['id'])]:
        with pytest.raises(sqlite3.IntegrityError), db.transaction() as tx:
            tx.execute(f'UPDATE quotes SET {column}=? WHERE id=?', (value, quote['id']))
    for column, value in [('account_id',account), ('quote_id', 'missing'), ('tax_code_id',tax)]:
        with pytest.raises(sqlite3.IntegrityError), db.transaction() as tx:
            tx.execute(f'UPDATE quote_lines SET {column}=? WHERE quote_id=?', (value, quote['id']))
    uk_data = {**data, 'contact_id': customer['id'], 'lines': [dict(description='UK service', quantity=1, unit_price=5, account_id=account)]}
    uk_quote = service.create(foreign, actor=ACTOR, **uk_data)
    assert uk_quote['currency'] == 'GBP' and uk_quote['quote_number'] == 'QUO-000001'
    assert quote['currency'] == 'EUR'
    foreign_invoice = service.documents.create_invoice(foreign, contact_id=customer['id'],
        issue_date=data['quote_date'], lines=uk_data['lines'], actor=ACTOR)
    service.send(oid, quote['id'], actor=ACTOR)
    service.accept(oid, quote['id'], actor=ACTOR)
    with pytest.raises(sqlite3.IntegrityError), db.transaction() as tx:
        tx.execute("UPDATE quotes SET status='Converted',converted_invoice_id=? WHERE id=?", (foreign_invoice['id'], quote['id']))
    # Expiring one tenant's offers leaves another tenant's stale offer untouched.
    with db.transaction() as tx:
        tx.execute("UPDATE quotes SET quote_date='1900-01-01',valid_until='1900-01-02' WHERE id=?", (uk_quote['id'],))
    service.expire_due(oid)
    assert service.get(foreign, uk_quote['id'])['status'] == 'Draft'


def test_inactive_accounts_tax_and_supplier_guards(db, offer):
    service, oid, data = offer
    supplier = service.documents.create_contact(oid, name='Synthetic supplier', country_code='EE', contact_type='supplier')
    with pytest.raises(ValueError, match='customer'):
        service.create(oid, actor=ACTOR, **{**data, 'contact_id':supplier['id']})
    for table, column in [('accounts', 'account_id'), ('tax_codes', 'tax_code_id')]:
        with db.transaction() as tx:
            tx.execute(f'UPDATE {table} SET active=0 WHERE id=?', (data['lines'][0][column],))
        with pytest.raises(ValueError, match='active'):
            service.create(oid, actor=ACTOR, **data)
        with db.transaction() as tx:
            tx.execute(f'UPDATE {table} SET active=1 WHERE id=?', (data['lines'][0][column],))


def test_failed_posting_and_sequence_allocation_are_atomic(db, offer, monkeypatch):
    from quote_repository import QuoteRepository
    service, oid, data = offer
    quote = set_state(service, oid, data, 'Accepted')
    original = QuoteRepository.transition
    def fail_conversion(self, quote_id, status, **kwargs):
        if status == 'Converted':
            raise RuntimeError('Synthetic conversion link failure')
        return original(self, quote_id, status, **kwargs)
    monkeypatch.setattr(QuoteRepository, 'transition', fail_conversion)
    with pytest.raises(RuntimeError):
        service.convert(oid, quote['id'], actor=ACTOR)
    assert service.get(oid, quote['id'])['status'] == 'Accepted'
    assert not db.rows('SELECT * FROM invoices') and not db.rows('SELECT * FROM gl_entries')
    assert db.scalar("SELECT next_number FROM document_sequences WHERE organisation_id=? AND document_type='invoice'", (oid,)) == 1
    assert not db.rows("SELECT * FROM audit_events WHERE action IN ('invoice.created','invoice.issued','quote.converted')")


def test_conversion_rolls_back_when_period_locked(db, offer):
    service, oid, data = offer
    quote = set_state(service, oid, data, 'Accepted')
    with db.transaction() as tx:
        tx.execute("UPDATE fiscal_periods SET status='Locked' WHERE organisation_id=?", (oid,))
    with pytest.raises(ValueError):
        service.convert(oid, quote['id'], actor=ACTOR)
    assert service.get(oid, quote['id'])['status'] == 'Accepted'
    assert not db.rows('SELECT * FROM invoices') and not db.rows('SELECT * FROM posting_batches')
    assert db.scalar("SELECT next_number FROM document_sequences WHERE organisation_id=? AND document_type='invoice'", (oid,)) == 1


def test_concurrent_conversion_and_numbering(db, offer):
    service, oid, data = offer
    with ThreadPoolExecutor(max_workers=2) as pool:
        created = list(pool.map(lambda _: service.create(oid, actor=ACTOR, **data), range(2)))
    assert {q['quote_number'] for q in created} == {'QUO-000001','QUO-000002'}
    quote = set_state(service, oid, data, 'Accepted')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.convert(oid, quote['id'], actor=ACTOR), range(2)))
    assert results[0] == results[1]
    assert db.scalar('SELECT COUNT(*) FROM invoices') == 1
    assert db.scalar('SELECT COUNT(*) FROM posting_batches') == 1


def test_upgrade_preserves_data_and_existing_sequences(tmp_path, monkeypatch):
    import database
    from organisations import OrganisationService
    original = database.MIGRATIONS
    directory = tmp_path / 'previous' / 'sqlite'
    directory.mkdir(parents=True)
    for file in (original / 'sqlite').glob('*.sql'):
        if file.stem < '0020':
            shutil.copyfile(file, directory / file.name)
    monkeypatch.setattr(database, 'MIGRATIONS', directory.parent)
    db = Database(path=str(tmp_path / 'upgrade.sqlite'))
    db.migrate()
    org = OrganisationService(db).create(name='Preserved', country_code='EE', entity_type='EE_OU', owner_email=ACTOR)
    with db.transaction() as tx:
        tx.execute("DELETE FROM document_sequences WHERE document_type='quote'")
        tx.execute("UPDATE document_sequences SET next_number=42 WHERE document_type='invoice'")
    before = {table: db.rows(f'SELECT * FROM {table} ORDER BY id') for table in ['organisations','accounts','contacts','invoices','gl_entries']}
    monkeypatch.setattr(database, 'MIGRATIONS', original)
    assert db.migrate() == ['0020_quotes', '0021_periodisation', '0022_payment_links', '0023_analytical_objects', '0024_reminder_rules', '0025_fx_realised'] and db.migrate() == []
    for table, rows in before.items():
        assert db.rows(f'SELECT * FROM {table} ORDER BY id') == rows
    assert db.scalar("SELECT next_number FROM document_sequences WHERE document_type='invoice'") == 42
    assert db.scalar("SELECT next_number FROM document_sequences WHERE organisation_id=? AND document_type='quote'", (org['id'],)) == 1
    assert db.rows('PRAGMA foreign_key_check') == []


def test_api_authorisation_csrf_and_workflow(db, offer, uk_org, monkeypatch):
    from api_app import api, User, current_user, require_csrf
    service, oid, data = offer
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    reset_database_cache()
    viewer = {'X-Test-User': 'viewer@example.test'}
    with db.transaction() as tx:
        tx.execute('INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)', (new_id(),oid,'viewer@example.test','viewer',utc_now()))
    base = f'/organisations/{oid}/quotes'
    with TestClient(api, headers={'X-Test-User': ACTOR}) as client:
        response = client.post(base, json=data)
        assert response.status_code == 201, response.text
        quote = response.json()
        url = base + '/' + quote['id']
        assert client.get(base, headers=viewer).status_code == 200
        assert client.get(url, headers=viewer).status_code == 200
        assert client.post(base, headers=viewer, json=data).status_code == 403
        assert client.patch(url, headers=viewer, json={'notes':'bad'}).status_code == 403
        for action in ['send','accept','decline','expire-status','convert']:
            assert client.post(url + '/' + action, headers=viewer).status_code == 403
            assert client.post(url + '/' + action, headers={'X-Test-User':'outsider@example.test'}).status_code == 403
            assert client.post(f"/organisations/{uk_org['id']}/quotes/{quote['id']}/{action}").status_code == 404
        assert client.get(url, headers={'X-Test-User':'outsider@example.test'}).status_code == 403
        assert client.get(f"/organisations/{uk_org['id']}/quotes/{quote['id']}").status_code == 404
        assert client.patch(url, json={'notes': 'API edit'}).json()['notes'] == 'API edit'
        assert client.patch(url, json={'lines':None}).status_code == 422
        assert client.post(url + '/convert').status_code == 422
        assert client.post(url + '/send').json()['status'] == 'Sent'
        assert client.patch(url, json={'notes':'bad'}).status_code == 422
        assert client.post(url + '/accept').json()['status'] == 'Accepted'
        invoice = client.post(url + '/convert').json()
        assert invoice['status'] == 'Issued'
        assert client.post(url + '/convert').json() == invoice
        assert client.get(url).json()['status'] == 'Converted'
        declined = client.post(base, json=data).json()
        other = base + '/' + declined['id']
        client.post(other + '/send')
        assert client.post(other + '/decline').json()['status'] == 'Declined'
        assert client.post(other + '/accept').status_code == 422
        old = client.post(base, json={**data, 'quote_date':'2000-01-01','valid_until':'2000-01-02'}).json()
        assert client.post(base + '/' + old['id'] + '/expire-status').json()['status'] == 'Expired'
    routes = [r for r in api.routes if '/quotes' in r.path]
    assert len(routes) == 9
    for route in routes:
        assert (current_user if route.methods == {'GET'} else require_csrf) in [d.call for d in route.dependant.dependencies]
    api.dependency_overrides[current_user] = lambda: User(email=ACTOR)
    try:
        from web_app import app
        with TestClient(app) as client:
            token = client.get('/api/csrf').json()['csrf_token']
            for route, method, payload in [(base,'POST',data), (url,'PATCH',{'notes':'bad'})] + [(url+'/'+a,'POST',None) for a in ['send','accept','decline','expire-status','convert']]:
                assert client.request(method, '/api'+route, json=payload).status_code == 403
            assert client.post('/api'+base, headers={'X-CSRF-Token':token}, json=data).status_code == 201
    finally:
        api.dependency_overrides.clear()
        reset_database_cache()
