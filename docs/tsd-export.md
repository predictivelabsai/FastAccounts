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
TSD records are grouped by recipient and frozen payment type. Base salary and
components with the same type code form one record. Each approved run and
absence-pay payout stores its per-type calculation lines in
`pay_item_tsd_lines` in the approval transaction. Preparing the export
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
2. Pay-run records use the date of the run's non-cancelled salary payout when
   one exists. Otherwise they use the run's frozen payday-rule date, falling
   back to period end for older runs. Approved absence-pay payouts are separate
   records dated on their frozen payout date. TSD is due on the 10th of the
   month following each payment month; a weekend or Estonian public holiday
   moves the due date forward to the next working day. The accountant must
   check payment records before upload.
3. `EMPLOYMENT_SALARY`, `BOARD_MEMBER_FEE` and `CONTRACTOR_FEE` are FastAccounts semantic labels.
   The payroll plan does not specify official e-MTA payment-type codes, and
   these labels are not represented as verified EMTA codes. Services-contract
   remuneration (`income_line`, töövõtulepingu tasu) uses `CONTRACTOR_FEE`;
   its official code mapping is still pending.
4. The XML uses published XBRL GL core element names plus a small FastAccounts
   TSD extension namespace (`urn:fastaccounts:ee:tsd:2026:review-only`). It is
   tested for well-formedness and the documented fields, not against an e-MTA
   schema or test environment.
5. Amounts come from frozen approved TSD lines and remain `Decimal` values.
   Levy rounding residuals go to the largest eligible payment-type record so
   each total matches the approved calculation. No money is recalculated with
   binary floating point.
6. The payer registration number and each frozen payee personal ID are
   required. Migration `0010_tsd_export` snapshots existing identifiers once;
   every new draft snapshots the identifier when the pay run is created.
   Later employee-master edits cannot change the export.

The rule extract is `payroll_tsd_types.py`, transcribed from resident
natural-person rows in EMTA's 18 November 2025 matrix. Current preset defaults
are:

| Preset | VALJAMLIIK | Basis |
| --- | ---: | --- |
| Monthly/hourly base, base adjustment, bonus, overtime and ordinary employment additions | 10 | Legacy code 10 covers wages, supplements and holiday pay |
| Board-member fee | 21 | Legacy code 21; no monthly minimum or unemployment insurance |
| Services contract | 17 | Resident VÕS remuneration |
| Employer sick benefit within the statutory limit | 24 | Excess must be separated as code 10 |
| Termination compensation | 33 | Legacy termination compensation |
| Author, parental, expenses and other deductions | 17, 10 or 16 | Needs accountant confirmation of the legal and tax basis |

The payment-type editor lets an accountant change the code for future items.
Legacy approved runs are reconstructed from their frozen component and employee
context snapshots when all required inputs are present. If a snapshot is
incomplete, the workpaper keeps one record using the frozen base payment type
and displays `Legacy run: per-type split unavailable`. Legacy run values are
never rewritten. Cent-allocation residuals go to the largest eligible record
for the relevant levy. The social-tax minimum top-up goes on the base salary
record, with the matrix eligibility checked.

## Per-payment field mapping

The review CSV header uses these fields in this order. The XML repeats the same fields
as `tsd:*` children of each XBRL GL `gl-cor:entryDetail`.

| Export field | Source or derivation |
| --- | --- |
| `declaration` | Constant `TSD` |
| `annex` | `1` for the currently supported resident-payment scope; `2` is reserved in the mapping table for future non-resident support |
| `payment_record_id` | Frozen TSD line ID, unique per pay-run item and payment type; legacy fallback uses the item ID |
| `pay_run_id` | Tenant-scoped approved `pay_runs.id` |
| `payment_date` | Salary payout date, frozen payday-rule date, legacy period end, or absence-pay payout date |
| `payment_month` | `YYYY-MM` from `payment_date` |
| `filing_deadline` | The 10th day after `payment_date`'s month, moved forward to the next working day when needed |
| `payer_registration_no` | `organisations.registration_no` |
| `recipient_personal_id` | Frozen `pay_run_items.employee_personal_id` |
| `recipient_name` | Frozen `pay_run_items.employee_name` |
| `payment_classification` | FastAccounts display label retained for compatibility |
| `pay_basis` | Frozen `monthly`, `hourly`, `board_fee`, or `income_line` |
| `currency` | Constant `EUR`; the service rejects non-EE/non-EUR books |
| `gross_amount` | Frozen TSD line amount for the payment type |
| `tax_free_minimum` | Exemption 610 allocated to the payment type, capped at its taxable amount |
| `income_tax_base` | Frozen per-type taxable amount plus the exemption allocated to that record |
| `income_tax` | Frozen per-type allocation of the approved income-tax total |
| `employee_unemployment_insurance` | Frozen per-type UI amount |
| `employer_unemployment_insurance` | Frozen per-type employer UI amount |
| `funded_pension` | Frozen per-type II-pillar amount |
| `social_tax_base` | Frozen per-type social-tax base, including any eligible monthly-minimum top-up |
| `social_tax` | Frozen per-type allocation of approved social tax |
| `net_amount` | Approved net allocated across the payment-type records by gross amount |
| `employer_cost` | Per-type gross plus social tax and employer UI |

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

