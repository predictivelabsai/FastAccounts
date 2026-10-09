# Concise threat model

## Protected assets

Accounting records, evidence, bank data, tax workpapers, OAuth/API credentials, personal
contact data, audit history, and statutory records under retention.

## Trust boundaries and controls

- Browser to app: Google sign-in or email and password (scrypt hashes, email confirmation
  that re-asks the chosen password, single-use SHA-256-hashed reset links valid for one hour,
  per-email lockout and per-address throttles, identical responses whether or not an account
  exists), invite-only membership, a secure signed session rotated on every sign-in and
  invalidated everywhere by a password reset, CSRF tokens on every form and API write,
  explicit CORS allowlist, and role checks on every API workflow.
- Organisation to organisation: `organisation_id` on business tables plus service queries and
  cross-tenant tests. PostgreSQL RLS is planned defense in depth.
- App to provider: least-privilege credentials encrypted at rest, HMAC/webhook replay records,
  request idempotency, bounded retries, no tokens in logs, and explicit production gates.
- Evidence storage: traversal-safe generated paths, size limit, SHA-256, metadata, and a
  documented malware-scanning hook before managed hosting.
- Tax filing: reviewed workpaper, recorded reviewer, exact export hash, provider approval,
  declaration confirmation, and submission receipt. Current direct filing is disabled.

## Important residual risks before production

- External penetration testing and backup/restore drills are not substitutes for unit tests.
- UK and Estonian accountant UAT is pending and may change country mappings.
- e-MTA X-Road access and open-banking regulatory/commercial responsibilities require signed
  agreements. Their production controls remain unavailable until then.
- Malware scanning, rate limiting at the edge (application throttles exist for sign-in,
  sign-up and reset), MFA policy, retention automation, and incident
  alerting must be configured in the managed deployment environment.
