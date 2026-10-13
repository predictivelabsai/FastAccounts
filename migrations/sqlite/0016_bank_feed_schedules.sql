CREATE TABLE IF NOT EXISTS bank_feed_schedules (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    gocardless_account_id TEXT NOT NULL,
    interval_kind TEXT NOT NULL DEFAULT 'daily' CHECK (interval_kind = 'daily'),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    next_run_date TEXT NOT NULL,
    last_run_date TEXT,
    last_pull_at TEXT,
    last_result TEXT CHECK (last_result IN ('Running','Success','Error','Reauth Required')),
    last_error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organisation_id,gocardless_account_id)
);

CREATE INDEX IF NOT EXISTS bank_feed_schedules_due
ON bank_feed_schedules (organisation_id,active,next_run_date);
