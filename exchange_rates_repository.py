"""Parameterised, organisation-scoped exchange rate queries."""
from core_utils import db_number, new_id, utc_now


class ExchangeRateRepository:
    def __init__(self, tx, organisation_id):
        self.tx, self.oid = tx, organisation_id

    def list(self):
        return self.tx.rows('SELECT * FROM exchange_rates WHERE organisation_id=? '
                            'ORDER BY rate_date DESC,from_currency,to_currency,source,id', (self.oid,))

    def resolve(self, from_currency, to_currency, rate_date):
        return self.tx.one('SELECT rate FROM exchange_rates WHERE organisation_id=? '
                           'AND from_currency=? AND to_currency=? AND rate_date<=? '
                           "ORDER BY rate_date DESC,CASE WHEN source='manual' THEN 0 ELSE 1 END,source,id LIMIT 1",
                           (self.oid, from_currency, to_currency, rate_date))

    def create(self, rate_date, from_currency, to_currency, rate):
        row_id = new_id()
        self.tx.execute('INSERT INTO exchange_rates(id,organisation_id,rate_date,from_currency,to_currency,rate,source,created_at) '
                        "VALUES (?,?,?,?,?,?,'manual',?)",
                        (row_id, self.oid, rate_date, from_currency, to_currency, db_number(rate), utc_now()))
        return self.get(row_id)

    def get(self, row_id):
        return self.tx.one('SELECT * FROM exchange_rates WHERE organisation_id=? AND id=?', (self.oid, row_id))

    def delete(self, row_id):
        self.tx.execute('DELETE FROM exchange_rates WHERE organisation_id=? AND id=?', (self.oid, row_id))
