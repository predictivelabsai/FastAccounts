"""Offline realised FX, exact settlement and transit clearing acceptance checks."""
from decimal import Decimal
from pathlib import Path
import socket

import pytest

from core_utils import decimal, money
from documents import DocumentService
from exchange_rates import ExchangeRateService
from ledger import LedgerService, PostingLine
from organisations import OrganisationService
from periodisation import PeriodisationService
from prepayments import PrepaymentService
from test_bulk_sending import ACTOR


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Live network is forbidden')
    monkeypatch.setattr(socket.socket, 'connect', blocked)


def setup(db, org, side='customer', currency='USD'):
    docs = DocumentService(db)
    contact = docs.create_contact(org['id'], name='Synthetic FX contact', contact_type='both', country_code=org['country_code'])
    bank = docs.create_bank_account(org['id'], name='Synthetic FX bank', currency=currency)
    accounts = {r['system_role']: r['id'] for r in db.rows(
        'SELECT * FROM accounts WHERE organisation_id=?', (org['id'],))}
    return docs, contact, bank, accounts


def document(db, org, data, *, side='customer', rate='1.1', currency='USD', amount='100', posted=True):
    docs, contact, bank, accounts = data
    args = dict(contact_id=contact['id'], currency=currency, exchange_rate=Decimal(rate), actor=ACTOR,
                lines=[dict(account_id=accounts['SALES' if side == 'customer' else 'EXPENSE'], unit_price=amount)])
    if side == 'customer':
        row = docs.create_invoice(org['id'], issue_date='2026-01-10', **args)
        return docs.issue_invoice(row['id'], actor=ACTOR) if posted else row
    row = docs.create_bill(org['id'], bill_date='2026-01-10', due_date='2026-01-10',
                           supplier_number='SYN-' + str(db.scalar('SELECT COUNT(*) FROM bills WHERE organisation_id=?', (org['id'],))), **args)
    return docs.approve_bill(row['id'], actor=ACTOR) if posted else row


def pay(org, data, documents, *, side='customer', rate='1.2', amount=None):
    docs, contact, bank, accounts = data
    allocations = [dict(document_id=row['id'], amount=portion) for row, portion in documents]
    return docs.record_payment(org['id'], payment_type='customer_receipt' if side == 'customer' else 'supplier_payment',
        contact_id=contact['id'], bank_account_id=bank['id'], payment_date='2026-01-20',
        amount=amount or sum((decimal(x['amount']) for x in allocations), Decimal('0')),
        allocations=allocations, exchange_rate=Decimal(rate), actor=ACTOR, reference='FX-SYN')


def entries(db, batch_id):
    rows = db.rows('SELECT g.*,a.system_role FROM gl_entries g JOIN accounts a ON a.id=g.account_id '
                   'WHERE g.posting_batch_id=? ORDER BY g.line_number', (batch_id,))
    assert sum((decimal(r['debit']) for r in rows), Decimal('0')) == sum((decimal(r['credit']) for r in rows), Decimal('0'))
    return rows


def balance(db, oid, role):
    rows = db.rows('SELECT g.debit,g.credit FROM gl_entries g JOIN accounts a ON a.id=g.account_id '
                   'WHERE g.organisation_id=? AND a.system_role=?', (oid, role))
    return sum((decimal(r['debit']) - decimal(r['credit']) for r in rows), Decimal('0'))


@pytest.mark.parametrize('side', ['customer', 'supplier'])
@pytest.mark.parametrize('rate,difference', [('1.2', '10'), ('1.0', '-10')])
def test_realised_both_directions(db, ee_org, side, rate, difference):
    data = setup(db, ee_org, side)
    row = document(db, ee_org, data, side=side)
    original = entries(db, row['posting_batch_id'])
    payment = pay(ee_org, data, [(row, '100')], side=side, rate=rate)
    posted = entries(db, payment['posting_batch_id'])
    assert len(posted) == 3
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0
    assert balance(db, ee_org['id'], 'FX_GAIN_LOSS') == Decimal(difference) * (-1 if side == 'customer' else 1)
    assert entries(db, row['posting_batch_id']) == original


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_mixed_rates_and_unallocated_remainder(db, ee_org, side):
    data = setup(db, ee_org, side)
    first = document(db, ee_org, data, side=side, rate='1.1', amount='10')
    second = document(db, ee_org, data, side=side, rate='1.3', amount='20')
    payment = pay(ee_org, data, [(first, '10'), (second, '20')], side=side, rate='1.2', amount='35')
    rows = entries(db, payment['posting_batch_id'])
    control = next(r for r in rows if r['system_role'] == ('AR' if side == 'customer' else 'AP'))
    assert decimal(control['credit' if side == 'customer' else 'debit']) == Decimal('43')
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == Decimal('6') * (-1 if side == 'customer' else 1)
    assert len(rows) == 3


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_partial_cents_clear_exactly(db, ee_org, side):
    data = setup(db, ee_org, side)
    row = document(db, ee_org, data, side=side, rate='1.3333333333', amount='0.03')
    for portion in ['0.01', '0.01', '0.01']:
        payment = pay(ee_org, data, [(row, portion)], side=side, rate='2')
        entries(db, payment['posting_batch_id'])
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0