The separate **Legacy Annex 1 CSV upload** is a resident Part A row per frozen
recipient and payment type. It contains codes 1000, 1010, 1020, 1030, 1040,
1050, 1060-1090, 1100-1140 and 1150-1170. The 2024 Annex 1 guide does not
define code 1040 and does not mention it between 1030 and 1050, so the column
is kept blank. Code 1050 (A1/E101 country) is blank because the payroll snapshot
does not record an A1 certificate. Codes 1070 and 1080 are zero because the
payroll engine does not model those adjustments. Code 1090 contains only a
positive frozen social-tax base excess above actual eligible payments. Codes
1150/1160 contain exemption 610 when present. Code 1170 uses frozen withheld
income tax, except payment types for which the guide excludes it.

The guide defines the code meanings but does not specify an upload delimiter or
number format. The upload file therefore uses semicolon delimiters, UTF-8
without a BOM, and dot-decimal monetary amounts with exactly two decimal
places. This is an implementation assumption and must be checked with e-MTA.
This upload export is available only through payment month December 2027. The
earlier internal review CSV remains available as `export.csv`.

The accountant workpaper is available on screen and as XLSX, with payment list,
payment-type and recipient views, month filter, record count, frozen levy
totals and legacy-run warnings. The workbook has `Summary`, `Payments`, `By
payment type` and `By recipient` sheets. UI totals combine employee and
employer amounts.

## Submission boundary

`EMTATSDExportProvider.submit()` always raises `PermissionError`. There is no
X-tee client, SOAP client, e-MTA session, upload call, confirmation call, or
status polling in this implementation.


## APA TSD XBRL GL example mapping (4b step 1)

Source: vendored `tests/fixtures/emta/APA_TSD_lahteandmed_ariuhingule_naide_XML_20251017.xml`, checked against taxonomy extract `APA_TSD_TAKSONOOMIA_20251017.txt` (general fields and EE0201001 columns) and developer guide `APA_TSD_juhend_arendajale_sh_kalkulaatorteenus_20260130.txt` (sections 1.3-1.4). The XML example deliberately covers conditional fields and several scenarios; conditional fields are emitted only when the frozen payout data supports them. Required means required for the supported resident cash-pay scenario, following the taxonomy's EE0201001 column and guide. Optional includes conditional and example-only fields.

