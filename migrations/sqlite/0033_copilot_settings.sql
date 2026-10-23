CREATE TABLE IF NOT EXISTS copilot_settings (
    organisation_id TEXT PRIMARY KEY REFERENCES organisations(id),
    encrypted_credentials TEXT,
    encryption_key_version INTEGER,
    model TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
