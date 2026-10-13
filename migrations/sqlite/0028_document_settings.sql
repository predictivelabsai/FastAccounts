CREATE TABLE IF NOT EXISTS document_settings (
    id TEXT PRIMARY KEY,
    organisation_id TEXT NOT NULL UNIQUE REFERENCES organisations(id) ON DELETE CASCADE,
    accent_colour TEXT NULL CHECK (accent_colour IS NULL OR
        (length(accent_colour)=7 AND accent_colour GLOB '#[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]')),
    footer_text TEXT NULL CHECK (footer_text IS NULL OR length(footer_text)<=500),
    logo_attachment_id TEXT NULL REFERENCES attachments(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