@pytest.mark.parametrize('side', ['customer', 'supplier'])
@pytest.mark.parametrize('total,first_rate', [('0.02', '1.5'), ('0.03', '1.5'), ('0.02', '2')])
def test_final_equal_rate_rounding_exception_clears_actual_remaining(db, ee_org, side, total, first_rate):
    data = setup(db, ee_org, side)
    row = document(db, ee_org, data, side=side, rate='1.5', amount=total)
    first = pay(ee_org, data, [(row, '0.01')], side=side, rate=first_rate)
    entries(db, first['posting_batch_id'])
    if total == '0.03':
        middle = pay(ee_org, data, [(row, '0.01')], side=side, rate='1.5')
        assert len(entries(db, middle['posting_batch_id'])) == 2
    final = pay(ee_org, data, [(row, '0.01')], side=side, rate='1.5')
    assert len(entries(db, final['posting_batch_id'])) == 3
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0
    allocation = db.one('SELECT * FROM payment_allocations WHERE payment_id=?', (final['id'],))
    assert decimal(allocation['booked_base_amount']) == Decimal('0.01')


@pytest.mark.parametrize('side', ['customer', 'supplier'])
@pytest.mark.parametrize('legacy_rate', ['1.2', '3'])
def test_legacy_payment_allocation_clears_actual_base(db, ee_org, side, legacy_rate):
    data = setup(db, ee_org, side)
    row = document(db, ee_org, data, side=side)
    legacy = pay(ee_org, data, [], side=side, amount='50', rate=legacy_rate)
    entries(db, legacy['posting_batch_id'])
    kind, table = ('invoice', 'invoices') if side == 'customer' else ('bill', 'bills')
    with db.transaction() as tx:
        tx.execute('INSERT INTO payment_allocations(id,payment_id,document_type,document_id,amount) VALUES (?,?,?,?,?)',
                   ('legacy', legacy['id'], kind, row['id'], '50'))
        tx.execute(f"UPDATE {table} SET paid_total=50,status='Part Paid' WHERE id=? AND organisation_id=?", (row['id'], ee_org['id']))
    final = pay(ee_org, data, [(row, '50')], side=side)
    entries(db, final['posting_batch_id'])
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_equal_rate_multi_document_aggregate_rounding(db, ee_org, side):
    data = setup(db, ee_org, side)
    rows = [document(db, ee_org, data, side=side, rate='1.5', amount='0.01') for _ in range(2)]
    payment = pay(ee_org, data, [(row, '0.01') for row in rows], side=side, rate='1.5')
    assert len(entries(db, payment['posting_batch_id'])) == 3
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_zero_remaining_base_control_has_no_empty_ledger_leg(db, ee_org, side):
    data = setup(db, ee_org, side)
    row = document(db, ee_org, data, side=side, rate='0.5', amount='0.02')
    for _ in range(2):
        payment = pay(ee_org, data, [(row, '0.01')], side=side, rate='1')
        rows = entries(db, payment['posting_batch_id'])
        assert all(decimal(r['debit']) or decimal(r['credit']) for r in rows)
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_multi_document_conversion_rounding_does_not_strand_cents(db, ee_org, side):
    data = setup(db, ee_org, side)
    rows = [document(db, ee_org, data, side=side, rate='2', amount='0.01') for _ in range(2)]
    payment = pay(ee_org, data, [(row, '0.01') for row in rows], side=side, rate='1.5')
    entries(db, payment['posting_batch_id'])
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_actual_booked_entries_take_precedence_over_rate_metadata(db, ee_org, side):
    data = setup(db, ee_org, side)
    row = document(db, ee_org, data, side=side, posted=False)
    accounts = data[3]
    debit, credit = (accounts['AR'], accounts['SALES']) if side == 'customer' else (accounts['EXPENSE'], accounts['AP'])
    kind = 'invoice' if side == 'customer' else 'bill'
    batch = LedgerService(db).post(organisation_id=ee_org['id'], voucher_type=kind, voucher_id=row['id'],
        voucher_code='SYN-LEGACY', posting_date='2026-01-10', currency='USD', exchange_rate=Decimal('1.4'), actor=ACTOR,
        lines=[PostingLine(debit, debit=Decimal('100'), source_line_type=kind, source_line_id=row['id']),
               PostingLine(credit, credit=Decimal('100'), source_line_type=kind, source_line_id=row['id'])])
    table = 'invoices' if side == 'customer' else 'bills'
    with db.transaction() as tx:
        tx.execute(f'UPDATE {table} SET posting_batch_id=?,status=? WHERE id=? AND organisation_id=?',
                   (batch['id'], 'Issued' if side == 'customer' else 'Approved', row['id'], ee_org['id']))
    result = pay(ee_org, data, [(row, '100')], side=side)
    entries(db, result['posting_batch_id'])
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0
    assert balance(db, ee_org['id'], 'FX_GAIN_LOSS') == Decimal('20') * (1 if side == 'customer' else -1)


