"""Manual exchange rates and exact-direction historical booking resolution."""
import re
import sqlite3
from datetime import date
from decimal import Decimal

from psycopg import IntegrityError

from core_utils import audit, decimal
from database import get_database
from exchange_rates_repository import ExchangeRateRepository


def positive_rate(value):
    rate = decimal(value)
    if not rate.is_finite() or rate <= 0:
        raise ValueError('Exchange rate must be positive')
    return rate


def resolve_rate(tx, organisation_id, from_currency, to_currency, rate_date):
    """Return latest exact-direction rate on or before the date, or None."""
    row = ExchangeRateRepository(tx, organisation_id).resolve(from_currency, to_currency, rate_date)
    return decimal(row['rate']) if row else None


def booking_rate(tx, organisation_id, currency, base_currency, rate_date, explicit=None):
    if explicit is not None:
        return positive_rate(explicit)
    if currency != base_currency:
        return positive_rate(resolve_rate(tx, organisation_id, currency, base_currency, rate_date) or Decimal('1'))
    return Decimal('1')


class ExchangeRateService:
    def __init__(self, db=None):
        self.db = db or get_database()

    def list(self, organisation_id):
        with self.db.transaction() as tx:
            return ExchangeRateRepository(tx, organisation_id).list()

    def create(self, organisation_id, *, rate_date, from_currency, to_currency, rate, actor):
        if not isinstance(rate_date, str) or date.fromisoformat(rate_date).isoformat() != rate_date:
            raise ValueError('Rate date must use YYYY-MM-DD')
        if any(not re.fullmatch(r'[A-Z]{3}', code) for code in (from_currency, to_currency)):
            raise ValueError('Currencies must be three uppercase letters')
        if from_currency == to_currency:
            raise ValueError('From and to currencies must differ')
        rate = positive_rate(rate)
        if rate >= Decimal('10000000000') or rate != rate.quantize(Decimal('0.0000000001')):
            raise ValueError('Rate must fit NUMERIC(20,10)')
        try:
            with self.db.transaction() as tx:
                row = ExchangeRateRepository(tx, organisation_id).create(rate_date, from_currency, to_currency, rate)
                audit(tx, organisation_id, actor, 'exchange_rate.created', 'exchange_rate', row['id'],
                      dict(rate_date=rate_date, from_currency=from_currency, to_currency=to_currency, rate=str(rate), source='manual'))
                return row
        except (sqlite3.IntegrityError, IntegrityError) as exc:
            # Check after rollback so PostgreSQL's failed transaction is never reused.
            if any(row['rate_date'] == rate_date and row['from_currency'] == from_currency
                   and row['to_currency'] == to_currency and row['source'] == 'manual'
                   for row in self.list(organisation_id)):
                raise ValueError('A manual exchange rate already exists for this date and currency pair') from exc
            raise

    def delete(self, organisation_id, row_id, *, actor):
        with self.db.transaction() as tx:
            repo = ExchangeRateRepository(tx, organisation_id)
            row = repo.get(row_id)
            if not row:
                raise KeyError('Exchange rate not found')
            repo.delete(row_id)
            audit(tx, organisation_id, actor, 'exchange_rate.deleted', 'exchange_rate', row_id, row)
            return {'deleted': True}
