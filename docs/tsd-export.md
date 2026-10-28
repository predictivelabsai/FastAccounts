# Estonian TSD file export mapping

> **Status: NOT live-verified against e-MTA.** The XML and CSV outputs are
> structurally tested against the mapping documented here, but they have not
> been uploaded to or accepted by e-MTA. Accountant review and manual upload
> are required. Direct submission is disabled.

## Scope and regulatory direction

The implementation follows the direction recorded in
[`payroll-plan.md`](payroll-plan.md): from 1 October 2026, TSD Annexes 1–2 are
data-based and use per-payment XBRL GL XML; the old TSD XML format is invalid.
e-MTA supports XBRL GL file upload, and CSV upload is transitional only through
31 December 2027. The filing deadline is the 10th day of the month following
the payment month. Annexes 3–8 are unchanged and are not produced here.

This is an accountant-facing export from an **Approved** Estonian EUR pay run.
One frozen `pay_run_items` row becomes one payment record. Preparing the export
creates a tenant-scoped `sync_runs` row with provider `emta`, direction `export`,
object type `tsd`, and status `Review Required`. An owner, administrator, or
accountant must mark that preparation reviewed before either file can be
downloaded. Downloading a file does not submit it.

## Assumptions and known limits

1. The payroll engine currently supports resident Estonian calculations only.
   Every generated payment is therefore mapped to Annex 1. The mapping table
   reserves Annex 2 for non-resident payments, but the exporter does not invent
   Annex 2 records from names, personal IDs, or other unreliable inference.
   Non-resident calculation and classification remain outside the payroll
   engine's current scope.
2. The exporter uses the date of the run's non-cancelled salary payout when one
   exists. Otherwise it uses the run's frozen payday-rule date, falling back to
   period end for older runs. TSD is due on the 10th of the month after that
   payment month; a weekend or Estonian public holiday moves the due date
   forward to the next working day. The accountant must check payment records
   before upload.
3. `EMPLOYMENT_SALARY`, `BOARD_MEMBER_FEE` and `CONTRACTOR_FEE` are FastAccounts semantic labels.
   The payroll plan does not specify official e-MTA payment-type codes, and
   these labels are not represented as verified EMTA codes. Services-contract
   remuneration (`income_line`, töövõtulepingu tasu) uses `CONTRACTOR_FEE`;
   its official code mapping is still pending.
4. The XML uses published XBRL GL core element names plus a small FastAccounts
   TSD extension namespace (`urn:fastaccounts:ee:tsd:2026:review-only`). It is
   tested for well-formedness and the documented fields, not against an e-MTA
   schema or test environment.
5. Amounts come from the frozen approved pay-run item and remain `Decimal`
   values rounded by the payroll engine. No amount is recalculated with binary
   floating point.
6. The payer registration number and each frozen payee personal ID are
   required. Migration `0010_tsd_export` snapshots existing identifiers once;
   every new draft snapshots the identifier when the pay run is created.
   Later employee-master edits cannot change the export.

The code-level classification tables are `TSD_PAYMENT_CLASSIFICATION` and
`TSD_ANNEX_MAPPING` at the top of `tsd.py`.

## Per-payment field mapping

The CSV header uses these fields in this order. The XML repeats the same fields
as `tsd:*` children of each XBRL GL `gl-cor:entryDetail`.

| Export field | Source or derivation |
| --- | --- |
| `declaration` | Constant `TSD` |
| `annex` | `1` for the currently supported resident-payment scope; `2` is reserved in the mapping table for future non-resident support |
| `payment_record_id` | Immutable `pay_run_items.id` |
| `pay_run_id` | Tenant-scoped approved `pay_runs.id` |
| `payment_date` | Salary payout date, frozen payday-rule date, or legacy period end |
| `payment_month` | `YYYY-MM` from `payment_date` |
| `filing_deadline` | The 10th day after `payment_date`'s month, moved forward to the next working day when needed |
| `payer_registration_no` | `organisations.registration_no` |
| `recipient_personal_id` | Frozen `pay_run_items.employee_personal_id` |
| `recipient_name` | Frozen `pay_run_items.employee_name` |
| `payment_classification` | Monthly/hourly → `EMPLOYMENT_SALARY`; board fee → `BOARD_MEMBER_FEE` |
| `pay_basis` | Frozen `monthly`, `hourly`, `board_fee`, or `income_line` |
| `currency` | Constant `EUR`; the service rejects non-EE/non-EUR books |
| `gross_amount` | `pay_run_items.gross` |
| `tax_free_minimum` | `pay_run_items.tax_free_minimum` |
| `income_tax_base` | `max(0, gross − funded pension − employee unemployment insurance − tax-free minimum)` using `Decimal` |
| `income_tax` | `pay_run_items.income_tax` |
| `employee_unemployment_insurance` | `pay_run_items.ui_employee` |
| `employer_unemployment_insurance` | `pay_run_items.ui_employer` |
| `funded_pension` | `pay_run_items.funded_pension` |
| `social_tax_base` | `pay_run_items.social_tax_base`, including the payroll engine's minimum-base treatment |
| `social_tax` | `pay_run_items.social_tax` |
| `net_amount` | `pay_run_items.net` |
| `employer_cost` | `pay_run_items.employer_cost` |

Before serialization, the sum of `gross_amount`, `net_amount`, and
`employer_cost` must equal the corresponding approved pay-run totals. A mismatch
stops the export.

## XBRL GL envelope mapping

| XBRL GL element | Value |
| --- | --- |
| `xbrli:xbrl` | Instance root |
| `gl-cor:accountingEntries` | Container for document metadata and payment entries |
| `gl-cor:documentInfo/gl-cor:entriesType` | `journal` |
| `gl-cor:uniqueID` | TSD preparation (`sync_runs`) ID |
| `gl-cor:language` | `et` |
| `gl-cor:creationDate` | Preparation creation date |
| `gl-cor:periodCoveredStart` / `periodCoveredEnd` | Assumed payment date |
| `gl-cor:sourceApplication` | `FastAccounts` |
| `tsd:annexScope` | `1-2`, describing the data-based TSD direction, not claiming that the file contains an Annex 2 payment |
| `tsd:validationStatus` | `NOT_LIVE_VERIFIED_AGAINST_EMTA` |
| `gl-cor:entryHeader` | One per frozen payment record |
| `gl-cor:enteredDate` | Assumed payment date |
| `gl-cor:sourceJournalID` | `TSD-A1` or future `TSD-A2` according to `annex` |
| `gl-cor:entryNumber` | Payment-record ID |
| `gl-cor:entryDetail/gl-cor:lineNumber` | Sequential row number |
| `gl-cor:documentType` | `TSD` |
| `gl-cor:documentNumber` | Pay-run ID |
| `gl-cor:documentDate` | Assumed payment date |
| `gl-cor:detailComment` | FastAccounts semantic payment classification |
| `gl-cor:amount` | Gross amount |
| `gl-cor:debitCreditCode` | `D`, representing the gross payroll expense-side amount in this export envelope |

## CSV transition boundary

The CSV contains the per-payment fields above, encoded as UTF-8 with a BOM for
spreadsheet compatibility. Export is rejected when the assumed payment date is
after 31 December 2027. The CSV is not described as a permanent filing format.

## Submission boundary

`EMTATSDExportProvider.submit()` always raises `PermissionError`. There is no
X-tee client, SOAP client, e-MTA session, upload call, confirmation call, or
status polling in this implementation.
