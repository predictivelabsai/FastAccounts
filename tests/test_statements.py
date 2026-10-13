from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core_utils import new_id
from database import reset_database_cache
from documents import DocumentService
from ledger import LedgerService, PostingLine
from opening_balances import OpeningBalanceService
from statements import StatementService
from prepayments import PrepaymentService


@pytest.fixture
def statement_data(db, ee_org):
    docs = DocumentService(db)
    contact = docs.create_contact(ee_org['id'], name='Synthetic Õun OÜ', country_code='EE')
    accounts = {r['system_role']: r['id'] for r in db.rows(
        'SELECT * FROM accounts WHERE organisation_id=?', (ee_org['id'],))}
    start = date.fromisoformat(db.scalar(
        'SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1', (ee_org['id'],)))
    return docs, contact, accounts, start


def post(db, org, contact, accounts, day, amount, *, side='customer', currency='EUR', transaction_amount=None):
    value = Decimal(amount)
    debit = max(value, Decimal('0')) if side == 'customer' else max(-value, Decimal('0'))
    credit = max(-value, Decimal('0')) if side == 'customer' else max(value, Decimal('0'))
    return LedgerService(db).post(organisation_id=org['id'], voucher_type='manual_journal',
        voucher_id=new_id(), voucher_code='TEST', posting_date=day.isoformat(), actor='owner@example.test',
        currency=org['base_currency'], lines=[
            PostingLine(accounts['AR' if side == 'customer' else 'AP'], debit=debit, credit=credit,
                contact_id=contact['id'], transaction_currency=currency,
                transaction_amount=Decimal(transaction_amount) if transaction_amount else debit-credit),
            PostingLine(accounts['CAPITAL'], debit=credit, credit=debit)])


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_statement_arithmetic_boundaries_reversals_and_currency(db, ee_org, statement_data, side):
    docs, contact, accounts, start = statement_data
    post(db, ee_org, contact, accounts, start, '100', side=side)
    first = start + timedelta(days=1)
    end = start + timedelta(days=2)
    batch = post(db, ee_org, contact, accounts, first, '50', side=side)
    post(db, ee_org, contact, accounts, end, '-20', side=side)
    foreign = '36' if side == 'customer' else '-36'
    post(db, ee_org, contact, accounts, end, '30', side=side, currency='USD', transaction_amount=foreign)
    LedgerService(db).reverse(batch['id'], reversal_date=end.isoformat(), actor='owner@example.test')
    post(db, ee_org, contact, accounts, end + timedelta(days=1), '999', side=side)
    report = StatementService(db).statement(ee_org['id'], contact['id'], date_from=first.isoformat(),
                                            date_to=end.isoformat(), side=side)
    assert report['opening_balance'] == Decimal('100.00')
    assert report['closing_balance'] == Decimal('110.00')
    assert report['opening_balance'] + sum(r['amount'] for r in report['movements']) == report['closing_balance']
    assert report['eur_opening_balance'] + sum(r['eur_amount'] for r in report['movements']) == report['eur_closing_balance']
    assert report['movements'][-1]['balance'] == report['closing_balance']
    assert report['currencies']['EUR']['closing_balance'] == Decimal('80')
    assert report['currencies']['USD']['closing_balance'] == Decimal('36')
    for currency, balances in report['currencies'].items():
        assert balances['opening_balance'] + sum(r['transaction_amount'] for r in report['movements']
                                                 if r['currency'] == currency) == balances['closing_balance']
    pdf = StatementService.pdf(report)
    assert pdf.startswith(b'%PDF') and len(pdf) > 1000


def test_opening_items_and_tenant_contact_isolation(db, ee_org, uk_org, statement_data):
    docs, contact, accounts, start = statement_data
    OpeningBalanceService(db).post_open_items(ee_org['id'], posting_date=start.isoformat(), actor='owner@example.test',
        rows=[dict(type='customer', name=contact['name'], original_number='OLD-1',
                   original_date=start.isoformat(), due_date=start.isoformat(), amount='120.25')])
    other = docs.create_contact(ee_org['id'], name='Other contact', country_code='EE')
    post(db, ee_org, other, accounts, start, '900')
    # Even a foreign tenant posting with this contact tag must be excluded.
    foreign_accounts = {r['system_role']: r['id'] for r in db.rows(
        'SELECT * FROM accounts WHERE organisation_id=?', (uk_org['id'],))}
    post(db, uk_org, contact, foreign_accounts, start, '700')
    post(db, ee_org, contact, accounts, start, '60', side='supplier')
    service = StatementService(db)
    report = service.statement(ee_org['id'], contact['id'], date_from=(start+timedelta(days=1)).isoformat(),
                               date_to=(start+timedelta(days=1)).isoformat())
    assert report['opening_balance'] == report['closing_balance'] == Decimal('120.25')
    assert report['movements'] == []
    same_day = service.statement(ee_org['id'], contact['id'], date_from=start.isoformat(), date_to=start.isoformat())
    assert same_day['opening_balance'] == 0
    assert same_day['movements'][0]['description'].startswith('Opening: OLD-1')
    with pytest.raises(KeyError, match='Contact not found'):
        service.statement(uk_org['id'], other['id'], date_from=start.isoformat(), date_to=start.isoformat(), eur_rate='1.2')


