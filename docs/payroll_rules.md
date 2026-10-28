# Estonian payroll demo rules (2026)

This is the agreed 2026 accounting-bureau demo specification. Production
accountant UAT is pending. Only EUR Estonian books and 2026 periods are accepted.
Monthly calculations cover monthly salaries (full- or part-time), hourly pay,
board-member fees, income-line services-contract pay and the social tax minimum
obligation. They exclude automatic
leave and sickness calculations, benefits, non-resident calculations, direct TSD
submission and payment execution. Bureau-entered payment components can represent
additional remuneration and net deductions. Reviewed resident-only TSD manual-upload
files are documented in
[`tsd-export.md`](tsd-export.md).

All calculations use Decimal, with ROUND_HALF_UP to cents on each tax/deduction.
Each employee's rounded amounts are then summed; aggregate taxes are not recomputed.

- Pay basis (`pay_basis`): `monthly` (gross = `gross_salary`), `hourly`
  (gross = `hourly_rate` × hours entered on the pay run, rounded to cents) or
  `board_fee` (board-member fee; kept in step with `board_member`), or
  `income_line` (zero base pay; reviewed income components provide the gross).
- Work-time fraction (`fte`, 0 < FTE ≤ 1, default 1) records part-time work
  (osakoormus). It pro-rates the monthly minimum wage; it does not change pay.
- Funded pension (II pillar): 0%, 2%, 4% or 6% of gross, default 2%. 0% is for
  anyone who has not joined or has left the II pillar (not only board members).
- Employee unemployment insurance: 1.6%; employer unemployment: 0.8%.
  The supplied specification freezes those rates through 2028; this demo only
  accepts 2026 periods and does not extend other rules to later years.
- Income tax: 22% of max(0, gross - pension - employee unemployment - exemption).
- Exemption: up to EUR 700 monthly on the employee's effective application
  (maximum, limited amount, or none). The legacy boolean remains compatible.
  It is an allowance, not a deduction.
  `tax_free_minimum` records the amount actually used, capped at
  gross − pension − employee unemployment (e.g. 688.80 on a EUR 700 part-time salary).
- Withholding total: pension + employee unemployment + income tax + net deductions.
- Net pay: gross - withholding total.
- Employer social tax: 33% of the social tax base (`social_tax_base`), which is
  the gross pay, or the 2026 monthly minimum base of EUR 886 when that is higher
  (see below). Employer cost: gross + social tax + employer unemployment.
- Board members: no unemployment insurance on either side; pension defaults to
  zero when omitted, with 0/2/4/6 explicitly configurable.
- Minimum wage (Vabariigi Valitsuse 23.03.2026 määrus nr 36): EUR 886/month and
  EUR 5.31/hour for January–March, EUR 946/month and EUR 5.67/hour from April.
  Monthly employees must earn at least the monthly minimum × FTE (EUR 473.00 at
  0.5 FTE from April); hourly employees need an hourly rate of at least the hourly
  minimum. Board fees have no minimum. Draft creation rejects the entire run with
  an explanatory 422 naming the employee if anyone falls below the minimum, or
  if an hourly employee has no valid hours (0 < hours ≤ 744, two decimals).
- Employees with `employment_start_date` after the month or
  `employment_end_date` before it are left out of that month's run.

## Social tax minimum obligation (sotsiaalmaksu miinimumkohustus)

Sources (checked 2026-10-08): EMTA "Sotsiaalmaks", updated 20.07.2026
(<https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/sotsiaalmaks>),
section "Erandjuhud, millal tööandja ei pea täitma minimaalse sotsiaalmaksu
kohustust"; EMTA "Maksumäärad"; sotsiaalmaksuseadus (SMS) § 2 lg 2–4 and § 2¹;
rahandusministri 15.03.2013 määrus nr 17 (§ 2 lg 1, § 5).

- The employer pays social tax on at least EUR 886 per month for 2026
  (EUR 292.38). The shortfall `social_tax_minimum_topup` = 33% × base − 33% ×
  gross is an employer cost. On approval it is posted as a separate line on the
  mapped social-tax expense and accrual accounts (default debit 6120, credit 2253) with the memo
  "Sotsiaalmaksu miinimumkohustuse lisamakse YYYY-MM".
