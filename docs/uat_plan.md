# Accountant UAT plan

All fixtures are synthetic. Record reviewer, date, evidence, expected/actual result, severity,
and any blocking correction in `docs/uat_results/` (kept empty until real UAT begins).

## Shared bookkeeping journeys

1. Create a company and a sole-trader/FIE organisation; prove a user in one cannot open the other.
2. Create exclusive and inclusive invoices, issue a credit, inspect PDF/XML, and allocate partial
   then final payment. Confirm AR, revenue, tax, aging, and audit trail.
3. Capture a bill and evidence, submit for review, approve, pay, credit, and confirm AP/input tax.
4. Import the same CSV and CAMT.053 twice. Confirm one bank record, review match reasons, reconcile,
   and trace bank transaction → payment → document → ledger.
5. Post and reverse a manual journal; lock a period and prove further posting is rejected.
6. Reconcile trial balance, general ledger, P&L, balance sheet, cash summary, AR/AP aging.

## UK pack

- Validate 20%, 5%, zero, exempt, out-of-scope, and reverse-charge fixtures.
- Validate nine VAT boxes against source documents and the digital audit link.
- Review accrual and cash-basis warnings, CSV export, and HMRC sandbox plan.
- Confirm direct submission cannot run without provider enablement and legal declaration.

## Estonia pack

- Validate 24%, 13%, 9%, zero, exempt, and reverse-charge fixtures and KMD mapping.
- Validate correction documents, Estonian e-invoice review export, and Merit V2 dry-run mapping.
- Reconcile KMD export to ledger and confirm e-MTA direct filing remains disabled pending X-Road.

## Exit rule

The country pack may be labelled “accountant validated” only when a qualified accountant for that
country signs the golden fixtures and all severity-1/2 findings are closed and retested.
