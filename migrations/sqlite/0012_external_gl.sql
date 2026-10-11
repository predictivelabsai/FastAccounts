CREATE TABLE IF NOT EXISTS external_gl_entries (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_batch_ref TEXT NOT NULL,
    entry_date TEXT NOT NULL,
    external_account_code TEXT NOT NULL,
    local_account_code TEXT,
    description TEXT,
    document TEXT,
    debit NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (debit>=0),
    credit NUMERIC(18,2) NOT NULL DEFAULT 0 CHECK (credit>=0),
    dims_json TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id,provider,external_id)
);

CREATE INDEX IF NOT EXISTS idx_external_gl_org
ON external_gl_entries(organisation_id,provider,entry_date,external_account_code);