@pytest.mark.parametrize('side', ['customer', 'supplier'])
@pytest.mark.parametrize('bank_currency,doc_currency', [('EUR', 'USD'), ('USD', 'EUR')])
def test_payment_effective_rates_across_base_currency(db, ee_org, side, bank_currency, doc_currency):
    data = setup(db, ee_org, side, currency=bank_currency)
    row = document(db, ee_org, data, side=side, currency=doc_currency, rate='1.1' if doc_currency == 'USD' else '9')
    payment = pay(ee_org, data, [(row, '100')], side=side, rate='1.2' if bank_currency == 'USD' else '8')
    entries(db, payment['posting_batch_id'])
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0
    diff = Decimal('20') if bank_currency == 'USD' else Decimal('-10')
    assert balance(db, ee_org['id'], 'FX_GAIN_LOSS') == diff * (-1 if side == 'customer' else 1)


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_mixed_rate_net_zero_has_no_fx_line(db, ee_org, side):
    data = setup(db, ee_org, side)
    rows = [document(db, ee_org, data, side=side, rate=rate) for rate in ['1.1', '1.3']]
    payment = pay(ee_org, data, [(row, '100') for row in rows], side=side)
    assert len(entries(db, payment['posting_batch_id'])) == 2
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0


def signature(db, row):
    return [(r['system_role'], r['debit'], r['credit'], r['currency'], r['transaction_amount'],
             r['transaction_currency'], r['exchange_rate'], r['memo'], r['due_date'], r['source_line_type'])
            for r in entries(db, row['posting_batch_id'])]


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_rate_one_bit_identical_to_fx_free_org(db, ee_org, side):
    other = OrganisationService(db).create(name='Synthetic no FX', country_code='EE', entity_type='EE_OU', owner_email=ACTOR)
    ExchangeRateService(db).create(ee_org['id'], rate_date='2026-01-01', from_currency='USD', to_currency='EUR', rate='9', actor=ACTOR)
    results = []
    for org in [ee_org, other]:
        data = setup(db, org, side, currency='EUR')
        # An explicit non-1 stored document rate never converts a base line.
        row = document(db, org, data, side=side, rate='7', currency='EUR')
        results.append(signature(db, pay(org, data, [(row, '100')], side=side, rate='1')))
    assert results[0] == results[1] and len(results[0]) == 2


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_equal_foreign_rates_keep_original_aggregates(db, ee_org, side):
    data = setup(db, ee_org, side)
    row = document(db, ee_org, data, side=side, rate='1.2')
    result = entries(db, pay(ee_org, data, [(row, '100')], side=side)['posting_batch_id'])
    assert len(result) == 2
    assert all(decimal(r['debit']) + decimal(r['credit']) == 120 for r in result)
    assert all(r['transaction_currency'] == 'USD' and abs(decimal(r['transaction_amount'])) == 100 for r in result)


