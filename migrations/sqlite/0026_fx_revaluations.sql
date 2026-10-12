-- Run identity and immutable per-document detail in fx_revaluation.posted audits.
CREATE TABLE IF NOT EXISTS fx_revaluations (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id),
    revaluation_date TEXT NOT NULL,
    posting_batch_id TEXT,
    status TEXT NOT NULL CHECK(status IN ('Posted','Empty')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(organisation_id,id),
    UNIQUE(organisation_id,revaluation_date),
    FOREIGN KEY(organisation_id,posting_batch_id) REFERENCES posting_batches(organisation_id,id)
);
CREATE INDEX IF NOT EXISTS idx_fx_revaluations_date
    ON fx_revaluations(organisation_id,revaluation_date,id);
CREATE INDEX IF NOT EXISTS idx_gl_entries_fx_source
    ON gl_entries(organisation_id,source_line_type,source_line_id,account_id,posting_batch_id);
