# Estonian payroll demo rules (2026)

This is the agreed 2026 accounting-bureau demo specification. Production
accountant UAT is pending. Only EUR Estonian books and 2026 periods are accepted.
Monthly calculations cover monthly salaries (full- or part-time), hourly pay and
board-member fees, and the social tax minimum obligation. They exclude leave,
sickness, benefits, non-resident cases, TSD submission and payment execution.

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
- Withholding total: pension + employee unemployment + income tax.
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
  existing social-tax accounts (debit 6120, credit 2240) with the memo
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
Delete and recreate a draft to refresh it. One run per organisation/month is
allowed. Approved runs cannot be edited/deleted/reapproved through the service.
Approval posts at calendar month-end and respects configured fiscal-period locks.
One transaction changes status and creates the immutable balanced ledger batch;
a posting failure rolls both back. Existing ledger reversal tools provide linked
accounting corrections; this demo has no payroll amendment workflow.

| Account | Debit / credit |
|---|---|
| 6110 Salary expense | Gross debit |
| 6120 Social tax expense | Social tax debit (minimum top-up as its own line) |
| 6130 Employer unemployment expense | Employer UI debit |
| 2210 Employee net payable | Net credit |
| 2220 Payroll income tax payable | Income tax credit |
| 2230 Employee pension and unemployment payable | Pension + employee UI credit |
| 2240 Employer payroll taxes payable | Social tax + employer UI credit (minimum top-up as its own line) |

The migration adds these accounts to existing EE charts and organisation creation
adds them to future EE books. UK charts and UK demo books are unchanged.
