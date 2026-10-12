"""Reusable CSV staging, review and atomic commit with per-kind validators.

Like the employee reviewed import, application is explicit and issues belong to
individual rows. Discard retains staged rows for audit; existing data is never updated.
"""
import csv
import io
import json
import re
from decimal import Decimal, InvalidOperation

from core_utils import audit
from database import get_database
from database import Database
from master_data_repository import ImportRepository

MAX_CHARS = 2_000_000
MAX_ROWS = 10_000


class Contacts:
    columns = {'name', 'contact_type', 'email', 'phone', 'address', 'registry_code', 'vat_number', 'bank_account'}
    required = {'name', 'contact_type'}

    @staticmethod
    def keys(fields):
        return [('name', fields['name'].lower())] + ([('registry', fields['registry_code'])] if fields.get('registry_code') else [])

    @staticmethod
    def validate(fields, repo):
        errors = []
        if fields.get('contact_type') not in {'customer', 'supplier', 'both'}:
            errors.append('Invalid contact type')
        if fields.get('email') and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', fields['email']):
            errors.append('Invalid email')
        if fields.get('registry_code') and not re.fullmatch(r'(?:[0-9]{8}|[0-9]{11})', fields['registry_code']):
            errors.append('Registry code must contain 8 or 11 digits')
        if fields.get('vat_number') and not re.fullmatch(r'(?:EE[0-9]{9}|GB[0-9]{9}(?:[0-9]{3})?|[A-Z]{2}[A-Z0-9]{8,12})', fields['vat_number']):
            errors.append('Invalid VAT number')
        # EE and GB need their exact national shapes, rather than the generic fallback.
        if fields.get('vat_number', '').startswith(('EE', 'GB')) and not re.fullmatch(r'(?:EE[0-9]{9}|GB[0-9]{9}(?:[0-9]{3})?)', fields['vat_number']):
            if 'Invalid VAT number' not in errors:
                errors.append('Invalid VAT number')
        return errors


class Items:
    columns = {'code', 'name', 'sale_account', 'purchase_account', 'unit', 'sale_price', 'purchase_price'}
    required = {'code', 'name'}

    @staticmethod
    def keys(fields):
        return [('code', fields['code'])]

    @staticmethod
    def validate(fields, repo):
        errors = []
        for column in ('sale_price', 'purchase_price'):
            if fields.get(column):
                try:
                    value = Decimal(fields[column])
                    if not value.is_finite() or value < 0 or value >= Decimal('10000000000000000') or value.as_tuple().exponent < -4:
                        raise ValueError()
                    fields[column] = format(value, 'f')
                except (InvalidOperation, ValueError):
                    errors.append('Invalid ' + column.replace('_', ' '))
        for column, role, target in (('sale_account', 'SALES', 'sales_account_id'), ('purchase_account', 'COST_OF_SALES', 'purchase_account_id')):
            account = repo.account(fields.get(column), role)
            if not account:
                errors.append('Invalid ' + column.replace('_', ' '))
            else:
                fields[target] = account['id']
        return errors


KINDS = {'contacts': Contacts, 'items': Items}
ALIASES = {'registry_code': 'registry_code', 'registration_no': 'registry_code', 'personal_code': 'registry_code',
           'vat_no': 'vat_number', 'iban': 'bank_account', 'sales_account': 'sale_account', 'unit_price': 'sale_price'}