- Partial month: when employment starts or ends during the month, the minimum
  base is pro-rated by calendar days employed (886 / days in month × days,
  rounded to cents; SMS § 2 lg 3, as in EMTA's worked examples).
- Board-member fees: never subject to the minimum (it applies to employees and
  officials, määrus nr 17 § 2 lg 1). Items record the reason `board_member`.
- Per-employee exemption `social_tax_minimum_exemption` (social tax on actual pay only):

| Code | Exception | Basis |
|---|---|---|
| `state_pension` | Receives a state pension (riikliku pensioni saaja) | SMS § 2 lg 4 p 6 |
| `reduced_work_ability` | Partial or no work ability under the Work Ability Allowance Act | SMS § 2 lg 4 p 6 |
| `child_care` | Raising a child under 3, or three or more children under 19 | SMS § 2 lg 4 |
| `student` | Pupil or student | SMS § 2 lg 4 |
| `previously_unemployed` | Registered unemployed ≥ 6 months in the 12 months before hiring (applies for 12 months) | SMS § 2 lg 4 p 5 |
| `shortened_working_time` | Shortened working time (minors aged 7–17, teachers) | SMS § 2 lg 4 |
| `local_council_member` | Local council member | SMS § 2 lg 4 |
| `ship_crew` | Ship crew on a vessel meeting TuMS § 13 lg 5 or 6 | SMS § 2 lg 4 |
| `foreign_service_spouse` | Spouse/partner allowance under the Foreign Service Act § 67 | SMS § 2 lg 4 |
| `long_term_sick_leave_work` | Working on a long-term sick-leave certificate | SMS § 2 lg 3 p 1 |
| `absent_whole_month` | Absent the whole month: leave (except unpaid leave by agreement), incapacity, strike, conscript service, employee representation | SMS § 2 lg 3 p 1 |
| `multiple_employers` | Several employers and another employer applies the basic exemption; that employer carries the minimum | määrus nr 17 § 5 |

`multiple_employers` is rejected when this employer applies the basic exemption.
Not implemented (left to the accountant): the exemption-applying employer's
reduced minimum (886 minus the other employer's pay, määrus nr 17 § 5), and the
Töötukassa relief for reduced-work-ability employees (state pays 20% of 886 and
the employer pays 33% only above 886, SMS § 6 lg 3, TSD code 1070).

## Sample employees (October 2026)

The `Demo OÜ (sample payroll)` seed organisation and
`tests/test_payroll_part_time_hourly.py` use seven synthetic employees:

| Employee | Pay | II pillar | Exemption | Gross | Income tax | Net | Social tax | Employer cost |
|---|---|---:|---|---:|---:|---:|---:|---:|
| Mari Tamm | EUR 946 monthly, 1.0 FTE | 2% | yes | 946.00 | 46.63 | 865.31 | 312.18 | 1,265.75 |
| Jaan Kask | EUR 2,400 monthly | 2% | no | 2,400.00 | 508.99 | 1,804.61 | 792.00 | 3,211.20 |
| Kadri Saar | EUR 3,800 monthly | 4% | no | 3,800.00 | 789.18 | 2,798.02 | 1,254.00 | 5,084.40 |
| Andres Mets | EUR 5,500 monthly | 6% | no | 5,500.00 | 1,118.04 | 3,963.96 | 1,815.00 | 7,359.00 |
| Liis Kuusk | EUR 700 monthly, 0.5 FTE | 0% | yes | 700.00 | 0.00 | 688.80 | 292.38 (min. base 886; top-up 61.38) | 997.98 |
| Peeter Oja | EUR 8.00 × 176 h | 2% | yes | 1,408.00 | 144.61 | 1,212.70 | 464.64 | 1,883.90 |
| Toomas Rebane | EUR 1,500 board fee | 2% | no | 1,500.00 | 323.40 | 1,146.60 | 495.00 | 1,995.00 |
| **Total** | | | | **16,254.00** | | **12,480.00** | | **21,797.23** |

## Worked examples

For gross EUR 2,000 and pension 2%:

| Component | Without exemption | With EUR 700 exemption |
|---|---:|---:|
| Gross | 2,000.00 | 2,000.00 |
| Pension | 40.00 | 40.00 |
| Employee unemployment | 32.00 | 32.00 |
| Taxable after exemption | 1,928.00 | 1,228.00 |
| Income tax | 424.16 | 270.16 |
| Withholding total | 496.16 | 342.16 |
| Net | 1,503.84 | 1,657.84 |
| Employer social tax | 660.00 | 660.00 |
| Employer unemployment | 16.00 | 16.00 |
| Employer cost | 2,676.00 | 2,676.00 |

The request's no-exemption figures 422.72 and 1,505.28 conflict with its formula:
1,928 × 22% = 424.16. The implementation and tests use the formula above.

## Workflow and API representation

All routes are under `/api/organisations/{organisation_id}`. Membership and
existing role/CSRF checks apply. Money and percentages are decimal strings in
responses; booleans are JSON booleans. Employee create defaults pension to 2%
(or 0% for a board member if the field is omitted). PATCH changes supplied fields
only; null is allowed for email/personal_id only.

`GET/POST /employees`, `PATCH /employees/{employee_id}`;
`GET/POST /pay-runs`, `POST /pay-runs/{run_id}/approve`,
`DELETE /pay-runs/{run_id}`, `GET /pay-runs/{run_id}/payslips.pdf`.
Creation returns 201, draft deletion 204, missing records 404, unauthorized
membership 403, validation 422, duplicate names/periods or invalid state 409.
Run responses include `items`, totals, status, period and `posted_batch_id`.
Each item includes `withholding_total`, frozen `employee_name`, `gross_salary`,
`funded_pension_percent`, `pay_basis`, `fte`, `hourly_rate`, `hours`,
`minimum_wage`, `social_tax_base`, `social_tax_minimum_topup`,
`social_tax_minimum_exemption`, and all calculated components.
`POST /pay-runs` accepts `{"period": "2026-10", "hours": {"<employee_id>": "176"}}`;
hours are required for every active hourly employee. Employee fields added in
migration 0006: `pay_basis`, `fte`, `hourly_rate`, `social_tax_minimum_exemption`,
`employment_start_date`, `employment_end_date`; `gross_salary` is empty for hourly staff.

A draft snapshots active employees; later employee changes do not rewrite it.
Hours and payment components can be edited on each draft item; totals are
recomputed atomically from frozen base pay, allowance application, employment
dates and levy settings. Delete and recreate a draft to refresh employee details. One run per organisation/month is
allowed. Approved runs cannot be edited/deleted/reapproved through the service.
Approval posts at calendar month-end and respects configured fiscal-period locks.
One transaction changes status and creates the immutable balanced ledger batch;
a posting failure rolls both back. Existing ledger reversal tools provide linked
accounting corrections; this demo has no payroll amendment workflow.

## Employee lifecycle and draft editing

Archive and unarchive use `PATCH /employees/{id}` with `active=false/true`.
Archived staff remain in existing drafts and approved runs, and are excluded from
new drafts. `DELETE /employees/{id}` permanently deletes only employees with no
`pay_run_items` rows; otherwise the service returns 409 and points to archive.
Archive, unarchive and deletion each create an audit event.

`PATCH /pay-runs/{run_id}/items/{item_id}` accepts `hours` for hourly employees
and/or a complete `components` list. Each line has `type_id`, decimal-string
`amount`, optional name/direction snapshots and six effective boolean flags:
`income_tax`, `social_tax`, `ui_employee`, `ui_employer`, `funded_pension`,
`social_minimum`. Omitted flags inherit the type defaults; the editor sends the
frozen effective flags when saving an existing line. Negative income amounts
allow gross adjustments; deductions must be positive. Invalid or excessive net
deductions roll back the whole save. Gross and every tax base must remain valid,
and monthly gross must retain the snapshotted minimum wage. Hourly gross must
retain the snapshotted hourly minimum multiplied by the entered hours, including
after negative income adjustments. Approval freezes
hours, base pay and component lines.

Types belong to the organisation: `GET/POST /payroll/component-types` and
`PUT /payroll/component-types/{id}`. Editing a type never changes saved lines.
The 27 seeded types are editable bureau defaults, not a substitute for the
accountant's decision for the recipient and payment period. Stable `preset_key`
values identify them independently of editable organisation names. The settings
navigation includes **Payment types / Makseliigid** (`#payment-types`), with the
same add/edit surface as the payroll editor and a link to payroll account
mappings. Owners, administrators and accountants can add named custom categories
and set their direction, liability role and six levy defaults. Custom categories
have no preset key. New income types in this editor start with all levy flags on.
Names and preset-basis descriptions are translated into English, Estonian,
Latvian and Lithuanian. Descriptions describe the preset basis, rather than
claiming to validate later bureau edits to its flags.

| Preset key | Estonian name | Direction | Income tax | Social tax | Employee / employer UI | II pillar | Counts towards social minimum |
|---|---|---|---|---|---|---|---|
| `base_adjustment` | Põhipalga korrigeerimine | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `contract` | Töövõtulepingu tasu | Income | Yes | Yes | Yes / Yes | Yes | No |
| `bailiff` | Kinnipidamine kohtutäiturile | Net deduction | No | No | No / No | No | No |
| `author` | Autori tasu | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `parental` | Vanemapuhkused | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `annual_leave` | Puhkusetasu | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `unused_leave` | Kasutamata puhkuse hüvitis | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `employer_sick_pay` | Tööandja haigushüvitis piirmäära ulatuses | Income | Yes | No | No / No | No | No |
| `overtime` | Ületunnitöö tasu | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `extra_work` | Lisatöö tasu | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `bonus` | Preemia ja boonus | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `thirteenth_salary` | 13. palk | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `public_holiday` | Riigipühal töötamise tasu | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `night_work` | Öötöö tasu | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `rest_day` | Puhkepäeval töötamise tasu | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `standby` | Valveaja tasu | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `substitution` | Asendustasu | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `commission` | Müügitasu | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `study_leave` | Õppepuhkuse tasu | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `average_pay` | Keskmise töötasu säilitamine | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `severance` | Töölepingu lõpetamise hüvitis | Income | Yes | Yes | Yes / Yes | Yes | Yes |
| `expense_reimbursement` | Dokumenteeritud kulude hüvitis | Income | No | No | No / No | No | No |
| `salary_advance` | Väljamakstud palga ettemaks | Net deduction | No | No | No / No | No | No |
| `advance_recovery` | Varasema ettemaksu tasaarvestus | Net deduction | No | No | No / No | No | No |
| `alimony` | Elatise kinnipidamine | Net deduction | No | No | No / No | No | No |
| `union_fee` | Ametiühingu liikmemaksu kinnipidamine | Net deduction | No | No | No / No | No | No |
| `agreed_deduction` | Muu kokkulepitud kinnipidamine | Net deduction | No | No | No / No | No | No |

Treatment references checked 2026-10-25:

- EMTA [Palgatulu](https://www.emta.ee/eraklient/maksud-ja-tasumine/maksustatavad-tulud/palgatulu):
  ordinary employment remuneration and TLS section 84 unused leave compensation
  carry the ordinary employment levies. All ordinary pay supplements in the table
  follow this basis. The catalogue supplies amounts and defaults, with no
  automatic entitlement, average-pay, leave-day or overtime calculation.
- EMTA [Sotsiaalmaks](https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/sotsiaalmaks),
  employer sick-pay section: the sick-pay preset is restricted to qualifying
  employer payments for days 1 to 8 within the statutory average-pay limit and
  backed by a valid certificate. Only income tax is enabled. Days 4 to 8 are the
  ordinary mandatory employer-paid days; days 1 to 3 may be voluntary. The bureau
  must check days, certificate and limit, and enter excess as fully taxable pay.
  This preset does not cover Tervisekassa payments or arbitrary sick-leave top-ups.
- EMTA [documented cost reimbursement, questions 24 and 25](https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/erisoodustused/toolahetuse-kusimused-ja-vastused),
  TuMS section 12(3): documented costs incurred for the employer's business are
  reimbursed with all levies off. This narrow preset excludes per diem allowances,
  private costs, fringe benefits and disguised remuneration. The bureau checks
  supporting documents and avoids duplicating a reimbursement already in books.
- EMTA [Töötuskindlustusmakse](https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/tootuskindlustusmakse):
  statutory termination compensation may be exempt from unemployment insurance;
  general agreed compensation is not universally exempt. The generic severance
  preset, including notice compensation, deliberately defaults to all levies on.
  The bureau must distinguish statutory TLS sections 100/109 payments from agreed
  supplements and confirm both UI flags and social-minimum counting at UAT.

Newly seeded author and employer parental-leave categories now default to fully
taxable income because their payment basis and recipient treatment are uncertain.
Accountant UAT must confirm every applicable levy, the contract and social-minimum
counting. The parental category is employer-side only, not a state benefit or an
assertion of a universal employer entitlement. No maternity or state-paid parental
benefit category is added. Existing organisation defaults, including the earlier
author social-tax demo assumption and parental exemptions, are preserved by the
migration and require bureau review at UAT. Contract-pay recipient flags and
minimum counting also retain their documented UAT requirement.

Standby pay, study-leave pay, retained average wages and general severance use
conservative fully taxable income defaults. The bureau confirms their contractual
or legal basis and social-minimum treatment at UAT. Qualifying sick pay and
reimbursement require the evidence and limits above. No exemption is inferred
from an uncertain payment name. Every income-line flag remains editable per period.

All net deductions leave tax bases unchanged and use `PAYROLL_DEDUCTION`, except
bailiff garnishments, which use `PAYROLL_BAILIFF`. Direct alimony is separate from
bailiff enforcement. The bureau confirms lawful authority and deduction limits.
`salary_advance` recognises an advance already paid for the current period;
`advance_recovery` recovers an earlier advance. Both reduce outstanding net pay,
without executing payment or reducing gross. Never apply both to the same advance.
They use the requested deduction liability role; clearing an already recorded
advance remains the accountant's responsibility.

Migration 0036 inserts missing catalogue entries into existing EE organisations
with `ON CONFLICT(organisation_id,preset_key) DO NOTHING`, reusing the unique
constraint introduced in 0034. Existing names, levy edits, custom types and frozen
payroll or ledger rows remain unchanged. New EE organisations receive the same
catalogue through `payroll_components.seed_types`. SQL migration values are a
versioned snapshot, checked against that catalogue in upgrade tests. UK
organisations receive no payroll types. No historical migration is rewritten.

Income amounts enter each levy base only when that levy flag is on. Pension and
employee UI are rounded on their respective aggregate bases and deducted from
the income-tax base before the allowance and 22% withholding. All income enters
gross and employee net before withholding, even when no tax flags apply.
Employer cost includes gross, social tax and employer UI, excluding net deductions.

The social minimum shortfall is `max(0, pro-rated minimum - minimum-counting pay)`.
Social tax base is social-taxable pay plus that shortfall; the top-up is total
social tax less rounded tax on actual social-taxable pay. Existing exemptions
remove the shortfall obligation, including for author payments. This means that
social tax and minimum-counting flags are deliberately independent. Monthly pay
is not automatically pro-rated. Bureau users must confirm mixed-component
contribution deductibility and the minimum-counting treatment during UAT.

PDFs append translated component detail after the employee payslips, preserving
existing per-employee page links. The Excel book includes a translated component
sheet. Reviewed integration push payloads retain frozen item/component detail;
the existing Merit/SmartAccounts transport remains a balanced GL journal export.

## Reviewed Merit Palk imports

Sources checked 2026-10-24: Merit Palk
[Getting Employee's List](https://api.merit.ee/merit-palk-api/palk-reference-manual/requesting-data-from-merit-palk/getting-employees-list/) and
[Getting Salary and Hours Report data](https://api.merit.ee/merit-palk-api/palk-reference-manual/requesting-data-from-merit-palk/getting-salary-and-hours-report-data/).
The employee endpoint identifies TypeId 5 as a contract of services
(`Töövõtuleping`). FastAccounts maps it to `pay_basis=income_line` with zero
monthly base pay, rather than inferring an employment salary from a tariff.
Reviewed `Töövõtulepingu tasu` or author's-fee income components provide remuneration;
the accountant must confirm their levy flags and recipient circumstances.
The contract-pay preset enables income tax, social tax, both unemployment
insurance flags and funded pension, with social-minimum counting off. These are
editable bureau defaults, not a universal tax decision for every recipient.
This basis carries no automatic employment-contract social minimum. Social tax
on taxable income still follows the component flags. See EMTA
[Sotsiaalmaks](https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/sotsiaalmaks)
and [Maksumäärad](https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/maksumaarad),
with SMS § 2 and the social-minimum rules above; accountant UAT remains pending.

The salary report uses `POST /api/v1/getsalaryreport`, with `StartDate` and
`EndDate` covering the selected month, `Language=EN` and `SortOption=2`.
Its `EmployeeFullName`, `SalaryTypeName`, `Month6`, `Hours` and `Sum` become
reviewed employee-period proposals. The response has no personal-code identity,
so only a unique employee name within the organisation can match. Missing or
ambiguous names stay blocked for review. Salary type names are customisable in
Merit: the base-salary allowlist is `Base salary`, `Monthly salary`,
`Hourly salary`, `Põhipalk`, `Kuupalk` and `Tunnipalk`. An exact existing
component-type name also maps automatically. Unmapped lines remain visible with
warnings. Existing draft components are retained; a collision with an imported
component type blocks apply for manual review to prevent duplicate income. Hourly
base pay differences use the visible base-adjustment component without changing
the hourly rate. New drafts require reviewed hours for every hourly employee;
unselected and rejected proposals do not supply hours.

Apply fills or creates the period's draft through the payroll service, using
Decimal money helpers for gross and component amounts and validated decimal
hours for hourly staff. It preserves the unique period constraint, tenant scope
and repeat-apply idempotency. An identical report is unchanged on repeat import;
a changed report updates the draft using the previous applied payload to identify
source components, while retaining unrelated manual lines. If source component
amounts have been edited locally, apply blocks for review instead of discarding
the edits. Approved runs cannot be changed. Source employer
taxes, dimensions and totals remain review evidence; local payroll rules
calculate the draft's taxes. Merit warns that unpaid salaries can affect report
results, so live PRO reconciliation and accountant acceptance remain required.

Employee-list requests support only the optional exact `PersonalCode` and
`Month6` filters. There is no documented offset, cursor or personal-code range.
The [Merit Palk FAQ](https://api.merit.ee/merit-palk-api/frequently-asked-questions-faq/)
states the 100-record limit for growing lists. FastAccounts fails closed when a
response reaches that ceiling; companies with more than 100 employees must
repeat imports with each exact
PersonalCode. No undocumented paging or silently truncated import is used.

## Month-end posting and TSD reclassification

Migration 0034 adds ten liability roles to EE charts without changing historical
posted batches. The original payroll accounts remain for historical reporting.
Expense roles retain their existing defaults. The following role mappings define
the monthly posting shape; organisations may select their own active chart codes.

| Role | Default code | Month-end debit / credit |
|---|---|---|
| PAYROLL_SALARY | 6110 | Gross salary expense debit |
| PAYROLL_SALARY_PAYABLE | 2250 | Gross credit, all employee withholdings debit |
| PAYROLL_BAILIFF | 2251 | Bailiff garnishment credit |
| PAYROLL_DEDUCTION | 2252 | Other net deductions credit |
| PAYROLL_SOCIAL | 6120 | Social tax expense debit, top-up separately |
| PAYROLL_SOCIAL_ACCRUED | 2253 | Social tax credit, top-up separately |
| PAYROLL_INCOME_WITHHELD | 2254 | Income tax credit |
| PAYROLL_PENSION_WITHHELD | 2255 | Funded pension credit |
| PAYROLL_UI_ACCRUED | 2256 | Employee UI and employer UI credits |
| PAYROLL_UI | 6130 | Employer UI expense debit |

`GET /payroll/posting-mappings` and `PUT /payroll/posting-mappings/{role}` expose
these mappings and the three payable roles below. They reuse migration 0011's
`account_mappings`, with provider `payroll:<lowercase role>` and matching local
and external code fields. A separate provider key per role permits shared target
accounts while preserving provider export mapping uniqueness. The UI's Payroll
accounts dialog lets the organisation select codes such as Sunio's 7001/7500/7550,
2210/2517/2563/2552/2554/2565 and 2320/2330/2340 after adding those chart accounts.

Each approved run has declaration state `none`, `prepared` after the existing
TSD preparation flow, or `settled` after explicit bureau reclassification.
`POST /pay-runs/{run_id}/tsd/settle` creates one separate,
immutable balanced batch dated on the TSD due date: the 10th of the month after
the payment month, moved forward to the next working day when needed:

| Debit accrual role | Credit payable role | Default payable code |
|---|---|---|
| PAYROLL_SOCIAL_ACCRUED | PAYROLL_SOCIAL_PAYABLE | 2257 |
| PAYROLL_INCOME_WITHHELD | PAYROLL_INCOME_PAYABLE | 2258 |
| PAYROLL_UI_ACCRUED | PAYROLL_UI_PAYABLE | 2259 |
| PAYROLL_PENSION_WITHHELD | PAYROLL_SOCIAL_PAYABLE | 2257 |

An approved run with zero tax liabilities can be marked settled by the same
explicit action without creating a zero-value journal; it retains a null
`declaration_batch_id` and an audit explaining that no liability existed.

The bureau may prepare TSD outside FastAccounts, so reclassification does not
require the in-app file preparation flow or frozen personal IDs. In-app
preparation remains available independently. The action is never automatic on
payroll approval or payment posting. Settlement
means this reclassification only; it does not claim a bank payment or EMTA
submission. Run responses include `declaration_state`, `declaration_due_date`,
`declaration_overdue` and `declaration_batch_id`. The month-end panel lists all
approved periods; the dashboard links to the count overdue after the due date.

Accrual account IDs are frozen at approval so a later mapping change cannot
strand the original liability. Reclassification of runs approved before 0034
debits their original combined legacy liabilities. Both entries respect fiscal
locks, tenant scope and atomic posting. Repeat settlement returns 409. Existing
ledger reversals remain the correction mechanism; there is no payroll amendment
or declaration-unsettling workflow. UK charts and books are unchanged.

## Rule selection

`payroll_rules.rules_for(date)` returns a frozen, year-specific rule set. Only
verified 2026 values are configured. Unsupported years fail validation with a
translated message; no other year inherits 2026 rates. `settlement_date(period)`
is the single settlement-date boundary and currently returns calendar month end.
The legacy `calculate_pay` call without a period retains its 2026 defaults.
The January to March and April onwards minimum-wage values are unchanged.

## Estonian working calendar

`payroll_calendar` uses the Anonymous Gregorian computus for Good Friday,
Easter Sunday and Pentecost Sunday. Working days are Monday to Friday excluding
the Estonian public holidays listed in the module. Full-time norms use eight
hours per working day, reduced by three hours for a working day immediately
before 24 February, 23 June, 24 December or 1 January. For 2026, October is
22 days / 176 hours; February is 19 / 149, June is 20 / 157, and December is
21 / 162. These are calendar norms, before individual schedules or leave.

Company payday histories are effective-dated. `next_month_day` and
`current_month_day` clamp dates beyond the target month's length. A resulting
weekend or public holiday shifts the payday backwards to the previous working
day. `next_month_first_working_day` starts on the first day of the next month
and moves forward to its first working day. The company payroll start date is
stored separately from the dated payday rule history.

Payroll freezes the date selected for its tax calculation on the run. The
resolution priority is an existing salary payout date, the effective payday
rule date, then the period end. A salary payout for an approved run must remain
in the payment month frozen by its calculation; a different month needs a
correction. Draft runs resolve again when created. For each employee and
payment month, approved frozen items consume the applicable maximum or limited
tax-free amount. Later runs in that payment month receive only the remaining
exemption. This aggregation reads frozen approved item values and does not
rewrite earlier calculations.

## Effective-dated employee tax elections

Migration 0037 adds organisation-scoped `employee_tax_settings` histories for
`tax_free`, `pension` and `unemployment`. Initial rows use employment start or
2026-01-01. Legacy exemption booleans become maximum/none applications; pension
rates are retained; employee unemployment insurance starts enabled except for
board fees. A limited application requires a non-negative amount with at most
two decimal places, no greater than that year's verified monthly maximum.

The final calendar day of the run month determines the effective row, including
mid-month changes. There is no daily pro-rating of an application. Before the
first history row, the defaults are no application, no funded pension and
ordinary employee unemployment insurance. The flag affects the employee's
unemployment deduction only; employer unemployment remains payable for ordinary
employment. Board-fee base remuneration retains both automatic UI exclusions.

Draft creation freezes the resolved mode, limit, pension rate, employee UI flag
and source row identifiers alongside the existing pay item context. Draft edits
reuse that snapshot. Later history changes affect newly created runs only.
Approved source rows cannot be edited or deleted. Existing approved amounts are
preserved; the migration does not infer historical elections from current data.

Legacy `apply_tax_free_minimum` and `funded_pension_percent` fields remain readable
and writable. They expose the legacy employee-master values, not a projection of
the latest effective history. Changed values create/update the corresponding
history row. `tax_settings_period` (YYYY-MM) selects its effective run month,
starting on day 1. Without it, writes use the latest existing run month; before
any run they use employment start or 2026-01-01. An unchanged value is a no-op.
A write conflicting with an approved source row fails with 409; use an explicit
later period or add a dated election. Existing drafts retain their snapshot.

## Wage component metadata and absence rules

Migration 0042 adds `is_wage` and `active` to organisation payment types and
freezes `is_wage` on each saved component line. `is_wage` controls inclusion in
average-pay history; changing a type later does not rewrite approved components.
New types default to wage and active. The seeded wage presets are base adjustment,
contract, author, overtime, extra work, bonus, 13th salary, public-holiday work,
night work, rest-day work, standby, substitution, commission, study-leave pay
and average pay. Parental payments, annual leave pay, unused-leave compensation,
employer sick benefit, severance, expense reimbursement and all deductions are
non-wage by default. Bureau users can change the flag for their policy and source
documents. Inactive types are unavailable on new payment lines; saved history
remains valid.

The Estonian Employment Contracts Act (Töölepingu seadus) § 54(3) excludes
national and public holidays from basic leave days; § 55 sets the default basic
leave entitlement at 28 calendar days; § 70(2) sets the vacation-pay deadline as
the penultimate calendar working day before leave unless the parties agree
otherwise. Average pay follows the Government Regulation “Keskmise töötasu
maksmise tingimused ja kord” § 2: wage amounts earned in the six calendar months
before the event month are used, with the regulation's short-service and no-wage
rules to be applied by the average-pay service. Sources: [Employment Contracts
Act](https://www.riigiteataja.ee/akt/123122024006) and [Average Pay
Regulation](https://www.riigiteataja.ee/akt/13191217).

The absence register stores inclusive start and end dates, a document reference
and a comment for each organisation-scoped employee record. Calendar days count
both endpoints. Annual and extended leave days exclude public holidays, while
working days use the Estonian payroll calendar. Other absence types currently
report inclusive calendar days as leave days. An employee cannot have overlapping
absence records. The `permitted_absence` type has an organisation setting for
whether salary continues; it defaults to unpaid. Collective annual leave creates
one separately auditable absence per selected employee.

For monthly employees, the run freezes standard calendar norm days, interrupted
absence working days and resulting worked days. The frozen base salary and
monthly minimum threshold are each multiplied by `worked_days / norm_days`.
The agreed monthly salary already reflects the employee's FTE; the calendar day
ratio therefore applies equally at every FTE. This demo has no employee-specific
weekday schedule, so norm days use the Estonian Monday-to-Friday calendar at the
configured FTE pay. Hourly employees retain the entered hours and hourly amount
unchanged by absences. Run items and payslips display worked days against norm
days.

### Payroll absence calculation parameters

The absence and average-pay service uses the dated statutory rules and the
organisation's explicitly selected absence-pay method. It does not infer tax or
employment-law treatment solely from absence labels. Parameters without a
verified rule are year-versioned and identified in
`payroll_absences_validation.md` under “Needs accountant confirmation”.

## Employee contact and bank details

The employee API and workbook include optional `phone`, `iban`,
`bank_account_owner`, `address` and `date_of_birth`. IBAN input is normalised to
uppercase without whitespace and must pass ISO 13616 mod-97 checksum validation.
Date of birth is derived from a recognisable Estonian personal code when absent;
a supplied valid YYYY-MM-DD date takes precedence. Existing personal codes are
also derived on read when there is no stored date. These employee-master details
use the existing organisation and audit boundary and do not change posted pay.

## History API and editor

`/organisations/{organisation_id}/employees/{employee_id}/tax-settings` supports
GET (all histories, including a `frozen` indicator) and POST (a complete row).
Append `/{setting_id}` for PUT (replace an unused row's date/value, retaining its
kind) or DELETE. A row has `kind`, `start_date` and exactly the relevant payload:

- `tax_free`: `mode` in maximum/limited/none, with `amount` required only for limited.
- `pension`: `rate` in 0/2/4/6.
- `unemployment`: boolean `applies` for employee unemployment withholding.

Duplicate effective dates return 409. Rows referenced by approved payroll cannot
be edited or deleted and return a translated 409. Future-dated and unused rows
can be edited/deleted; this includes rows used only by a draft, whose values are
already frozen. Migration backfill rows are not asserted to represent elections
for old approved runs. Their existing calculation snapshots remain authoritative.

Owner, administrator and accountant roles can write. Viewers and approvers can
read. Every history write requires CSRF. The dialog lists the three histories,
shows protected rows, and edits unused rows inline. Contact/master-data changes
use the existing Save action; history changes save independently. The editor is
read-only for viewers and approvers. Employee UI exclusions do not disable the
employer contribution. Contract components retain their separately reviewed tax
flags, and board-fee base remuneration keeps its automatic exclusions.
