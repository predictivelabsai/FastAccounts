# Analytical objects

P1 item 10, 12 October 2026. Analytical objects categorise income and costs for
UK and Estonian books. They are accounting dimensions, not CRM, HR or project
management records.

## What already existed

The `feat/payment-links` base had immutable balanced `PostingLine` postings,
invoice and bill lines, manual journal API posting, trial balance, general ledger
and P&L reports, including calendar-aligned P&L comparisons. It had no `projects`
table, `list_projects` service, `projects_project_id`, `projects_location_id` or
`projects_person_id` fields, object CRUD, report dimension filter or form
selectors. A similarly named sibling-server tool is not part of this repository.
Quotes, purchase periodisation and payment methods supply the existing service,
repository, role, CSRF and Settings-dialog conventions used here.

## This change

- Migration `0023_analytical_objects.sql` creates one tenant-scoped `objects`
  catalogue with project, location, person and generic object types; code, name,
  notes, active status and timestamps. Codes are unique within organisation and
  type. All parent composite foreign keys have matching unique indexes.
- Nullable `projects_project_id`, `projects_location_id`, `projects_person_id`
  and `projects_object_id` fields are accepted on invoice, bill and manual journal
  API lines and on `PostingLine`. To keep the migration additive and directly
  rerunnable on SQLite and PostgreSQL, the persisted fields live in
  `invoice_line_objects`, `bill_line_objects` and `gl_entry_objects` companion
  tables. Existing parent tables and posted ledger rows are not rebuilt or
  rewritten. Document reads and general ledger results include the dimension IDs.
- Composite foreign keys enforce organisation, parent line and dimension type.
  Companion rows become immutable with their posted parent, including insertion
  of a tag onto an already posted line. PostgreSQL trigger definitions are
  substituted by the existing migration runner convention.
- Object reads are available to all book members. Catalogue creation, editing
  and deletion require owner or administrator membership and CSRF protection.
  Mutations are audited and serialised with dimension posting on the organisation.
  Referenced objects cannot be deleted or change type, even on a draft document;
  deactivate them instead. New assignments require active objects. Already saved
  document tags, reversals and periodisation retain inactive historical objects.
- Invoice revenue is grouped by account and all four dimensions. Bill net costs
  and non-recoverable VAT retain each line's dimensions. Credit notes and supplier
  credits retain explicitly supplied tags. VAT control, AR and AP lines remain
  untagged. Whole batches remain balanced; a dimension-filtered trial balance
  is an analytical subset and need not balance.
- Purchase deferral and later expense portions preserve dimensions from the bill.
  Decimal penny allocations use remaining dimension totals, cap allocations at
  remaining costs and exhaust them exactly by the final period. Recurring invoices inherit tags
  from the original template invoice by line number.
- `object_id` filters trial balance, general ledger and P&L by a single catalogue
  object across its matching dimension. Unknown or foreign IDs fail. P&L applies
  the same filter to current and comparative periods in all comparison modes.
- Objects appears under Settings, with list, create/edit dialog, active checkbox
  and confirmed deletion. Existing single-line invoice/bill forms have optional
  dimension selectors. The report selector includes inactive historical objects.
  All four locale files append `analytical_objects`, merged by `APPEND_SECTIONS`.

## Acceptance checks

`tests/test_objects.py` covers CRUD, audit, roles, CSRF, tenant and type isolation,
draft references, invoice/bill/journal tagging, credit notes, reversal history,
locked periods, idempotency, report comparisons, periodisation penny allocation,
locale merging and upgrade/rerun preservation. `tests/test_objects_browser.py`
exercises management, invoice/bill tagging, report filtering and comparison,
confirmation and mobile dialog containment in English, Estonian, Lithuanian and
Latvian. Run the full suite with Python 3.12.14: `python -m pytest -q`.

## Deferred scope

Object merging, multiple objects within one dimension, combined dimension
filters, a standalone manual journal SPA editor, quote and recurring-template
dimension authoring, dimension-specific exports and production UAT are outside
this item. Existing untagged postings are not backfilled. Recurring schedules retain their
existing amount snapshot and use the original invoice for dimension inheritance.
PostgreSQL execution remains an explicit opt-in.
