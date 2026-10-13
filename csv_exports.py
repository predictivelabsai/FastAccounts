"""Read-only list and accounting report CSV rendering."""
from __future__ import annotations

import csv
from decimal import Decimal
from io import StringIO

from cash_flow import CashFlowService
from database import get_database
from invoice_list import _csv_text, validate_list_dates
from ledger import LedgerService
from list_export_repository import ListExportRepository
from objects import ObjectService
from quotes import QuoteService


# Columns are explicit so empty lists retain a stable, useful header.
CONTACT_COLUMNS = (
    ('Name', 'name'), ('Type', 'contact_type'), ('Email', 'email'),
    ('Country', 'country_code'), ('VAT number', 'vat_no'),
    ('Registration number', 'registration_no'), ('Address', 'address'),
    ('IBAN', 'iban'), ('Payment terms (days)', 'payment_terms_days'))
QUOTE_COLUMNS = (
    ('Number', 'quote_number'), ('Customer', 'contact_name'), ('Quote date', 'quote_date'),
    ('Valid until', 'valid_until'), ('Status', 'status'), ('Currency', 'currency'),
    ('Subtotal', 'subtotal'), ('Tax', 'tax_total'), ('Total', 'total'), ('Notes', 'notes'))
BANK_COLUMNS = (
    ('Date', 'booking_date'), ('Value date', 'value_date'), ('Counterparty', 'counterparty'),
    ('Reference', 'reference'), ('Amount', 'amount'), ('Currency', 'currency'), ('Status', 'status'))
OBJECT_COLUMNS = (('Code', 'code'), ('Name', 'name'), ('Object type', 'object_type'), ('Active', 'active'))
ACCOUNT_COLUMNS = (
    ('Code', 'code'), ('Account', 'name'), ('Type', 'account_type'),
    ('Debit', 'debit'), ('Credit', 'credit'), ('Balance', 'balance'))
LEDGER_COLUMNS = (
    ('Date', 'entry_date'), ('Code', 'account_code'), ('Account', 'account_name'),
    ('Reference', 'voucher_code'), ('Description', 'memo'), ('Debit', 'debit'),
    ('Credit', 'credit'), ('Currency', 'currency'), ('Contact', 'contact_name'),
    ('Status', 'status'), ('Project', 'projects_project_id'), ('Location', 'projects_location_id'),
    ('Person', 'projects_person_id'), ('Object', 'projects_object_id'))
AGING_COLUMNS = (
    ('Number', 'number'), ('Contact', 'contact_name'), ('Date', 'document_date'),
    ('Due date', 'due_date'), ('Currency', 'currency'), ('Days overdue', 'days_overdue'),
    ('Classification', 'bucket'), ('Outstanding', 'outstanding'))
CASH_COLUMNS = (('Description', 'description'), ('Inflows', 'inflows'),
                ('Outflows', 'outflows'), ('Balance', 'balance'), ('Currency', 'currency'))
REPORT_TABS = frozenset({'trial-balance', 'profit-and-loss', 'balance-sheet', 'general-ledger',
                         'cash-flow', 'receivables-aging', 'payables-aging'})
MONEY_FIELDS = frozenset({'subtotal', 'tax_total', 'total', 'amount', 'debit', 'credit',
                          'balance', 'outstanding', 'inflows', 'outflows'})


def _render(columns, rows):
    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow([label for label, _ in columns])
    for row in rows:
        values = []
        for _, key in columns:
            value = row.get(key)
            if value is None:
                value = ''
            elif key in MONEY_FIELDS:
                # Numeric cells bypass the text guard, including negative money.
                value = format(Decimal(str(value)).quantize(Decimal('0.01')), 'f')
            else:
                value = _csv_text(value)
            values.append(value)
        writer.writerow(values)
    return output.getvalue().encode('utf-8-sig')


class CsvExportService:
    def __init__(self, db=None):
        self.db = db or get_database()

    def export(self, organisation_id, kind):
        repo = ListExportRepository(self.db)
        if kind == 'contacts':
            return _render(CONTACT_COLUMNS, repo.contacts(organisation_id))
        if kind == 'quotes':
            return _render(QUOTE_COLUMNS, QuoteService(self.db).list(organisation_id))
        if kind == 'bank-transactions':
            return _render(BANK_COLUMNS, repo.bank_transactions(organisation_id))
        if kind == 'objects':
            return _render(OBJECT_COLUMNS, ObjectService(self.db).list(organisation_id))
        raise KeyError('List export not found')

    def report(self, organisation_id, tab, *, start=None, end=None, as_at=None,
               date_from=None, date_to=None, object_id=None):
        if tab not in REPORT_TABS:
            raise KeyError('Report export not found')
        if tab == 'cash-flow':
            first, last = date_from, date_to
        elif tab in {'balance-sheet', 'receivables-aging', 'payables-aging'}:
            first, last = (start if tab == 'balance-sheet' else None), as_at
        else:
            first, last = start, end
        if last is None or (first is None and tab not in {'balance-sheet', 'receivables-aging', 'payables-aging'}):
            raise ValueError('Report dates are required')
        validate_list_dates(first, last)
        ledger = LedgerService(self.db)
        if tab == 'trial-balance':
            return _render(ACCOUNT_COLUMNS, ledger.trial_balance(
                organisation_id, start=start, end=end, object_id=object_id))
        if tab in {'profit-and-loss', 'balance-sheet'}:
            if tab == 'profit-and-loss':
                data = ledger.profit_and_loss(organisation_id, start=start, end=end, object_id=object_id)
                totals = [('Income', 'income'), ('Expenses', 'expenses'), ('Profit', 'profit')]
            else:
                data = ledger.balance_sheet(organisation_id, as_at=as_at, start=start)
                totals = [('Assets', 'assets'), ('Liabilities', 'liabilities'), ('Equity', 'equity'),
                          ('Current earnings', 'current_earnings'), ('Liabilities and equity', 'liabilities_and_equity')]
            rows = data['accounts'] + [dict(name=label, balance=data[key]) for label, key in totals]
            return _render(ACCOUNT_COLUMNS, rows)
        if tab == 'general-ledger':
            return _render(LEDGER_COLUMNS, ledger.general_ledger(
                organisation_id, start=start, end=end, object_id=object_id))
        if tab.endswith('-aging'):
            method = ledger.receivables_aging if tab == 'receivables-aging' else ledger.payables_aging
            return _render(AGING_COLUMNS, method(organisation_id, as_at=as_at)['items'])
        data = CashFlowService(self.db).statement(organisation_id, date_from=date_from, date_to=date_to)
        rows = [dict(description='Opening balance', balance=data['opening_balance'])]
        rows += [dict(description=key, inflows=value['inflows'], outflows=value['outflows'],
                      balance=value['net']) for key, value in data['buckets'].items()]
        rows += [dict(description='Total', inflows=data['inflows'], outflows=data['outflows']),
                 dict(description='Closing balance', balance=data['closing_balance'])]
        return _render(CASH_COLUMNS, [row | {'currency': data['base_currency']} for row in rows])
