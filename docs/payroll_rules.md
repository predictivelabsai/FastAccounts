# Estonian payroll demo rules (2026)

This is the agreed 2026 accounting-bureau demo specification. Production
accountant UAT is pending. Only EUR Estonian books and 2026 periods are accepted.
Monthly full-salary calculations exclude leave, sickness, benefits, non-resident
cases, social-tax minimum adjustments, TSD submission and payment execution.

All calculations use Decimal, with ROUND_HALF_UP to cents on each tax/deduction.
Each employee's rounded amounts are then summed; aggregate taxes are not recomputed.

- Funded pension (II pillar): 2%, 4% or 6% of gross, default 2%.
- Employee unemployment insurance: 1.6%; employer unemployment: 0.8%.
  The supplied specification freezes those rates through 2028; this demo only
  accepts 2026 periods and does not extend other rules to later years.
- Income tax: 22% of max(0, gross - pension - employee unemployment - exemption).
- Exemption: flat EUR 700 monthly only on the employee's application
  (`apply_tax_free_minimum=true`), otherwise zero. It is an allowance, not a deduction.
- Withholding total: pension + employee unemployment + income tax.
- Net pay: gross - withholding total.
- Employer social tax: 33% of gross. Employer cost: gross + social tax + employer unemployment.
- Board members: no unemployment insurance on either side; pension defaults to
  zero when omitted, with 0/2/4/6 explicitly configurable.
- Non-board employees must earn at least EUR 886 for January–March and EUR 946
  from April. Draft creation rejects the entire run with an explanatory 422 if
  any active non-board employee falls below the minimum.

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
`funded_pension_percent`, and all calculated components.

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
| 6120 Social tax expense | Social tax debit |
| 6130 Employer unemployment expense | Employer UI debit |
| 2210 Employee net payable | Net credit |
| 2220 Payroll income tax payable | Income tax credit |
| 2230 Employee pension and unemployment payable | Pension + employee UI credit |
| 2240 Employer payroll taxes payable | Social tax + employer UI credit |

The migration adds these accounts to existing EE charts and organisation creation
adds them to future EE books. UK charts and UK demo books are unchanged.