@pytest.mark.parametrize('failure', ['rate', 'balance', 'allocation'])
def test_payment_atomicity(db, ee_org, monkeypatch, failure):
    data = setup(db, ee_org)
    row = document(db, ee_org, data)
    before = {table: db.rows(f'SELECT * FROM {table} ORDER BY id') for table in
              ['payments', 'payment_allocations', 'posting_batches', 'gl_entries', 'audit_events', 'invoices']}
    if failure == 'balance':
        original = LedgerService.post
        def unbalanced(self, **kwargs):
            kwargs['lines'] = kwargs['lines'][:-1]
            return original(self, **kwargs)
        monkeypatch.setattr(LedgerService, 'post', unbalanced)
    with pytest.raises(ValueError):
        pay(ee_org, data, [(row, '101' if failure == 'allocation' else '100')], rate='0' if failure == 'rate' else '1.2')
    for table, rows in before.items():
        assert db.rows(f'SELECT * FROM {table} ORDER BY id') == rows


def prepay(db, org, data, *, side='customer', rate='1.1', amount='100'):
    docs, contact, bank, accounts = data
    if bank['currency'] != org['base_currency']:
        ExchangeRateService(db).create(org['id'], rate_date='2026-01-01', from_currency=bank['currency'],
                                      to_currency=org['base_currency'], rate=rate, actor=ACTOR)
    return PrepaymentService(db).create(org['id'], side=side, contact_id=contact['id'], bank_account_id=bank['id'],
        document_date='2026-01-10', amount=amount, idempotency_key='pre', actor=ACTOR)


@pytest.mark.parametrize('side', ['customer', 'supplier'])
@pytest.mark.parametrize('pre_currency,doc_currency', [('USD', 'USD'), ('USD', 'EUR'), ('EUR', 'USD')])
def test_prepayment_creation_allocation_cross_currency(db, ee_org, side, pre_currency, doc_currency):
    data = setup(db, ee_org, side, currency=pre_currency)
    pre = prepay(db, ee_org, data, side=side)
    assert decimal(pre['exchange_rate']) == (Decimal('1.1') if pre_currency == 'USD' else 1)
    entries(db, pre['posting_batch_id'])
    row = document(db, ee_org, data, side=side, rate='1.2', currency=doc_currency)
    result = PrepaymentService(db).allocate(ee_org['id'], pre['id'], document_type='invoice' if side == 'customer' else 'bill',
        document_id=row['id'], allocation_date='2026-01-20', amount='100', idempotency_key='allocate', actor=ACTOR)
    assert len(entries(db, result['posting_batch_id'])) == 3
    assert balance(db, ee_org['id'], 'CUSTOMER_PREPAYMENTS' if side == 'customer' else 'SUPPLIER_PREPAYMENTS') == 0
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0
    pre_base = Decimal('110') if pre_currency == 'USD' else Decimal('100')
    doc_base = Decimal('120') if doc_currency == 'USD' else Decimal('100')
    assert balance(db, ee_org['id'], 'FX_GAIN_LOSS') == (doc_base - pre_base) * (1 if side == 'customer' else -1)


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_prepayment_equal_rates_bit_identical(db, ee_org, side):
    other = OrganisationService(db).create(name='Synthetic no rates', country_code='EE', entity_type='EE_OU', owner_email=ACTOR)
    ExchangeRateService(db).create(ee_org['id'], rate_date='2026-01-01', from_currency='USD', to_currency='EUR', rate='9', actor=ACTOR)
    results = []
    for org in [ee_org, other]:
        data = setup(db, org, side, currency='EUR')
        pre = prepay(db, org, data, side=side)
        row = document(db, org, data, side=side, rate='7', currency='EUR')
        allocation = PrepaymentService(db).allocate(org['id'], pre['id'], document_type='invoice' if side == 'customer' else 'bill',
            document_id=row['id'], allocation_date='2026-01-20', amount='100', idempotency_key='alloc', actor=ACTOR)
        results.append(signature(db, allocation))
    assert results[0] == results[1] and len(results[0]) == 2


@pytest.mark.parametrize('side', ['customer', 'supplier'])
@pytest.mark.parametrize('rate', ['1.2', '1', '1.1'])
def test_refund_fx_and_original_links(db, ee_org, side, rate):
    data = setup(db, ee_org, side)
    pre = prepay(db, ee_org, data, side=side)
    original = entries(db, pre['posting_batch_id'])
    ExchangeRateService(db).create(ee_org['id'], rate_date='2026-01-20', from_currency='USD', to_currency='EUR', rate=rate, actor=ACTOR)
    result = PrepaymentService(db).refund(ee_org['id'], pre['id'], refund_date='2026-01-20', amount='100', idempotency_key='refund', actor=ACTOR)
    rows = entries(db, result['posting_batch_id'])
    assert len(rows) == (2 if rate == '1.1' else 3)
    assert {r['reverses_entry_id'] for r in rows if r['system_role'] != 'FX_GAIN_LOSS'} == {r['id'] for r in original}
    assert balance(db, ee_org['id'], 'CUSTOMER_PREPAYMENTS' if side == 'customer' else 'SUPPLIER_PREPAYMENTS') == 0
    assert balance(db, ee_org['id'], 'FX_GAIN_LOSS') == (Decimal(rate) - Decimal('1.1')) * 100 * (1 if side == 'customer' else -1)
    assert entries(db, pre['posting_batch_id']) == original


