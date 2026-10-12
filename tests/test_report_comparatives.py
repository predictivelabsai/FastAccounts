"""Calendar comparatives, report arithmetic and authorised API compatibility."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from core_utils import new_id
from ledger import LedgerService, PostingLine, comparison_periods


@pytest.mark.parametrize('start,end,mode,expected', [
    ('2024-03-01', '2024-03-31', 'previous', ('2024-03-01', '2024-03-31', '2024-02-01', '2024-02-29')),
    ('2024-04-01', '2024-06-30', 'previous', ('2024-04-01', '2024-06-30', '2024-01-01', '2024-03-31')),
    ('2024-01-01', '2024-12-31', 'previous', ('2024-01-01', '2024-12-31', '2023-01-01', '2023-12-31')),
    ('2024-03-10', '2024-03-20', 'previous', ('2024-03-10', '2024-03-20', '2024-02-28', '2024-03-09')),
    ('2024-02-29', '2024-02-29', 'prior_year', ('2024-02-29', '2024-02-29', '2023-02-28', '2023-02-28')),
    ('2024-02-01', '2024-02-15', 'ytd', ('2024-01-01', '2024-02-29', '2023-01-01', '2023-02-28')),
    ('2025-02-01', '2025-02-15', 'ytd', ('2025-01-01', '2025-02-28', '2024-01-01', '2024-02-29')),
    ('2024-01-01', '2024-01-31', 'previous', ('2024-01-01', '2024-01-31', '2023-12-01', '2023-12-31')),
    ('2025-02-01', '2025-02-28', 'prior_year', ('2025-02-01', '2025-02-28', '2024-02-01', '2024-02-29')),
])
def test_comparison_date_math(start, end, mode, expected):
    assert comparison_periods(start, end, mode) == expected


DATA = [('2023-01-10', 11), ('2023-02-28', 12), ('2023-06-30', 13), ('2023-12-31', 14),
        ('2024-01-31', 21), ('2024-02-01', 22), ('2024-02-29', 23), ('2024-03-09', 24),
        ('2024-03-10', 25), ('2024-03-20', 26), ('2024-03-21', 27), ('2024-04-01', 28), ('2024-06-30', 29)]


@pytest.fixture
def reporting_books(db, uk_org):
    org = uk_org['id']
    with db.transaction() as tx:
        tx.execute("INSERT INTO fiscal_periods(id,organisation_id,code,starts_on,ends_on) "
                   "VALUES (?,?,'comparatives-fixture','2023-01-01','2025-12-31')", (new_id(), org))
    accounts = {r['system_role']: r['id'] for r in db.rows('SELECT * FROM accounts WHERE organisation_id=?', (org,))}
    for day, amount in DATA:
        value = Decimal(amount)
        expense = value / 10
        LedgerService(db).post(organisation_id=org, posting_date=day, voucher_type='journal',
            voucher_id=day, voucher_code=day, actor='owner@example.test', currency='GBP',
            lines=[PostingLine(accounts['AR'], debit=value), PostingLine(accounts['SALES'], credit=value),
                   PostingLine(accounts['EXPENSE'], debit=expense), PostingLine(accounts['BANK'], credit=expense)])
    return org


@pytest.mark.parametrize('start,end,mode,current,previous', [
    ('2024-02-01', '2024-02-29', 'previous', 45, 21),
    ('2024-04-01', '2024-06-30', 'previous', 57, 168),
    ('2024-01-01', '2024-12-31', 'previous', 225, 50),
    ('2024-03-10', '2024-03-20', 'previous', 51, 47),
    ('2024-02-01', '2024-02-29', 'prior_year', 45, 12),
    ('2024-02-01', '2024-02-15', 'ytd', 66, 23),
])
def test_profit_and_balance_comparative_values(db, reporting_books, ee_org, start, end, mode, current, previous):
    service = LedgerService(db)
    result = service.profit_and_loss(reporting_books, start=start, end=end, compare=mode)
    for report, income in [(result, current), (result['comparative'], previous)]:
        assert report['income'] == income
        assert report['expenses'] == Decimal(income) / 10
        assert report['profit'] == Decimal(income) * Decimal('0.9')
    for row in result['accounts']:
        expected = next(r for r in result['comparative']['accounts'] if r['code'] == row['code'])
        assert row['comparative_balance'] == expected['balance']
    sheet = service.balance_sheet(reporting_books, as_at=end, start=start, compare=mode)
    for report in [sheet, sheet['comparative']]:
        expected = sum((Decimal(amount) for day, amount in DATA if day <= report['as_at']), Decimal('0')) * Decimal('0.9')
        assert report['assets'] == report['current_earnings'] == report['liabilities_and_equity'] == expected
        assert report['liabilities'] == report['equity'] == 0
    isolated = service.profit_and_loss(ee_org['id'], start=start, end=end, compare=mode)
    assert isolated['income'] == isolated['comparative']['income'] == 0


def test_unchanged_single_period_and_default_balance_month(db, reporting_books):
    service = LedgerService(db)
    original = service.profit_and_loss(reporting_books, start='2024-02-01', end='2024-02-15')
    assert set(original) == {'start', 'end', 'income', 'expenses', 'profit', 'accounts'}
    assert original['income'] == 22
    original = service.balance_sheet(reporting_books, as_at='2024-02-15')
    assert 'comparative' not in original
    compared = service.balance_sheet(reporting_books, as_at='2024-02-15', compare='previous')
    assert compared['comparative']['as_at'] == '2024-01-31'
    assert compared['assets'] == original['assets']


def test_reports_api_and_mounted_web_permissions(db, reporting_books, ee_org, monkeypatch):
    from api_app import api
    from database import reset_database_cache
    from organisations import OrganisationService
    from web_app import app

    monkeypatch.setenv('FASTACCOUNTS_DB', db.path)
    monkeypatch.setenv('DB_URL', '')
    reset_database_cache()
    OrganisationService(db).add_member(reporting_books, 'owner@example.test', 'viewer@example.test', 'viewer')
    base = f'/organisations/{reporting_books}/reports/'
    queries = {'cash-flow': {'date_from': '2024-02-01', 'date_to': '2024-02-29'},
               'profit-and-loss': {'start': '2024-02-01', 'end': '2024-02-29', 'compare': 'previous'},
               'balance-sheet': {'as_at': '2024-02-29', 'compare': 'ytd'}}
    try:
        for application, prefix in [(api, ''), (app, '/api')]:
            with TestClient(application, headers={'X-Test-User': 'viewer@example.test'}) as client:
                for report, query in queries.items():
                    response = client.get(prefix + base + report, params=query)
                    assert response.status_code == 200, response.text
                    if report == 'cash-flow':
                        assert Decimal(str(response.json()['outflows'])) == Decimal('4.50')
                    else:
                        assert 'comparative' in response.json()
                    assert client.get(prefix + base.replace(reporting_books, ee_org['id']) + report, params=query).status_code == 403
                    assert client.get(prefix + base + report, params=query, headers={'X-Test-User': 'outsider@example.test'}).status_code == 403
                assert client.get(prefix + base + 'cash-flow', params={'date_from': 'bad', 'date_to': '2024-02-29'}).status_code == 422
                for report in ['profit-and-loss', 'balance-sheet']:
                    assert client.get(prefix + base + report, params={**queries[report], 'compare': 'invalid'}).status_code == 422
                single = client.get(prefix + base + 'profit-and-loss', params={'start': '2024-02-01', 'end': '2024-02-29'})
                assert 'comparative' not in single.json()
    finally:
        reset_database_cache()
