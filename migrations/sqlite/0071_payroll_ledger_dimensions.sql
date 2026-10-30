-- Freeze payroll analytical tags on general ledger entries.
ALTER TABLE gl_entry_objects ADD COLUMN payroll_department_id TEXT;
ALTER TABLE gl_entry_objects ADD COLUMN payroll_cost_centre_id TEXT;
CREATE INDEX idx_gl_entry_objects_payroll_department ON gl_entry_objects(organisation_id,payroll_department_id);
CREATE INDEX idx_gl_entry_objects_payroll_cost_centre ON gl_entry_objects(organisation_id,payroll_cost_centre_id);