@pytest.mark.parametrize('side', ['customer', 'supplier'])
def test_allocation_then_refunds_consume_booked_cents(db, ee_org, side):
    data = setup(db, ee_org, side)
    pre = prepay(db, ee_org, data, side=side, rate='1.3333333333', amount='0.03')
    row = document(db, ee_org, data, side=side, rate='2', amount='0.01')
    service = PrepaymentService(db)
    allocation = service.allocate(ee_org['id'], pre['id'], document_type='invoice' if side == 'customer' else 'bill',
        document_id=row['id'], allocation_date='2026-01-20', amount='0.01', idempotency_key='alloc', actor=ACTOR)
    entries(db, allocation['posting_batch_id'])
    ExchangeRateService(db).create(ee_org['id'], rate_date='2026-01-20', from_currency='USD', to_currency='EUR', rate='2', actor=ACTOR)
    for key in ['refund1', 'refund2']:
        refund = service.refund(ee_org['id'], pre['id'], refund_date='2026-01-20', amount='0.01', idempotency_key=key, actor=ACTOR)
        entries(db, refund['posting_batch_id'])
    assert balance(db, ee_org['id'], 'CUSTOMER_PREPAYMENTS' if side == 'customer' else 'SUPPLIER_PREPAYMENTS') == 0
    assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0
    assert service.get(ee_org['id'], pre['id'])['unallocated_balance'] == 0


@pytest.mark.parametrize('side', ['customer', 'supplier'])
@pytest.mark.parametrize('event', ['allocation', 'refund'])
def test_prepayment_equal_rate_final_cents(db, ee_org, side, event):
    data = setup(db, ee_org, side)
    pre = prepay(db, ee_org, data, side=side, rate='1.5', amount='0.02')
    service = PrepaymentService(db)
    row = document(db, ee_org, data, side=side, rate='1.5', amount='0.02') if event == 'allocation' else None
    for key in ['first', 'last']:
        if row:
            result = service.allocate(ee_org['id'], pre['id'], document_type='invoice' if side == 'customer' else 'bill',
                document_id=row['id'], allocation_date='2026-01-20', amount='0.01', idempotency_key=key, actor=ACTOR)
        else:
            result = service.refund(ee_org['id'], pre['id'], refund_date='2026-01-20', amount='0.01', idempotency_key=key, actor=ACTOR)
        entries(db, result['posting_batch_id'])
    assert balance(db, ee_org['id'], 'CUSTOMER_PREPAYMENTS' if side == 'customer' else 'SUPPLIER_PREPAYMENTS') == 0
    if row:
        assert balance(db, ee_org['id'], 'AR' if side == 'customer' else 'AP') == 0


@pytest.mark.parametrize('posted', [False, True])
@pytest.mark.parametrize('split', ['equal_first', 'equal_last'])
def test_periodisation_fx_cents_clear_transit(db, ee_org, posted, split):
    data = setup(db, ee_org, 'supplier')
    row = document(db, ee_org, data, side='supplier', rate='1.3333333333', amount='100.01', posted=posted)
    service = PeriodisationService(db)
    schedule = service.create(ee_org['id'], bill_id=row['id'], expense_account_id=data[3]['EXPENSE'],
        start_period='2026-01-10', number_of_periods=3, split_rule=split, actor=ACTOR)
    if not posted:
        data[0].approve_bill(row['id'], actor=ACTOR)
    result = service.post_due(ee_org['id'], schedule['id'], as_at='2026-10-01', actor=ACTOR)
    assert result['status'] == 'Completed'
    assert balance(db, ee_org['id'], 'PERIODISED_PURCHASES') == 0
    for period in result['periods']:
        rows = entries(db, period['posted_journal_id'])
        assert all(decimal(r['exchange_rate']) == Decimal('1.3333333333') for r in rows)


