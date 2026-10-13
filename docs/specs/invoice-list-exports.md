# Invoice list exports and filters

P1 item 11, 12 October 2026. Read-only sales invoice and purchase bill lists for
UK and Estonian books, built on the analytical objects branch.

## Selection contract

Existing invoice and bill list GET endpoints accept optional `status`,
`contact_id`, `date_from`, `date_to`, `currency` and `q`. Supplied filters are
combined with AND. Dates are inclusive ISO calendar dates and apply to invoice
issue dates or bill dates. Invalid dates or reversed ranges return 400 on list
and document export routes. Unknown status, contact or currency values return
an empty list. Exact status and currency values retain their stored spelling.
Sales `Overdue` preserves the previous shortcut: Issued or Part Paid with a due
date earlier than today. Search matches document number, reference or contact
name case-insensitively through database LOWER, with literal LIKE wildcards.
Non-ASCII case folding follows the configured database's LOWER behaviour.

`invoice_list_repository.py` owns parameterised SQL with organisation predicates
on both the document and contact join. `invoice_list.py` owns date validation,
shared selection and export rendering. Thin API handlers apply the existing
membership role gate. Every book role, including viewers, can read or download;
non-members cannot. No accounting workflow or persisted state changes.

## Downloads and workspace

`/organisations/{id}/invoices/export.csv` and `export.xlsx`, and matching bill
routes, honour exactly the list filters. CSV uses UTF-8 with a BOM, standard
quoting and two-place Decimal money. Excel uses existing `excel_export.py`
helpers, bold headings and numeric money cells. Both include number, reference,
contact, document date, due date, currency, net, VAT, gross, paid and status.
Text cannot execute spreadsheet formulas. Each kind gets one worksheet; mixed
currency amounts are not added together. The established invoices report XLSX
route also gains all filters while retaining its established layout.

The existing SPA lists have status, customer/supplier, date range, search and
currency controls. A committed field change re-requests the view using its
existing fetch/render pattern. Filter values survive view refreshes and are
kept separately per organisation and document kind for the current session.
CSV and Excel links carry the same current query. Controls have labels and
adapt to narrow screens. Existing catalogue labels are reused; new copy is
appended in `invoice_exports` in all four locales and merged by APPEND_SECTIONS.

## Acceptance and limits

`tests/test_invoice_list_exports.py` checks both country/kind combinations,
every filter, combinations, number/reference/contact search, literal wildcards,
tenant joins, CSV quoting and amounts, Excel values and numeric styles, formula
text, unknown values, invalid dates, viewer access and non-member rejection.
Existing payment-link and periodisation locale-tail assertions are extended
for the appended feature section; the prepayment browser status assertion is
scoped to table rows to exclude the filter option. Offline Playwright checks exercise all controls
and download queries in four
locales, escaped input and mobile containment. Run the full pytest suite and
`node --check static/app.js` before marking the roadmap and change log complete.

No migration, dependency, live network call, saved filter system, per-user
columns or expanded spreadsheet formatting is introduced. Persisted preferences,
large-list pagination/streaming and production accountant UAT remain follow-ups.
