"""Document appearance settings and organisation logo lifecycle."""
import re
from pathlib import Path

from core_utils import audit, sha256_bytes
from database import get_database
from document_settings_repository import DocumentSettingsRepository
from documents import DocumentService

MAX_LOGO_BYTES = 512 * 1024


class DocumentSettingsService:
    def __init__(self, db=None):
        self.db = db or get_database()

    @staticmethod
    def _payload(row):
        return dict(accent_colour=row['accent_colour'] if row else None,
                    footer_text=row['footer_text'] if row else None,
                    logo_attachment_id=row['logo_attachment_id'] if row else None,
                    configured=row is not None)

    def get(self, organisation_id, tx=None):
        if tx is None:
            with self.db.transaction() as owned_tx:
                return self.get(organisation_id, tx=owned_tx)
        return self._payload(DocumentSettingsRepository(tx, organisation_id).get())

    def save(self, organisation_id, *, actor, accent_colour=None, footer_text=None):
        if accent_colour is not None and (not isinstance(accent_colour, str) or
                                          not re.fullmatch(r'#[0-9a-fA-F]{6}', accent_colour)):
            raise ValueError('Accent colour must contain six hexadecimal digits after #')
        if footer_text is not None and (not isinstance(footer_text, str) or len(footer_text) > 500):
            raise ValueError('Invoice footer must contain at most 500 characters')
        with self.db.transaction() as tx:
            repo = DocumentSettingsRepository(tx, organisation_id)
            repo.lock()
            data = self._payload(repo.get())
            data.update(accent_colour=accent_colour, footer_text=footer_text)
            repo.save(data)
            audit(tx, organisation_id, actor, 'document_settings.updated', 'document_settings', organisation_id,
                  dict(accent_colour=accent_colour, footer_text=footer_text))
            return self._payload(repo.get())

    def upload_logo(self, organisation_id, *, actor, filename, content_type, content):
        suffix = Path(filename.replace('\\', '/')).suffix.lower()
        if content_type not in {'image/png', 'image/jpeg'}:
            raise ValueError('Logo must be a PNG or JPEG image')
        if not content or len(content) > MAX_LOGO_BYTES:
            raise ValueError('Logo must contain at most 512 KB')
        if content_type == 'image/png':
            valid = suffix == '.png' and content.startswith(b'\x89PNG\r\n\x1a\n')
        else:
            valid = suffix in {'.jpg', '.jpeg'} and content.startswith(b'\xff\xd8\xff')
        if not valid:
            raise ValueError('Logo content and filename must match its image type')
        attachment, old_attachment = None, None
        try:
            with self.db.transaction() as tx:
                repo = DocumentSettingsRepository(tx, organisation_id)
                repo.lock()
                data = self._payload(repo.get())
                old_id = data['logo_attachment_id']
                current = repo.logo(old_id) if old_id else None
                if current and current['sha256'] == sha256_bytes(content):
                    return data
                attachment = DocumentService(self.db).attach_evidence(
                    organisation_id, owner_type='organisation', owner_id=organisation_id,
                    filename=filename, content_type=content_type, content=content, actor=actor, tx=tx)
                data['logo_attachment_id'] = attachment['id']
                repo.save(data)
                if old_id:
                    old_attachment = repo.delete_logo(old_id)
                audit(tx, organisation_id, actor, 'document_settings.updated', 'document_settings', organisation_id,
                      dict(logo_attachment_id=attachment['id']))
                result = self._payload(repo.get())
        except Exception:
            if attachment:
                Path(attachment['storage_path']).unlink(missing_ok=True)
            raise
        if old_attachment:
            Path(old_attachment['storage_path']).unlink(missing_ok=True)
        return result

    def delete_logo(self, organisation_id, *, actor):
        attachment = None
        with self.db.transaction() as tx:
            repo = DocumentSettingsRepository(tx, organisation_id)
            repo.lock()
            data = self._payload(repo.get())
            old_id = data['logo_attachment_id']
            data['logo_attachment_id'] = None
            repo.save(data)
            if old_id:
                attachment = repo.delete_logo(old_id)
            audit(tx, organisation_id, actor, 'document_settings.updated', 'document_settings', organisation_id,
                  dict(logo_attachment_id=None))
            result = self._payload(repo.get())
        if attachment:
            Path(attachment['storage_path']).unlink(missing_ok=True)
        return result

    def logo(self, organisation_id, tx=None):
        if tx is None:
            with self.db.transaction() as owned_tx:
                return self.logo(organisation_id, tx=owned_tx)
        repo = DocumentSettingsRepository(tx, organisation_id)
        data = self._payload(repo.get())
        attachment = repo.logo(data['logo_attachment_id']) if data['logo_attachment_id'] else None
        if not attachment:
            raise KeyError('Logo not found')
        if attachment['content_type'] not in {'image/png', 'image/jpeg'}:
            raise ValueError('Logo must be a PNG or JPEG image')
        try:
            content = Path(attachment['storage_path']).read_bytes()
        except OSError:
            raise KeyError('Logo file not found') from None
        if sha256_bytes(content) != attachment['sha256'] or len(content) != attachment['size_bytes']:
            raise ValueError('Attachment integrity check failed')
        return attachment, content
