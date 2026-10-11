CREATE TABLE IF NOT EXISTS account_mappings (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    local_account_code TEXT NOT NULL,
    external_account_code TEXT NOT NULL,
    external_account_name TEXT,
    status TEXT NOT NULL DEFAULT 'Suggested' CHECK (status IN ('Suggested','Confirmed','Disabled')),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0,1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organisation_id,provider,local_account_code),
    UNIQUE (organisation_id,provider,external_account_code)
);

ALTER TABLE import_staged_records ADD COLUMN matched_local_id TEXT;
ALTER TABLE import_staged_records ADD COLUMN match_json TEXT;
UPDATE import_staged_records
SET matched_local_id=matched_local_employee_id
WHERE matched_local_employee_id IS NOT NULL;
