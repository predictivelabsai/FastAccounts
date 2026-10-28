"""Synthetic cash-flow arithmetic, classification and read-only boundaries."""
from contextlib import contextmanager
from decimal import Decimal

import pytest

from cash_flow import CashFlowService
from core_utils import new_id
from documents import DocumentService
from ledger import LedgerService, PostingLine


@pytest.fixture
def books(db, ee_org):
    org = ee_org['id']
    with db.transaction() as tx:
        tx.execute("INSERT INTO fiscal_periods(id,organisation_id,code,starts_on,ends_on) "
                   "VALUES (?,?,'cash-flow-fixture','2023-01-01','2025-12-31')", (new_id(), org))
    accounts = {r['system_role']: r['id'] for r in db.rows('SELECT * FROM accounts WHERE organisation_id=?', (org,))}
    return org, accounts


def post(db, org, accounts, day, key, lines):
    return LedgerService(db).post(organisation_id=org, posting_date=day, voucher_type='journal',
        voucher_id=key, voucher_code=key, actor='owner@example.test',
        currency=db.scalar('SELECT base_currency FROM organisations WHERE id=?', (org,)),
        lines=[PostingLine(accounts[role], debit=Decimal(debit), credit=Decimal(credit),
                           memo=memo, contact_id=contact) for role, debit, credit, memo, contact in lines])


def movement(db, org, accounts, day, key, role, amount, inflow=True, contact=None):
    return post(db, org, accounts, day, key, [
        ('BANK', amount if inflow else '0', '0' if inflow else amount, key, contact),
        (role, '0' if inflow else amount, amount if inflow else '0', key, contact)])


def assert_balanced(report):
    assert report['opening_balance'] + report['inflows'] - report['outflows'] == report['closing_balance']
    assert sum((v['net'] for v in report['buckets'].values()), Decimal('0')) == report['closing_balance'] - report['opening_balance']
    for account in report['accounts']:
        assert account['opening_balance'] + sum((x['amount'] for x in account['movements']), Decimal('0')) == account['closing_balance']
        for line in account['movements']:
            assert sum(line['allocations'].values()) == abs(line['amount'])


def test_opening_end_boundaries_statuses_tenant_and_read_only(db, ee_org, uk_org, books):
    org, accounts = books
    contact = DocumentService(db).create_contact(org, name='Synthetic customer', country_code='EE')
    movement(db, org, accounts, '2024-01-31', 'opening', 'CAPITAL', '100')
    receipt = movement(db, org, accounts, '2024-02-01', 'receipt', 'AR', '20', contact=contact['id'])
    movement(db, org, accounts, '2024-02-29', 'supplier', 'AP', '7', False)
    movement(db, org, accounts, '2024-03-01', 'after', 'SALES', '99')
    LedgerService(db).reverse(receipt['id'], reversal_date='2024-03-01', actor='owner@example.test')
    excluded = movement(db, org, accounts, '2024-02-10', 'excluded', 'CAPITAL', '50')
    with db.transaction() as tx:
        tx.execute("UPDATE posting_batches SET status='Draft' WHERE id=?", (excluded['id'],))
    snapshot = db.rows('SELECT * FROM gl_entries ORDER BY id')
    audit = db.rows('SELECT * FROM audit_events ORDER BY id')
    report = CashFlowService(db).statement(org, date_from='2024-02-01', date_to='2024-02-29')
    assert report['opening_balance'] == 100
    assert report['closing_balance'] == 113
    assert report['buckets']['receipts']['inflows'] == 20
    assert report['buckets']['supplier_payments']['outflows'] == 7
    assert report['accounts'][0]['movements'][0]['contact_id'] == contact['id']
    assert report['base_currency'] == 'EUR'
    assert_balanced(report)
    other = CashFlowService(db).statement(uk_org['id'], date_from='2024-02-01', date_to='2024-02-29')
    assert other['opening_balance'] == other['closing_balance'] == other['inflows'] == other['outflows'] == 0
    assert other['base_currency'] == 'GBP'
    assert db.rows('SELECT * FROM gl_entries ORDER BY id') == snapshot
    assert db.rows('SELECT * FROM audit_events ORDER BY id') == audit
    reversed_report = CashFlowService(db).statement(org, date_from='2024-02-01', date_to='2024-03-01')
    assert reversed_report['buckets']['receipts']['outflows'] == 20
    assert_balanced(reversed_report)


