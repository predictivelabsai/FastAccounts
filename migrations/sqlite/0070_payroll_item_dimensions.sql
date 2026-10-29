-- Freeze employee-level dimensions on the calculated payroll item.
ALTER TABLE pay_run_items ADD COLUMN department_id TEXT;
ALTER TABLE pay_run_items ADD COLUMN position_id TEXT;
ALTER TABLE pay_run_items ADD COLUMN cost_centre_id TEXT;
ALTER TABLE pay_run_items ADD COLUMN project_id TEXT;
