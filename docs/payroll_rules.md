# Estonian payroll demo rules (2026)

This is the agreed 2026 accounting-bureau demo specification. Production
accountant UAT is pending. Only EUR Estonian books and 2026 periods are accepted.
Monthly calculations cover monthly salaries (full- or part-time), hourly pay and
board-member fees, and the social tax minimum obligation. They exclude automatic
leave and sickness calculations, benefits, non-resident calculations, direct TSD
submission and payment execution. Bureau-entered payment components can represent
additional remuneration and net deductions. Reviewed resident-only TSD manual-upload
files are documented in
[`tsd-export.md`](tsd-export.md).

All calculations use Decimal, with ROUND_HALF_UP to cents on each tax/deduction.
Each employee's rounded amounts are then summed; aggregate taxes are not recomputed.

- Pay basis (`pay_basis`): `monthly` (gross = `gross_salary`), `hourly`
  (gross = `hourly_rate` × hours entered on the pay run, rounded to cents) or
  `board_fee` (board-member fee; kept in step with `board_member`).
- Work-time fraction (`fte`, 0 < FTE ≤ 1, default 1) records part-time work
  (osakoormus). It pro-rates the monthly minimum wage; it does not change pay.
- Funded pension (II pillar): 0%, 2%, 4% or 6% of gross, default 2%. 0% is for
  anyone who has not joined or has left the II pillar (not only board members).
- Employee unemployment insurance: 1.6%; employer unemployment: 0.8%.
  The supplied specification freezes those rates through 2028; this demo only
  accepts 2026 periods and does not extend other rules to later years.
- Income tax: 22% of max(0, gross - pension - employee unemployment - exemption).
- Exemption: flat EUR 700 monthly only on the employee's application
  (`apply_tax_free_minimum=true`), otherwise zero. It is an allowance, not a deduction.
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
The three seeded types are editable bureau defaults, not a substitute for the
accountant's decision for the recipient and payment period:

| Preset | Direction | Income tax | Social tax | Employee / employer UI | II pillar | Counts towards social minimum |
|---|---|---|---|---|---|---|
| Kinnipidamine kohtutäiturile | Net deduction | No | No | No / No | No | No |
| Autori tasu | Income | Yes | Yes | No / No | No | Yes |
| Vanemapuhkused | Income | Yes | No | No / No | No | No |

The author preset's social-tax default is an explicit demo assumption: the
request did not specify that flag. The bureau must confirm it during UAT.
Author and parental-leave rule citations and applicability also need accountant
UAT confirmation. Every income-line flag is editable per period. Net deductions
reduce net pay and credit their chosen deduction liability role; they do not
change tax bases. Bailiff garnishments use a separate liability role.

<!-- EMTA references for bureau UAT, checked 2026-10-23. These sources do not
     establish universal treatment for every author or parental-leave payment.
     https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/sotsiaalmaks
     https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/maksumaarad
     https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/deklaratsiooni-tsd-esitamine -->

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
immutable balanced batch dated the 10th of the following month:

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
The demo uses the literal following-month 10th, without weekend/holiday shifts.

Accrual account IDs are frozen at approval so a later mapping change cannot
strand the original liability. Reclassification of runs approved before 0034
debits their original combined legacy liabilities. Both entries respect fiscal
locks, tenant scope and atomic posting. Repeat settlement returns 409. Existing
ledger reversals remain the correction mechanism; there is no payroll amendment
or declaration-unsettling workflow. UK charts and books are unchanged.