@pytest.mark.parametrize('role,bucket', [('AR', 'receipts'), ('AP', 'supplier_payments'),
    ('PAYROLL_NET', 'payroll'), ('PAYROLL_SALARY', 'payroll'), ('PAYROLL_SOCIAL', 'payroll'),
    ('PAYROLL_UI', 'payroll'), ('PAYROLL_INCOME_TAX', 'payroll'), ('PAYROLL_WITHHOLDING', 'payroll'),
    ('PAYROLL_EMPLOYER_TAX', 'payroll'), ('OUTPUT_VAT', 'vat'), ('INPUT_VAT', 'vat'),
    ('SALES', 'revenue'), ('EXPENSE', 'expenses'), ('CAPITAL', 'financing'),
    ('RETAINED_EARNINGS', 'financing'), ('FIXED_ASSETS', 'other')])
def test_classification_both_directions(db, books, role, bucket):
    org, accounts = books
    movement(db, org, accounts, '2024-02-01', 'in', role, '12.34')
    movement(db, org, accounts, '2024-02-02', 'out', role, '5.67', False)
    report = CashFlowService(db).statement(org, date_from='2024-02-01', date_to='2024-02-29')
    assert report['buckets'][bucket] == {'inflows': Decimal('12.34'), 'outflows': Decimal('5.67'), 'net': Decimal('6.67')}
    assert report['accounts'][0]['movements'][1]['memo'] == 'out'
    assert_balanced(report)


def test_split_contra_and_non_cash_lines_allocate_exact_cents(db, books):
    org, accounts = books
    post(db, org, accounts, '2024-02-01', 'split', [
        ('BANK', '10.01', '0', 'Split receipt', None), ('EXPENSE', '9.99', '0', 'Non-cash debit', None),
        ('AR', '0', '10', '', None), ('SALES', '0', '10', '', None)])
    report = CashFlowService(db).statement(org, date_from='2024-02-01', date_to='2024-02-01')
    assert report['buckets']['receipts']['inflows'] == Decimal('5.01')
    assert report['buckets']['revenue']['inflows'] == Decimal('5.00')
    assert report['inflows'] == Decimal('10.01')
    assert_balanced(report)


def test_internal_lines_net_and_remain_in_detail(db, books):
    org, accounts = books
    post(db, org, accounts, '2024-02-01', 'internal', [
        ('BANK', '30', '0', 'Transfer in', None), ('BANK', '0', '20', 'Transfer out', None),
        ('CAPITAL', '0', '10', '', None)])
    report = CashFlowService(db).statement(org, date_from='2024-02-01', date_to='2024-02-01')
    assert report['buckets']['internal'] == {'inflows': 20, 'outflows': 20, 'net': 0}
    assert report['inflows'] == 10 and report['outflows'] == 0
    assert len(report['accounts'][0]['movements']) == 2
    assert_balanced(report)


def test_transfer_between_distinct_liquid_accounts_snapshot(db, books):
    """Multiple BANK roles cannot be stored by today's unique-role schema.

    A read-only projection supplies two liquid accounts to exercise the report's
    multi-account behaviour without changing production schema or account roles.
    """
    org, accounts = books
    bank = DocumentService(db).create_bank_account(org, name='Synthetic second bank', currency='EUR')
    accounts['SECOND'] = bank['ledger_account_id']
    post(db, org, accounts, '2024-02-01', 'transfer', [
        ('SECOND', '25', '0', 'Transfer in', None), ('BANK', '0', '25', 'Transfer out', None)])

    class Projection:
        @contextmanager
        def transaction(self):
            with db.transaction() as tx:
                class ReadOnly:
                    one = tx.one

                    def rows(self, sql, params):
                        rows = tx.rows(sql, params)
                        if 'FROM accounts WHERE' in sql:
                            rows.append(tx.one('SELECT id,code,name FROM accounts WHERE id=? AND organisation_id=?', (accounts['SECOND'], org)))
                        return rows
                yield ReadOnly()

    report = CashFlowService(Projection()).statement(org, date_from='2024-02-01', date_to='2024-02-01')
    assert report['inflows'] == report['outflows'] == report['closing_balance'] == 0
    assert report['buckets']['internal']['inflows'] == report['buckets']['internal']['outflows'] == 25
    assert {a['closing_balance'] for a in report['accounts']} == {Decimal('25'), Decimal('-25')}
    assert_balanced(report)


