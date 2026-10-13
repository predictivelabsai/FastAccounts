-- AI copilot (Grok): per-organisation opt-in, per-user transcripts and
-- per-day counters. The migration runner guards reruns via schema_migrations.
ALTER TABLE organisations ADD COLUMN copilot_enabled INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS copilot_messages (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    user_email TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL CHECK(length(content) <= 60000),
    attachment_ids_json TEXT,
    stage_proposal_json TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    model TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS copilot_messages_org_time
    ON copilot_messages(organisation_id, user_email, created_at);

CREATE TABLE IF NOT EXISTS copilot_usage (
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    user_email TEXT NOT NULL,
    day TEXT NOT NULL CHECK(length(day) = 10),
    messages INTEGER NOT NULL DEFAULT 0,
    scans INTEGER NOT NULL DEFAULT 0,
    prompt_chars INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (organisation_id, user_email, day)
);