class MasterDataImportService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    def stage(self, organisation_id: str, kind: str, csv_content: str, *, actor: str) -> dict:
        if kind not in KINDS:
            raise ValueError('Unsupported import kind')
        if not isinstance(csv_content, str) or not csv_content.strip() or len(csv_content) > MAX_CHARS:
            raise ValueError('Supply CSV text within the 2000000 character limit')
        adapter = KINDS[kind]
        source = io.StringIO(csv_content.lstrip('\ufeff'))
        reader = csv.reader(source, strict=True)
        try:
            headers = next(reader)
        except (StopIteration, csv.Error) as exc:
            raise ValueError('Invalid CSV header') from exc
        headers = [h.strip().lower().replace(' ', '_') for h in headers]
        headers = [ALIASES.get(h, h) for h in headers]
        if len(set(headers)) != len(headers) or not adapter.required <= set(headers) or not set(headers) <= adapter.columns:
            raise ValueError('CSV columns must match the supported columns for ' + kind)
        with self.db.transaction() as tx:
            repo = ImportRepository(tx, organisation_id)
            repo.lock_organisation()
            batch_id = repo.stage_batch(kind, actor)
            number = 0
            seen = set()
            while True:
                row_number, start = reader.line_num + 1, source.tell()
                try:
                    values = next(reader)
                except StopIteration:
                    break
                except csv.Error:
                    number += 1
                    if number > MAX_ROWS:
                        raise ValueError('CSV exceeds the 10000 row limit')
                    repo.stage_row(batch_id, row_number, [source.getvalue()[start:source.tell()]], {}, 'Malformed CSV row')
                    # Resume when possible. An unclosed quote may consume the rest.
                    continue
                if not any(v.strip() for v in values):
                    continue
                number += 1
                if number > MAX_ROWS:
                    raise ValueError('CSV exceeds the 10000 row limit')
                fields = {h: v.strip() for h, v in zip(headers, values)}
                errors = ['CSV row has the wrong number of columns'] if len(values) != len(headers) else []
                errors.extend('Required field: ' + h for h in sorted(adapter.required) if not fields.get(h))
                errors.extend(adapter.validate(fields, repo))
                warning = ''
                if not errors:
                    keys = adapter.keys(fields)
                    if seen.intersection(keys) or repo.existing(kind, fields):
                        warning = 'Existing record will be skipped'
                    else:
                        seen.update(keys)
                repo.stage_row(batch_id, row_number, values, fields, '; '.join(errors), warning)
            repo.counts(batch_id)
            audit(tx, organisation_id, actor, 'import.staged', 'import_batch', batch_id)
        return self.get(organisation_id, batch_id)

    def get(self, organisation_id: str, batch_id: str, *, limit: int = 100, offset: int = 0) -> dict:
        if not 1 <= limit <= MAX_ROWS or offset < 0:
            raise ValueError('Invalid import pagination')
        with self.db.transaction() as tx:
            repo = ImportRepository(tx, organisation_id)
            batch = repo.batch(batch_id)
            batch['rows'] = [{**r, 'raw': json.loads(r['raw_json']), 'parsed': json.loads(r['parsed_json'])} for r in repo.rows(batch_id, limit, offset)]
            batch['limit'], batch['offset'] = limit, offset
            return batch

    def commit(self, organisation_id: str, batch_id: str, *, actor: str) -> dict:
        with self.db.transaction() as tx:
            repo = ImportRepository(tx, organisation_id)
            organisation = repo.lock_organisation()
            batch = repo.batch(batch_id)
            repo.transition(batch_id, 'committed')
            for row in repo.rows(batch_id):
                if row['error']:
                    continue
                fields = json.loads(row['parsed_json'])
                if repo.existing(batch['kind'], fields):
                    repo.outcome(row['id'], None, warning='Existing record skipped')
                    continue
                errors = KINDS[batch['kind']].validate(fields, repo)
                if errors:
                    repo.outcome(row['id'], None, error='; '.join(errors))
                    continue
                entity_id = repo.create(batch['kind'], fields, organisation['country_code'])
                repo.outcome(row['id'], entity_id)
            repo.counts(batch_id)
            audit(tx, organisation_id, actor, 'import.committed', 'import_batch', batch_id)
        return self.get(organisation_id, batch_id)

    def discard(self, organisation_id: str, batch_id: str, *, actor: str) -> dict:
        with self.db.transaction() as tx:
            repo = ImportRepository(tx, organisation_id)
            repo.transition(batch_id, 'discarded')
            audit(tx, organisation_id, actor, 'import.discarded', 'import_batch', batch_id)
        return self.get(organisation_id, batch_id)
