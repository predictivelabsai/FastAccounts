CREATE TABLE IF NOT EXISTS integration_connections (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Disconnected' CHECK (status IN ('Disconnected','Configured','Connected','Error','Reauth Required')),
    external_tenant_id TEXT,
    encrypted_credentials TEXT,
    encryption_key_version INTEGER,
    config_json TEXT NOT NULL DEFAULT '{}',
    last_sync_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organisation_id,provider)
);

CREATE TABLE IF NOT EXISTS external_mappings (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    object_type TEXT NOT NULL,
    local_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    external_version TEXT,
    ownership TEXT NOT NULL CHECK (ownership IN ('fastaccounts','external','manual')),
    direction TEXT NOT NULL CHECK (direction IN ('import','export','bidirectional')),
    last_hash TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE (organisation_id,provider,object_type,local_id),
    UNIQUE (organisation_id,provider,object_type,external_id)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('import','export')),
    object_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('Queued','Running','Completed','Failed','Review Required')),
    cursor_before TEXT,
    cursor_after TEXT,
    read_count INTEGER NOT NULL DEFAULT 0,
    write_count INTEGER NOT NULL DEFAULT 0,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_conflicts (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    sync_run_id TEXT NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    object_type TEXT NOT NULL,
    local_id TEXT,
    external_id TEXT,
    conflict_type TEXT NOT NULL,
    local_json TEXT,
    external_json TEXT,
    status TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','Resolved Local','Resolved External','Ignored')),
    resolved_by TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox_messages (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','Processing','Succeeded','Failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    available_at TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (organisation_id,topic,idempotency_key)
);

CREATE TABLE IF NOT EXISTS webhook_receipts (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    external_event_id TEXT NOT NULL,
    organisation_id TEXT REFERENCES organisations(id) ON DELETE CASCADE,
    signature_valid INTEGER NOT NULL CHECK (signature_valid IN (0,1)),
    payload_hash TEXT NOT NULL,
    received_at TEXT NOT NULL,
    processed_at TEXT,
    status TEXT NOT NULL DEFAULT 'Received' CHECK (status IN ('Received','Processed','Rejected','Failed')),
    UNIQUE (provider,external_event_id)
);

CREATE INDEX IF NOT EXISTS idx_outbox_ready ON outbox_messages(status,available_at);
CREATE INDEX IF NOT EXISTS idx_sync_runs_org ON sync_runs(organisation_id,provider,created_at);