@pytest.mark.parametrize('currency,rate', [('USD', '1.25'), ('EUR', '7')])
def test_periodisation_effective_rate_and_vat(db, ee_org, currency, rate):
    data = setup(db, ee_org, 'supplier')
    tax = db.scalar("SELECT id FROM tax_codes WHERE organisation_id=? AND code='EE24'", (ee_org['id'],))
    bill = data[0].create_bill(ee_org['id'], contact_id=data[1]['id'], supplier_number='SYN-VAT',
        bill_date='2026-01-10', due_date='2026-01-10', actor=ACTOR, currency=currency, exchange_rate=Decimal(rate),
        lines=[dict(account_id=data[3]['EXPENSE'], unit_price='100.01', tax_code_id=tax)])
    service = PeriodisationService(db)
    schedule = service.create(ee_org['id'], bill_id=bill['id'], expense_account_id=data[3]['EXPENSE'],
        start_period='2026-01-10', number_of_periods=3, actor=ACTOR)
    approved = data[0].approve_bill(bill['id'], actor=ACTOR)
    original = entries(db, approved['posting_batch_id'])
    vat = balance(db, ee_org['id'], 'INPUT_VAT')
    assert vat == (Decimal('30') if currency == 'USD' else Decimal('24'))
    result = service.post_due(ee_org['id'], schedule['id'], as_at='2026-10-01', actor=ACTOR)
    assert balance(db, ee_org['id'], 'PERIODISED_PURCHASES') == 0
    assert balance(db, ee_org['id'], 'INPUT_VAT') == vat
    assert entries(db, approved['posting_batch_id']) == original
    for period in result['periods']:
        assert all(decimal(r['exchange_rate']) == (Decimal(rate) if currency == 'USD' else 1)
                   for r in entries(db, period['posted_journal_id']))


@pytest.mark.parametrize('country,preferred', [('UK', 7900), ('EE', 6990)])
@pytest.mark.parametrize('existing', [False, True])
def test_migration_role_seeding_and_wiring(tmp_path, monkeypatch, country, preferred, existing):
    import organisations
    import database
    from database import Database
    import shutil
    root = Path(__file__).resolve().parents[1]
    directory = tmp_path / 'migrations' / 'sqlite'
    directory.mkdir(parents=True)
    for path in (root / 'migrations/sqlite').glob('*.sql'):
        if path.name < '0025':
            shutil.copyfile(path, directory / path.name)
    db = Database(path=str(tmp_path / 'legacy.sqlite'))
    original = database.MIGRATIONS
    monkeypatch.setattr(database, 'MIGRATIONS', directory.parent)
    db.migrate()
    for chart in ['UK_ACCOUNTS', 'EE_ACCOUNTS']:
        monkeypatch.setattr(organisations, chart, tuple(r for r in getattr(organisations, chart) if r[4] != 'FX_GAIN_LOSS'))
    org = OrganisationService(db).create(name='Synthetic legacy chart', country_code=country,
        entity_type='UK_COMPANY' if country == 'UK' else 'EE_OU', owner_email=ACTOR)
    with db.transaction() as tx:
        tx.execute("INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) "
                   "VALUES ('custom',?,?, 'Synthetic existing', 'Expense','Debit',?)",
                   (org['id'], str(preferred), 'FX_GAIN_LOSS' if existing else None))
    monkeypatch.setattr(database, 'MIGRATIONS', original)
    assert db.migrate() == ['0025_fx_realised', '0026_fx_revaluations', '0027_mfa', '0028_document_settings', '0029_copilot', '0030_master_data_maintenance']
    assert db.migrate() == []
    assert db.scalar('SELECT COUNT(*) FROM schema_migrations') == 30
    role = db.one("SELECT * FROM accounts WHERE organisation_id=? AND system_role='FX_GAIN_LOSS'", (org['id'],))
    assert role['code'] == str(preferred if existing else preferred + 1)
    sql = (root / 'migrations/sqlite/0025_fx_realised.sql').read_text(encoding='utf-8')
    with db.transaction() as tx:
        tx.execute(sql[sql.index('WITH RECURSIVE'):])
    assert db.scalar("SELECT COUNT(*) FROM accounts WHERE organisation_id=? AND system_role='FX_GAIN_LOSS'", (org['id'],)) == 1
    assert "'0024_reminder_rules', '0025_fx_realised', '0026_fx_revaluations', '0027_mfa', '0028_document_settings', '0029_copilot', '0030_master_data_maintenance']" in (root / '.github/workflows/ci.yml').read_text(encoding='utf-8')
