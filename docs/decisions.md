# Implementation decisions

## 2026-10-24: Merit Palk payroll input completion

Use the existing staged review and draft payroll editor. Salary reports expose
names rather than employee IDs, so require unique tenant-scoped matches and
explicit salary-type mapping. Services contracts use an income-line basis with
no monthly salary. Migration 0035 extends existing pay-basis constraints without
adding tables or columns. Preserve approved payroll and unrelated manual lines.

The employee manual exposes exact PersonalCode and Month6 filters, with no
pagination or range contract. Keep capped pulls fail-closed and explain exact
personal-code filtering in the UI. Live PRO reconciliation and accountant UAT
remain acceptance work outside synthetic validation.
