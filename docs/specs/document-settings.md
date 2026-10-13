# Document appearance settings

Date: 2026-10-12. Approved parity slate: P2 item 4.

## Goal and model

Provide per-organisation accent colour, logo and invoice footer settings for
sales invoice and credit note PDFs. The Settings sidebar opens Document
appearance. Existing settings-page helpers and the reminder-rules view are the
interaction references: labelled controls, compact sections, save feedback and
disabled controls for viewers. No independent design reference was supplied.

Migration `0028_document_settings` adds one optional row per organisation,
with a unique organisation foreign key, nullable six-digit hexadecimal accent,
nullable footer of at most 500 characters, nullable logo attachment foreign key
and creation/update timestamps. It seeds nothing and can be rerun safely.
SQLite enforces the colour with GLOB; the existing PostgreSQL adapter translates
that constraint to an anchored regular expression. No sibling PostgreSQL SQL
migrations exist. Existing migration assertions and CI include all 28 versions.

## API and persistence

Member-readable GET and owner/administrator plus CSRF PUT live at
`/organisations/{organisation_id}/document-settings`. PUT accepts only nullable
`accent_colour` and `footer_text`. Absent rows return null appearance values
without creating configuration. The service owns transactions and audit events;
the repository owns organisation-scoped, parameterised queries. Writes lock the
organisation row before upserting, preserving independent logo or text changes.
The audit action is `document_settings.updated`.

The `/logo` child endpoint supports member-readable GET, privileged multipart
POST and privileged DELETE. PNG and JPEG uploads are limited to 512 KiB, with
matching MIME type, magic bytes and filename extension. Logo files use existing
organisation-owned evidence storage and SHA-256/size integrity checks. Removing
or replacing a logo clears the settings reference before deleting its attachment
row and file. Settings and evidence audit records share the write transaction.
Failure cleanup removes newly written files when the database operation fails.

## Rendering and limits

The invoice, organisation and appearance settings can be read on the caller's
transaction, including invoice email delivery. An accent changes only the title
word. A verified logo is drawn above the top-right number line, bounded by
140 by 40 points with its aspect ratio preserved. Broken, missing or unreadable
logo content is skipped silently. A grey Helvetica 7.5 footer appears at the
bottom-left of every page, including overflow pages. Without appearance settings,
the drawing operations remain unchanged. ReportLab invariant output removes
variable timestamps and document IDs so unchanged inputs yield identical bytes.

These are appearance settings, not editable PDF templates. Invoice labels remain
English; Helvetica and the established document layout remain in use. Payroll,
statements, arbitrary image types, real accounting data, provider calls and
general document redesign are outside scope. Live PostgreSQL and independent
native-language copy review remain follow-ups.

## Files and acceptance checks

- `document_settings.py` and `document_settings_repository.py`: defaults,
  validation, locked writes, logo lifecycle and audit.
- `migrations/sqlite/0028_document_settings.sql`, `database.py` and CI:
  additive rerun-safe schema, PostgreSQL colour constraint and 28 versions.
- `organisations.py`, `documents.py`: transaction-aware appearance reads,
  organisation evidence ownership and deterministic branded sales PDFs.
- `api_app.py`: strict payloads, read/write roles, CSRF and bounded uploads.
- `static/app.js`, `web/public.py`, `web/i18n.py`, four locale files:
  settings navigation, save/upload/remove flows and matching catalogue keys.
- `tests/test_document_settings.py` and existing migration/catalogue tests:
  validation, tenancy, access, integrity, cleanup, concurrency, audit, PDF
  defaults/branding, migration reruns and four-language workspace flows.
- `docs/change_log.md`, `docs/product_roadmap.md`: paired dated delivery,
  validation counts and complete four-language copy-QA records.

Acceptance commands: focused document-settings tests, `node --check
static/app.js`, `git diff --check`, new-copy punctuation and attribution checks,
then the full `python -m pytest -q`. Use synthetic data and offline fixtures.
Commit only after green checks on `feat/document-settings`, directly stacked on
`feat/mfa` at `332cc30`. Do not push or touch the two excluded untracked files.

## Work allocation

Three independent implementation scopes cover backend persistence/API,
workspace/catalogues and tests. The integration scope covers PDF rendering,
this specification, paired delivery records and final full-suite validation.
All work stays on the requested branch and receives integration review before
the single final commit.

## File-by-file change summary

| File | Change |
| --- | --- |
| `.github/workflows/ci.yml` | Append migration 0028 to the exact inline upgrade list. |
| `api_app.py` | Settings and logo routes with role guards, CSRF and strict input validation. |
| `database.py` | Translate the SQLite colour GLOB CHECK for PostgreSQL. |
| `docs/change_log.md` | Dated delivery record, validation counts and complete four-language copy-QA table. |
| `docs/product_roadmap.md` | Paired scope, validation and four-language copy-QA record. |
| `docs/specs/document-settings.md` | Data model, endpoint/rendering limits, acceptance and full file list. |
| `document_settings.py` | Settings validation, defaults, audited writes and verified logo lifecycle. |
| `document_settings_repository.py` | Organisation lock, tenant-scoped reads and settings/logo persistence. |
| `documents.py` | Transaction-aware invoice reads, organisation evidence and branded deterministic PDFs. |
| `migrations/sqlite/0028_document_settings.sql` | Rerun-safe appearance table with nullable colour/footer/logo and constraints. |
| `organisations.py` | Expose transaction-aware document settings reads. |
| `static/app.js` | Document appearance form, logo preview/upload/removal and viewer gating. |
| `tests/test_automation.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_bulk_sending.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_cash_flow.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_document_settings.py` | 42 offline API, persistence, PDF, migration, locale and browser checks. |
| `tests/test_fx_rates.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_fx_realised.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_fx_revaluation.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_master_data_import.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_mfa.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_migrations_and_tenancy.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_objects.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_payment_links.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_payroll.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_payroll_part_time_hourly.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_periodisation.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_postgres_optional.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_prepayments.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_public.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_quotes.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `tests/test_reminder_rules.py` | Extend exact migration count/list or locale-tail expectations for document settings. |
| `web/i18n.py` | Merge the trailing document_settings locale section. |
| `web/locales/en.json` | Append the matching British English/Estonian/Lithuanian/Latvian appearance copy. |
| `web/locales/et.json` | Append the matching British English/Estonian/Lithuanian/Latvian appearance copy. |
| `web/locales/lt.json` | Append the matching British English/Estonian/Lithuanian/Latvian appearance copy. |
| `web/locales/lv.json` | Append the matching British English/Estonian/Lithuanian/Latvian appearance copy. |
| `web/public.py` | Add Document appearance after Objects in the Settings navigation. |

## Validation results (2026-10-12)

Windows/PowerShell, Python 3.14.6:

- Focused document-settings suite: 42 passed, 1 existing dependency warning in
  38.75s, including all eight four-language owner/viewer browser flows. Both
  revised tests independently checking accent-only and footer-only rendering
  passed after strengthening those assertions.
- Existing document and bulk-email checks: 33 passed, 1 warning in 39.48s.
- Full `python -m pytest -q`: 1313 passed, 4 skipped, 5 warnings in
  1131.25s (0:18:51). The skips are existing PostgreSQL opt-ins; warnings are
  existing dependency deprecations. Tests were not weakened.
- JavaScript syntax, diff, existing-locale preservation, new-copy punctuation
  and attribution checks passed. A synthetic two-page PDF was rendered and
  visually checked for title accent, proportionate logo and footer on both pages.
- All data is synthetic. Browser calls are fulfilled locally. Live PostgreSQL
  and independent native-language copy QA remain follow-ups.
