-- Build 10 tenant-scoped payroll registers and frozen analytical dimensions.
CREATE TABLE payroll_dimensions (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL REFERENCES organisations(id),
 kind TEXT NOT NULL CHECK(kind IN ('department','position_group','position','cost_centre')),
 code TEXT NOT NULL CHECK(length(code) BETWEEN 1 AND 40),
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 180),
 parent_id TEXT,
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 UNIQUE(organisation_id,id),
 UNIQUE(organisation_id,kind,code),
 FOREIGN KEY(organisation_id,parent_id) REFERENCES payroll_dimensions(organisation_id,id)
);
CREATE INDEX idx_payroll_dimensions_kind ON payroll_dimensions(organisation_id,kind,active,code);
ALTER TABLE employees ADD COLUMN department_id TEXT;
ALTER TABLE employees ADD COLUMN position_id TEXT;
ALTER TABLE payroll_contracts ADD COLUMN department_id TEXT;
ALTER TABLE payroll_contracts ADD COLUMN position_id TEXT;
ALTER TABLE payroll_salary_agreements ADD COLUMN department_id TEXT;
ALTER TABLE payroll_salary_agreements ADD COLUMN cost_centre_id TEXT;
ALTER TABLE payroll_salary_agreements ADD COLUMN project_id TEXT;
ALTER TABLE pay_item_components ADD COLUMN department_id TEXT;
ALTER TABLE pay_item_components ADD COLUMN cost_centre_id TEXT;
ALTER TABLE pay_item_components ADD COLUMN project_id TEXT;
ALTER TABLE payroll_contract_run_lines ADD COLUMN department_id TEXT;
ALTER TABLE payroll_contract_run_lines ADD COLUMN position_id TEXT;
ALTER TABLE payroll_contract_run_lines ADD COLUMN cost_centre_id TEXT;
ALTER TABLE payroll_contract_run_lines ADD COLUMN project_id TEXT;
