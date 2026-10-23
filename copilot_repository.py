"""Organisation-scoped copilot provider settings."""
from core_utils import audit, utc_now


def settings(db, organisation_id):
    return db.one("SELECT * FROM copilot_settings WHERE organisation_id=?",
                  (organisation_id,)) or {}


def save_settings(db, organisation_id, *, encrypted, version, model, actor):
    with db.transaction() as tx:
        tx.execute("UPDATE organisations SET name=name WHERE id=?", (organisation_id,))
        tx.execute(
            "INSERT INTO copilot_settings(organisation_id,encrypted_credentials,"
            "encryption_key_version,model,updated_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(organisation_id) DO UPDATE SET "
            "encrypted_credentials=excluded.encrypted_credentials,"
            "encryption_key_version=excluded.encryption_key_version,"
            "model=excluded.model,updated_at=excluded.updated_at",
            (organisation_id, encrypted, version, model, utc_now()))
        audit(tx, organisation_id, actor, "copilot.settings_updated", "organisation",
              organisation_id, {"configured": bool(encrypted), "model_changed": True})
