-- Freeze the payee identifier used by accountant-reviewed, per-payment TSD
-- exports. Existing run items are backfilled once; new runs snapshot it when
-- the draft is created so later employee edits cannot change a confirmed run.
ALTER TABLE pay_run_items ADD COLUMN employee_personal_id TEXT;
UPDATE pay_run_items
SET employee_personal_id=(
  SELECT e.personal_id FROM employees e
  WHERE e.organisation_id=pay_run_items.organisation_id
    AND e.id=pay_run_items.employee_id
);