def test_real_invoice_bill_and_payment_movements(db, ee_org, statement_data):
    docs, contact, accounts, start = statement_data
    day = start.isoformat()
    invoice = docs.create_invoice(ee_org['id'], contact_id=contact['id'], issue_date=day, actor='owner@example.test',
        lines=[dict(description='Synthetic service', quantity=1, unit_price='100', account_id=accounts['SALES'])])
    invoice = docs.issue_invoice(invoice['id'], actor='owner@example.test')
    bill = docs.create_bill(ee_org['id'], contact_id=contact['id'], bill_date=day, due_date=day,
        supplier_number='SUP-1', actor='owner@example.test',
        lines=[dict(description='Synthetic purchase', quantity=1, unit_price='80', account_id=accounts['EXPENSE'])])
    bill = docs.approve_bill(bill['id'], actor='owner@example.test')
    bank = docs.create_bank_account(ee_org['id'], name='Synthetic bank', currency='EUR')
    for side, document, amount in [('customer', invoice, '40'), ('supplier', bill, '30')]:
        docs.record_payment(ee_org['id'], payment_type='customer_receipt' if side == 'customer' else 'supplier_payment',
            bank_account_id=bank['id'], payment_date=day, amount=amount, contact_id=contact['id'],
            actor='owner@example.test', reference='PAY-TEST', allocations=[dict(document_id=document['id'], amount=amount)])
        report = StatementService(db).statement(ee_org['id'], contact['id'], date_from=day, date_to=day, side=side)
        assert report['closing_balance'] == Decimal('60' if side == 'customer' else '50')
        assert len(report['movements']) == 2
        assert {r['document_number'] for r in report['movements']} == {
            invoice['number'] if side == 'customer' else 'SUP-1', 'PAY-TEST'}


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_prepayment_allocation_statement_and_ageing(db, ee_org, statement_data, side):
    docs, contact, accounts, start = statement_data
    day, next_day = start.isoformat(), (start+timedelta(days=1)).isoformat()
    service = PrepaymentService(db)
    bank = docs.create_bank_account(ee_org['id'], name='Synthetic prepayment bank', currency='EUR')
    prepayment = service.create(ee_org['id'], side=side, contact_id=contact['id'], bank_account_id=bank['id'],
        document_date=day, amount='120', idempotency_key='create', actor='owner@example.test')
    # Unallocated money is outside AR/AP and does not create a trade statement movement.
    statements = StatementService(db)
    assert statements.statement(ee_org['id'], contact['id'], date_from=day, date_to=day, side=side)['closing_balance'] == 0
    if side == 'customer':
        document = docs.create_invoice(ee_org['id'], contact_id=contact['id'], issue_date=day, due_date=day,
            actor='owner@example.test', lines=[dict(unit_price='100', account_id=accounts['SALES'])])
        document = docs.issue_invoice(document['id'], actor='owner@example.test')
        ageing = LedgerService(db).receivables_aging
    else:
        document = docs.create_bill(ee_org['id'], contact_id=contact['id'], bill_date=day, due_date=day,
            supplier_number='PRE-SUP', actor='owner@example.test',
            lines=[dict(unit_price='100', account_id=accounts['EXPENSE'])])
        document = docs.approve_bill(document['id'], actor='owner@example.test')
        ageing = LedgerService(db).payables_aging
    allocation = dict(document_type='invoice' if side == 'customer' else 'bill', document_id=document['id'],
        amount='40', allocation_date=next_day, actor='owner@example.test', idempotency_key='allocate')
    service.allocate(ee_org['id'], prepayment['id'], **allocation)
    before = statements.statement(ee_org['id'], contact['id'], date_from=day, date_to=day, side=side)
    assert before['closing_balance'] == 100 and len(before['movements']) == 1
    report = statements.statement(ee_org['id'], contact['id'], date_from=next_day, date_to=next_day, side=side)
    assert report['opening_balance'] == 100 and report['closing_balance'] == 60
    assert len(report['movements']) == 1
    assert report['movements'][0]['voucher_type'] == 'prepayment_allocation'
    assert report['movements'][0]['amount'] == -40
    assert report['currencies']['EUR']['closing_balance'] == ageing(ee_org['id'], as_at=next_day)['total'] == 60
    # Refunding the remaining prepayment has no AR/AP effect.
    service.refund(ee_org['id'], prepayment['id'], refund_date=next_day, amount='20',
        idempotency_key='refund', actor='owner@example.test')
    assert statements.statement(ee_org['id'], contact['id'], date_from=next_day, date_to=next_day, side=side) == report
    service.allocate(ee_org['id'], prepayment['id'], **{**allocation, 'amount': '60', 'idempotency_key': 'allocate-2'})
    final = statements.statement(ee_org['id'], contact['id'], date_from=day, date_to=next_day, side=side)
    assert final['closing_balance'] == ageing(ee_org['id'], as_at=next_day)['total'] == 0
    assert ageing(ee_org['id'], as_at=next_day)['items'] == []


