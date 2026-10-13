-- Column additions are guarded by the migration runner on SQLite reruns.
ALTER TABLE user_accounts ADD COLUMN totp_secret TEXT;
ALTER TABLE user_accounts ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE user_accounts ADD COLUMN totp_last_step INTEGER;

CREATE TABLE IF NOT EXISTS mfa_recovery_codes (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES user_accounts(id),
    code_hash TEXT NOT NULL,
    used_at INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE(account_id, code_hash)
);
CREATE INDEX IF NOT EXISTS mfa_recovery_codes_account ON mfa_recovery_codes(account_id);
