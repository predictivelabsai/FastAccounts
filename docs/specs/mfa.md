# TOTP two-factor authentication

Date: 2026-10-12. Approved authentication slate: P2 item 3.

## Goal and model

Add optional personal two-factor authentication to the existing account row,
shared by password and Google sign-ins. Domain behaviour lives in
`web/account_auth.py`; the dependency-free engine lives in `web/totp.py`.
[RFC 6238](https://www.rfc-editor.org/rfc/rfc6238) defines the time-based HOTP
calculation. This implementation uses a fresh 20-byte RFC 4648 base32 secret,
HMAC-SHA1, a 30-second step and six decimal digits. Verification accepts the
current step or one step either side, strictly after the last consumed step.
RFC 6238 Appendix B SHA1 vectors are reduced to six digits; RFC 4226 Appendix D
checks the underlying HOTP counters.

Migration `0027_mfa` adds nullable `totp_secret`, integer `totp_enabled` defaulting
to zero and nullable `totp_last_step` to `user_accounts`. Recovery rows have an
account foreign key, a unique account/hash pair, a nullable usage timestamp and
creation timestamp. SHA-256 digests protect 10 random 128-bit recovery codes.
The SQLite runner guards the three column additions for partial upgrades and
retries; table/index creation uses IF NOT EXISTS. PostgreSQL uses the same
additive migration through the existing adapter. Live PostgreSQL is not tested.

## Enrolment and management

The workspace sidebar links to `/mfa`. Existing signed-in sessions remain valid
when MFA changes; `session_version` is never bumped by MFA.

Enrolment requires a verified account, CSRF and the current password. Google-only
users can set a password through the existing reset flow. The pending secret is
stored with MFA disabled. Re-enrolment is refused unless regeneration is explicit
and the password is proved again. A digest in the signed session authorises
viewing that pending secret and activating it. A different or stale setup session
cannot activate a replacement secret. The page provides read-only, selectable
secret and otpauth URI fields. Activation consumes a valid first code and returns
10 recovery codes in one response. Plaintext codes are never placed in a cookie,
log or database, and subsequent page loads cannot retrieve them. The acknowledgement
link returns to management without storing codes.

Disabling requires the password plus a current unused factor. The store rechecks
the password under the account transaction after the route check. It consumes the
factor, deletes unused recovery rows and clears the secret, enabled flag and last
step in one transaction. Regeneration requires the same checks, consumes the
factor and atomically replaces all unused recovery codes. Used hashes remain as
usage records. Account mutations serialise using an account-row write, so concurrent
TOTP/recovery submissions cannot both consume one factor. Failed factor checks
leave enrolment and unused recovery codes unchanged.

## Sign-in challenge

Password, email verification, Google callback and the explicitly enabled local
UAT sign-in route all use the same second-step hook. A valid first factor records
`mfa_pending` with email, random token, creation time, first-factor method, account
session version and validated local return path. It removes any existing user
identity but preserves language and CSRF, without rotating the whole session.

The challenge must be less than 10 minutes old. Access restrictions, account
verification, MFA status and session version are rechecked. A password reset
invalidates pending challenges, including the version check under the account
transaction. CSRF and the pending token protect challenge submissions. Invalid
codes leave the user unauthenticated; expiry clears pending state. Successful TOTP
or recovery-code consumption rotates the whole session through establish_session,
records `password+totp` or `google+totp` (including recovery sign-ins), and honours
only `_safe_return_path` destinations. Recovery codes burn once atomically.

All MFA POSTs use `mfa_email` and `mfa_ip` limits (10/account and 50/IP per 15
minutes). Password checks also reuse the login limits. Factor values are never
logged. Secret and recovery responses set Cache-Control: no-store and
Referrer-Policy: no-referrer. No organisation-scoped audit events are added.

## Threats addressed and limits

The second factor protects future sign-ins when a password is compromised.
CSRF, bounded guessing, session rotation, account scoping and strict monotonic
step consumption address cross-site submissions, brute force, fixation and replay.
Recovery codes provide single-use access when the authenticator is unavailable.

TOTP does not prevent phishing, malware or theft of an already authenticated
session. Existing sessions deliberately remain valid. The requested TEXT secret
is stored in the account database; protecting that database and its backups is
necessary. Lost authenticator plus lost recovery codes has no new bypass here.
Email/OTP push, hardware keys, organisation-wide enforcement, QR rendering,
additional secret encryption and recovery-support workflows are deferred.

## Files and acceptance checks

- `web/totp.py`: RFC vectors, base32 errors, time window and replay refusal.
- `web/account_auth.py`: transactional enrolment, activation, challenge, disable
  and recovery regeneration without session-version changes.
- `web_app.py`: first-factor hook, pending challenges, management POSTs, CSRF,
  throttles, password checks and return-path validation.
- `web/public.py`: auth-family forms, selectable setup fields, one-time recovery
  display and sidebar link. No static/app.js change is needed.
- `migrations/sqlite/0027_mfa.sql`, `database.py`, CI and existing migration
  assertions: 27 migrations, repeated/partial upgrades preserve account data.
- All four `web/locales/*.json` files: auth keys and workspace label, preserving
  the existing trailing feature-section order.
- `tests/test_mfa.py`: offline TestClient and Playwright flows in all four
  languages, rate limits, CSRF, Google callback fake, concurrent factor burns,
  setup permissions, expiry and password-reset invalidation.
- `docs/change_log.md` and `docs/product_roadmap.md`: paired validation records.

Required commands: `python -m pytest tests/test_mfa.py -q`,
`python -m pytest tests/test_fx_rates.py tests/test_fx_realised.py -q`, then
`python -m pytest -q`. All network calls are blocked in MFA tests except the
Windows loopback socketpair used by the local event loop. Browser requests are
intercepted and fulfilled locally. Live provider calls are never used.


## File-by-file change summary

| File | Change |
| --- | --- |
| `web/totp.py` | Standard-library secret generation, HOTP/TOTP, strict replay-safe verification and otpauth URI. |
| `web/account_auth.py` | Account MFA lifecycle, per-account serialisation, hashed recovery codes and MFA rate-limit actions. |
| `web_app.py` | Local/Google/verification/UAT second-step hooks, pending sessions, security routes, CSRF and throttles. |
| `web/public.py` | Auth-family MFA forms and recovery display, workspace link and Google return-path link. |
| `database.py` | Guard existing MFA columns when retrying the SQLite migration. |
| `migrations/sqlite/0027_mfa.sql` | Add three account fields, recovery-code table and account index. |
| `.github/workflows/ci.yml` | Append 0027_mfa to the exact inline migration list. |
| `web/locales/en.json` | Add 22 auth strings and one workspace link label in British English. |
| `web/locales/et.json` | Add the matching Estonian strings, listed in the change log for QA. |
| `web/locales/lt.json` | Add the matching Lithuanian strings, listed in the change log for QA. |
| `web/locales/lv.json` | Add the matching Latvian strings, listed in the change log for QA. |
| `tests/test_mfa.py` | 52 offline checks of engine, lifecycle, replay, concurrency, routing, migration and four-language browsers. |
| `docs/change_log.md` | Dated implementation/validation entry and complete locale copy-QA table. |
| `docs/product_roadmap.md` | Paired authentication-slate delivery and validation entry. |
| `docs/specs/mfa.md` | Data model, flows, threats, deferred scope, acceptance checks and file summary. |
| `tests/test_automation.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_cash_flow.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_fx_rates.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_fx_realised.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_fx_revaluation.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_master_data_import.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_migrations_and_tenancy.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_objects.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_payment_links.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_payroll.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_payroll_part_time_hourly.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_periodisation.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_postgres_optional.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_prepayments.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_public.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |
| `tests/test_quotes.py` | Extend exact upgrade lists/counts or CI assertions to include migration 0027 and count 27. |

## Validation results (2026-10-12)

Windows/PowerShell, Python 3.14.6:

- `python -m pytest tests/test_mfa.py -q`: 52 passed, 1 existing dependency
  warning in 68.68s. All four offline browser enrolment checks passed.
- `python -m pytest tests/test_fx_rates.py tests/test_fx_realised.py -q`:
  126 passed, 1 existing dependency warning in 121.29s.
- `python -m pytest -q`: 1271 passed, 4 skipped, 5 warnings in 1296.31s
  (0:21:36). The skips are existing PostgreSQL opt-ins; warnings are existing
  dependency deprecations. No tests were weakened.
- `git diff --check`, existing-locale preservation and new-copy/attribution
  checks passed. Static/app.js is unchanged, so node --check is not applicable.
- All changes remain uncommitted on feat/mfa. Protected untracked files remain
  untouched. Locale copy QA and live PostgreSQL validation are open follow-ups.
