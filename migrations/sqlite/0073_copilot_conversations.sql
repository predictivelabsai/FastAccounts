-- Per-user copilot conversations. Existing transcripts are retained as one
-- conversation for each organisation and user.
CREATE TABLE copilot_conversations (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    user_email TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

ALTER TABLE copilot_messages ADD COLUMN conversation_id TEXT REFERENCES copilot_conversations(id);

INSERT INTO copilot_conversations(id,organisation_id,user_email,title,created_at,updated_at)
SELECT 'legacy-' || length(organisation_id) || '-' || organisation_id || '-' ||
       length(user_email) || '-' || user_email,
       organisation_id,
       user_email,
       COALESCE((SELECT substr(m.content,1,80) FROM copilot_messages m
                 WHERE m.organisation_id=g.organisation_id
                   AND m.user_email=g.user_email AND m.role='user'
                 ORDER BY m.created_at,m.id LIMIT 1), 'New chat'),
       MIN(created_at), MAX(created_at)
FROM copilot_messages AS g
GROUP BY organisation_id,user_email;

UPDATE copilot_messages
SET conversation_id='legacy-' || length(organisation_id) || '-' || organisation_id || '-' ||
                    length(user_email) || '-' || user_email;

CREATE INDEX copilot_conversations_owner
    ON copilot_conversations(organisation_id,user_email,deleted_at,updated_at);
CREATE INDEX copilot_messages_conversation
    ON copilot_messages(organisation_id,user_email,conversation_id,created_at);
