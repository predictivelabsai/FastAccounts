-- Staged master data is retained, including discarded rows, for audit.
ALTER TABLE items ADD COLUMN unit TEXT NOT NULL DEFAULT '';
ALTER TABLE items ADD COLUMN purchase_price NUMERIC(20,4) CHECK(purchase_price>=0);
CREATE UNIQUE INDEX idx_items_tenant_id ON items(organisation_id,id);
CREATE TABLE import_batches (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    kind TEXT NOT NULL CHECK(kind IN ('contacts','items')),
    status TEXT NOT NULL CHECK(status IN ('staged','committed','discarded')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    total_rows INTEGER NOT NULL DEFAULT 0 CHECK(total_rows>=0),
    error_count INTEGER NOT NULL DEFAULT 0 CHECK(error_count>=0),
    warning_count INTEGER NOT NULL DEFAULT 0 CHECK(warning_count>=0),
    UNIQUE(organisation_id,id)
);
CREATE INDEX idx_import_batches_status ON import_batches(organisation_id,status,created_at);
CREATE TABLE import_rows (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    batch_id TEXT NOT NULL,
    row_number INTEGER NOT NULL CHECK(row_number>0),
    raw_json TEXT NOT NULL,
    parsed_json TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    warning TEXT NOT NULL DEFAULT '',
    entity_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(organisation_id,batch_id,row_number),
    FOREIGN KEY(organisation_id,batch_id) REFERENCES import_batches(organisation_id,id)
);
