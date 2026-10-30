ALTER TABLE payroll_leave_entitlements ADD COLUMN source_key TEXT;
ALTER TABLE payroll_leave_openings ADD COLUMN extended_unused_days NUMERIC(8,2) NOT NULL DEFAULT 0 CHECK(extended_unused_days >= 0);
ALTER TABLE payroll_leave_openings ADD COLUMN source_key TEXT;
CREATE UNIQUE INDEX idx_payroll_leave_entitlements_source
  ON payroll_leave_entitlements(organisation_id,employee_id,source_key) WHERE source_key IS NOT NULL;
CREATE UNIQUE INDEX idx_payroll_leave_openings_source
  ON payroll_leave_openings(organisation_id,employee_id,source_key) WHERE source_key IS NOT NULL;