| Example XML path (namespace prefix) | Meaning in taxonomy / guide | Requirement | FastAccounts source for one payout |
| --- | --- | --- | --- |
| `xbrli:xbrl` | XBRL instance root | Mandatory | Constant document envelope |
| `xbrll:schemaRef/@xlink:href`, `@xlink:arcrole`, `@xlink:type` | Reference to XBRL GL presentation taxonomy | Mandatory in example skeleton | Vendored example constants |
| `xbrli:context/@id`; `xbrli:entity`; `xbrli:identifier/@scheme`; `xbrli:period/xbrli:instant` | Reporting entity and instant context | Mandatory | Organisation registry code; payout date |
| `xbrli:unit/@id`; `xbrli:measure` | Currency and pure-number units | Mandatory in skeleton | EUR and count unit constants |
| `gl-cor:accountingEntries/gl-cor:documentInfo/gl-cor:entriesType` | Entry transaction type; payroll uses `other` | Mandatory | Constant `other` |
| `gl-cor:uniqueID` | Unique report identifier | Mandatory | Stable ID from organisation, payout ID and version |
| `gl-cor:language` | Report language, ISO 639 code | Mandatory | Constant `iso639:et` |
| `gl-cor:creationDate` | Report creation date | Mandatory | Frozen payout export date |
| `gl-bus:creator` | Contact or creating unit | Optional | Omitted; no suitable frozen source |
| `gl-cor:entriesComment` | Report purpose/comment | Optional | Constant APA TSD payment comment |
| `gl-cor:periodCoveredStart`, `gl-cor:periodCoveredEnd` | Start and end of reporting period | Mandatory | Payout date for both (one transaction per file) |
| `gl-bus:sourceApplication` | Accounting software name | Mandatory | Constant `FastAccounts` |
| `gl-muc:defaultCurrency` | Report currency, `iso4217:eur` | Mandatory | Constant EUR |
| `gl-cor:entityInformation/gl-bus:organizationIdentifiers/gl-bus:organizationIdentifier` | Reporting legal entity identifier | Mandatory | Tenant-scoped organisation registration number |
| `gl-bus:organizationDescription` | Identifier type; example uses `ARIREGISTRIKOOD` | Mandatory | Constant `ARIREGISTRIKOOD` |
| `gl-cor:entryHeader/gl-cor:entryNumber` | APA section identifier; payroll taxes section is `EE0201001` | Mandatory | Constant `EE0201001` |
| `gl-cor:entryHeader/gl-cor:entryDetail/gl-cor:lineNumber` | Detail identity | Optional for periodic section; supplied in sample | Deterministic payout line index |
| `gl-cor:lineNumberCounter` | Sequential detail number within section | Mandatory in example pattern | One-based detail index |
| `gl-cor:account/gl-cor:accountSub/gl-cor:accountSubID` + `gl-cor:accountSubType` | Codelist code and codelist identifier | Mandatory; payment type and operation type | Frozen payment type (`VALJAMLIIK2023ap`) and `R` (`TOIMINGUTYYP2023ap`) |
| `gl-cor:accountSub/gl-cor:segmentParentTuple/gl-cor:parentSubaccountCode` + `gl-cor:parentSubaccountType` | Related code pair for country/role composite codelists | Optional; sample's A1/foreign-work cases | Omitted for resident-only records until supported source exists |
| `gl-cor:amount` | Gross payment amount, two decimal places | Mandatory | Frozen TSD line gross `Decimal` |
| `gl-bus:allocationCode` | Access-control/allocation code | Optional | No source; omitted |
| `gl-cor:identifierReference/gl-cor:identifierCode` | Payee personal or MTA non-resident identifier | Mandatory | Frozen employee personal ID |
| `gl-cor:identifierDescription` | Identifier type codelist, `ISIKUKOOD` or `MRR_KOOD` | Mandatory with identifier | `ISIKUKOOD` for supported resident scope |
| `gl-cor:documentDate` | Payment execution date | Mandatory | Salary or absence payout date |
| `gl-bus:measurable/gl-bus:measurableID` + `gl-bus:measurableIDSchema` | Calculation event code and codelist (`TSD01`, `SYNDMUS2017ap`) | Mandatory for supported payroll detail | `TSD01`, `SYNDMUS2017ap` |
| `gl-bus:measurableStartDateTime` | Date of calculation/payroll obligation | Conditional | Frozen calculation date when available; otherwise omitted |
| `gl-bus:measurableDescription` + `gl-bus:measurableQuantity` | Measured tax base or exemption; descriptions use `MEASURABLEDESCRIPTION_enum` (e.g. `MVT_610`, `MVT_650`, `TSD_SMVM`) | Conditional, by applicable tax/base | Frozen exemption, social-tax base, and other supported bases as separate pairs |
| `gl-cor:taxes/gl-cor:taxAmount` + `gl-cor:taxCode` | Tax amount and `TAXCODE_enum` code | Conditional, one pair per non-zero applicable levy | Frozen income tax (`TSD_KTM`), social tax (`TSD_SM`), employee pension (`TSD_KP`), employee unemployment (`TSD_TK`), employer unemployment (`TSD_TTK`) |
| `gl-cor:taxes/gl-cor:taxPercentageRate` | Applicable tax rate | Conditional | Frozen rate only if stored; otherwise omitted |

The example contains non-resident, foreign-work/A1 and other conditional variants. The supported exporter emits the resident fields above only. It must not infer country roles, allocation codes, tax-rate metadata, or calculation timestamps absent from the frozen payout snapshot. Each output file represents exactly one payout transaction, as specified by the developer guide's file examples and transaction-level upload model.
