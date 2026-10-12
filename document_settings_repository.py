"""Organisation-scoped document appearance persistence."""
from core_utils import new_id, utc_now


class DocumentSettingsRepository:
    def __init__(self, tx, organisation_id):
        self.tx, self.oid = tx, organisation_id

    def get(self):
        return self.tx.one('SELECT * FROM document_settings WHERE organisation_id=?', (self.oid,))

    def lock(self):
        if self.tx.execute('UPDATE organisations SET name=name WHERE id=?', (self.oid,)).rowcount != 1:
            raise KeyError('Organisation not found')

    def save(self, data):
        now = utc_now()
        self.tx.execute(
            'INSERT INTO document_settings(id,organisation_id,accent_colour,footer_text,logo_attachment_id,created_at,updated_at) '
            'VALUES (?,?,?,?,?,?,?) ON CONFLICT(organisation_id) DO UPDATE SET accent_colour=excluded.accent_colour,'
            'footer_text=excluded.footer_text,logo_attachment_id=excluded.logo_attachment_id,updated_at=excluded.updated_at',
            (new_id(), self.oid, data['accent_colour'], data['footer_text'], data['logo_attachment_id'], now, now))

    def logo(self, attachment_id):
        return self.tx.one(
            "SELECT * FROM attachments WHERE organisation_id=? AND id=? AND owner_type='organisation' AND owner_id=?",
            (self.oid, attachment_id, self.oid))

    def delete_logo(self, attachment_id):
        attachment = self.logo(attachment_id)
        if attachment:
            self.tx.execute(
                "DELETE FROM attachments WHERE organisation_id=? AND id=? AND owner_type='organisation' AND owner_id=?",
                (self.oid, attachment_id, self.oid))
        return attachment
