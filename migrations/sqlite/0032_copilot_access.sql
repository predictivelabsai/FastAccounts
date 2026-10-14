-- Copilot access grants: organisation administrators always have access
-- once the organisation opts in; other members need an explicit grant row.
-- The provider key itself never enters the database or the repository.
CREATE TABLE IF NOT EXISTS copilot_access_grants (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    granted_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id, email)
);