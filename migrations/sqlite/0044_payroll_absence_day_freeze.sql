ALTER TABLE pay_run_items ADD COLUMN worked_days INTEGER;
ALTER TABLE pay_run_items ADD COLUMN norm_days INTEGER;
ALTER TABLE pay_run_items ADD COLUMN absence_working_days INTEGER NOT NULL DEFAULT 0;
ALTER TABLE payroll_absence_run_items ADD COLUMN interrupts_salary INTEGER NOT NULL DEFAULT 1 CHECK (interrupts_salary IN (0,1));