@pytest.mark.parametrize('first,last', [('bad', '2024-01-01'), ('2024-02-30', '2024-03-01'),
                                      ('2024-03-01', '2024-02-01')])
def test_invalid_dates(db, ee_org, first, last):
    with pytest.raises(ValueError):
        CashFlowService(db).statement(ee_org['id'], date_from=first, date_to=last)


def test_bank_role_scope_and_missing_organisation(db, books):
    org, accounts = books
    bank = DocumentService(db).create_bank_account(org, name='Synthetic unroled bank', currency='EUR')
    accounts['UNROLED'] = bank['ledger_account_id']
    post(db, org, accounts, '2024-02-01', 'unroled', [('UNROLED', '100', '0', '', None), ('CAPITAL', '0', '100', '', None)])
    assert CashFlowService(db).statement(org, date_from='2024-02-01', date_to='2024-02-01')['closing_balance'] == 0
    with pytest.raises(KeyError):
        CashFlowService(db).statement('missing', date_from='2024-02-01', date_to='2024-02-01')


@pytest.mark.parametrize('country', ['UK', 'EE'])
def test_bank_role_on_fresh_and_upgraded_organisations(tmp_path, monkeypatch, country):
    import shutil
    import database
    import organisations

    original = database.MIGRATIONS
    previous = tmp_path / 'previous' / 'sqlite'
    previous.mkdir(parents=True)
    for source in (original / 'sqlite').glob('*.sql'):
        if source.stem < '0016':
            shutil.copyfile(source, previous / source.name)
    monkeypatch.setattr(database, 'MIGRATIONS', previous.parent)
    later_roles = {'SUPPLIER_PREPAYMENTS', 'CUSTOMER_PREPAYMENTS', 'FIXED_ASSETS',
                   'ACCUMULATED_DEPRECIATION', 'DEPRECIATION_EXPENSE'}
    for chart in ['UK_ACCOUNTS', 'EE_ACCOUNTS']:
        monkeypatch.setattr(organisations, chart, tuple(a for a in getattr(organisations, chart) if a[4] not in later_roles))
    db = database.Database(path=str(tmp_path / 'upgrade.sqlite'))
    db.migrate()
    org = organisations.OrganisationService(db).create(name='Synthetic upgrade', country_code=country,
        entity_type='UK_COMPANY' if country == 'UK' else 'EE_OU', owner_email='owner@example.test')
    liquid = db.rows("SELECT * FROM accounts WHERE organisation_id=? AND system_role='BANK'", (org['id'],))
    assert len(liquid) == 1
    accounts = {a['system_role']: a['id'] for a in db.rows('SELECT * FROM accounts WHERE organisation_id=?', (org['id'],))}
    day = db.scalar('SELECT MIN(starts_on) FROM fiscal_periods WHERE organisation_id=?', (org['id'],))
    movement(db, org['id'], accounts, day, 'before-upgrade', 'CAPITAL', '25')
    before = CashFlowService(db).statement(org['id'], date_from=day, date_to=day)
    monkeypatch.setattr(database, 'MIGRATIONS', original)
    assert db.migrate() == ['0016_bank_feed_schedules', '0017_prepayments', '0018_fixed_assets', '0019_master_data_import', '0020_quotes', '0021_periodisation', '0022_payment_links', '0023_analytical_objects', '0024_reminder_rules', '0025_fx_realised', '0026_fx_revaluations', '0027_mfa', '0028_document_settings', '0029_copilot', '0030_master_data_maintenance', '0031_master_data_groups', '0032_copilot_access', '0033_copilot_settings', '0034_payroll_demo_fixes', '0035_payroll_income_line', '0036_payroll_component_catalogue', '0037_employee_tax_settings', '0038_payroll_payday_rules', '0039_payroll_payouts', '0040_payroll_settlement_dates', '0041_payroll_sepa_details', '0042_payroll_component_metadata']
    assert db.rows("SELECT * FROM accounts WHERE organisation_id=? AND system_role='BANK'", (org['id'],)) == liquid
    assert CashFlowService(db).statement(org['id'], date_from=day, date_to=day) == before
    assert before['closing_balance'] == 25
