-- Email and password sign-in beside Google SSO. Workspace access stays keyed by
-- the verified, lower-cased email used by memberships and invitations.
CREATE TABLE user_accounts (
 id TEXT PRIMARY KEY,
 email TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL DEFAULT '',
 password_hash TEXT,
 email_verified INTEGER NOT NULL DEFAULT 0 CHECK(email_verified IN (0,1)),
 google_linked INTEGER NOT NULL DEFAULT 0 CHECK(google_linked IN (0,1)),
 session_version INTEGER NOT NULL DEFAULT 1,
 password_changed_at TEXT,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
-- Single-use verification and password-reset tokens; only SHA-256 digests are stored.
CREATE TABLE auth_tokens (
 id TEXT PRIMARY KEY,
 account_id TEXT NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
 purpose TEXT NOT NULL CHECK(purpose IN ('verify','reset')),
 token_hash TEXT NOT NULL UNIQUE,
 expires_at BIGINT NOT NULL,
 used_at BIGINT,
 created_at TEXT NOT NULL
);
CREATE INDEX idx_auth_tokens_account_purpose ON auth_tokens(account_id,purpose);
-- Fixed-window throttles for sign-in, registration, reset and token forms.
-- Subjects (email or client address) are stored as SHA-256 digests.
CREATE TABLE auth_rate_limits (
 subject_hash TEXT NOT NULL,
 action TEXT NOT NULL,
 window_start BIGINT NOT NULL,
 attempts INTEGER NOT NULL,
 PRIMARY KEY(subject_hash,action)
);
