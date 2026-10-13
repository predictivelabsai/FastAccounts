-- Contact and user groups: named tags per organisation with many-to-many
-- membership. Contact membership references contacts by the composite tenant
-- key; user membership is by email (memberships are keyed by email too and
-- addresses can hold groups before they join).
CREATE TABLE IF NOT EXISTS contact_groups (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK(length(name) <= 100),
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id, name)
);

CREATE TABLE IF NOT EXISTS contact_group_members (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    group_id TEXT NOT NULL REFERENCES contact_groups(id) ON DELETE CASCADE,
    contact_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (group_id, contact_id)
);

CREATE INDEX IF NOT EXISTS contact_group_members_contact
    ON contact_group_members(organisation_id, contact_id);

CREATE TABLE IF NOT EXISTS user_groups (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK(length(name) <= 100),
    created_at TEXT NOT NULL,
    UNIQUE (organisation_id, name)
);

CREATE TABLE IF NOT EXISTS user_group_members (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    group_id TEXT NOT NULL REFERENCES user_groups(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (group_id, email)
);