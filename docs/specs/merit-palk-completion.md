# Merit Palk reviewed payroll inputs

Goal: import the documented monthly salary/hours report into draft payroll and
apply services-contract employees without manufacturing monthly employment pay.

Files: connector, import and payroll services, additive constraint migration,
existing integration/payroll JavaScript, four locales, payroll rules, roadmap,
change log and synthetic Merit Palk tests. Implementation tasks: provider and
reviewed apply; income-line payroll basis; documentation and translations.

Acceptance: unique tenant employee matching, Decimal round trips, draft-only
atomic writes, repeated apply idempotency, explicit unmapped-type warnings,
100-result fail-closed employee pulls with documented exact PersonalCode filter.
Run each requested focused test file separately, JavaScript syntax check, then
one full pytest run capped at 45 minutes. Live PRO and accountant UAT remain open.

Out of scope: payroll approval, live credentials, push, HR and ERP workflows,
and the user's two existing untracked review/demo files. Existing functional UI
patterns are retained; no visual redesign or external design reference applies.
