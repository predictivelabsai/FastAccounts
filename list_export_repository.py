"""Shared read-only list queries for the workspace and CSV exports."""


class ListExportRepository:
    def __init__(self, db):
        self.db = db

    def contacts(self, organisation_id):
        return self.db.rows(
            'SELECT * FROM contacts WHERE organisation_id=? ORDER BY name', (organisation_id,))

    def bank_transactions(self, organisation_id):
        return self.db.rows(
            'SELECT * FROM bank_transactions WHERE organisation_id=? ORDER BY booking_date DESC',
            (organisation_id,))