def test_eur_conversion_is_explicit_and_rounds_per_movement(db, uk_org):
    docs = DocumentService(db)
    contact = docs.create_contact(uk_org['id'], name='Synthetic UK', country_code='GB')
    accounts = {r['system_role']: r['id'] for r in db.rows('SELECT * FROM accounts WHERE organisation_id=?', (uk_org['id'],))}
    start = date.fromisoformat(db.scalar('SELECT starts_on FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1', (uk_org['id'],)))
    post(db, uk_org, contact, accounts, start, '10.01', currency='GBP')
    service = StatementService(db)
    args = dict(date_from=start.isoformat(), date_to=start.isoformat())
    for rate in [None, '0', '-1', 'NaN', 'Infinity', 'invalid']:
        with pytest.raises(ValueError):
            service.statement(uk_org['id'], contact['id'], eur_rate=rate, **args)
    report = service.statement(uk_org['id'], contact['id'], eur_rate='1.12345', **args)
    assert report['closing_balance'] == Decimal('10.01')
    assert report['eur_closing_balance'] == Decimal('11.25')
    assert report['currencies']['GBP']['closing_balance'] == Decimal('10.01')
    assert StatementService.pdf(report).startswith(b'%PDF')


def test_empty_statement_pdf(db, ee_org, statement_data):
    contact, day = statement_data[1], statement_data[3].isoformat()
    report = StatementService(db).statement(ee_org['id'], contact['id'], date_from=day, date_to=day)
    assert report['opening_balance'] == report['closing_balance'] == 0
    assert report['currencies'] == {} and report['movements'] == []
    assert len(StatementService.pdf(report)) > 1000


@pytest.mark.parametrize('dates,side', [(('bad', '2026-01-01'), 'customer'),
    (('2026-01-02', '2026-01-01'), 'customer'), (('2026-01-01', '2026-01-01'), 'invalid')])
def test_invalid_ranges_and_side(db, ee_org, statement_data, dates, side):
    contact = statement_data[1]
    with pytest.raises(ValueError):
        StatementService(db).statement(ee_org['id'], contact['id'], date_from=dates[0], date_to=dates[1], side=side)


def test_statement_api_and_mounted_web_download(db, ee_org, uk_org, statement_data, monkeypatch):
    from api_app import api
    from web_app import app
    docs, contact, accounts, start = statement_data
    post(db, ee_org, contact, accounts, start, '100')
    other = docs.create_contact(uk_org['id'], name='Foreign contact', country_code='GB')
    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    reset_database_cache()
    path = f"/organisations/{ee_org['id']}/contacts/{contact['id']}/statement"
    query = dict(date_from=start.isoformat(), date_to=start.isoformat())
    try:
        with TestClient(api, headers={'X-Test-User': 'owner@example.test'}) as client:
            response = client.get(path, params=query)
            assert response.status_code == 200
            assert response.json()['closing_balance'] == '100.00'
            foreign = client.get(path.replace(contact['id'], other['id']), params=query)
            assert foreign.status_code == 404
            assert client.get(path, params={**query, 'date_from': 'bad'}).status_code == 422
        with TestClient(api, headers={'X-Test-User': 'outsider@example.test'}) as client:
            for suffix in ['', '.pdf']:
                assert client.get(path+suffix, params=query).status_code == 403
        # web_app mounts the same authorised API for workspace download buttons.
        with TestClient(app, headers={'X-Test-User': 'owner@example.test'}) as client:
            response = client.get('/api'+path+'.pdf', params=query)
            assert response.status_code == 200
            assert response.content.startswith(b'%PDF')
            assert response.headers['content-type'] == 'application/pdf'
            assert 'attachment; filename="statement-' in response.headers['content-disposition']
    finally:
        reset_database_cache()
