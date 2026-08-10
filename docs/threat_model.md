# Concise threat model

## Protected assets

Accounting records, evidence, bank data, tax workpapers, OAuth/API credentials, personal
contact data, audit history, and statutory records under retention.

## Trust boundaries and controls

- Browser to app: Google sign-in, invite-only membership, secure signed session, CSRF token,
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
- Malware scanning, rate limiting at the edge, MFA policy, retention automation, and incident
  alerting must be configured in the managed deployment environment.
