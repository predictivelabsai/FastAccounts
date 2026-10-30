CREATE TABLE payroll_contracts (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 employee_id TEXT NOT NULL,
 contract_type TEXT NOT NULL CHECK(contract_type IN ('employment','board_member','services','other','none')),
 start_date TEXT NOT NULL,
 end_date TEXT,
 document_name TEXT,
 workplace_address TEXT,
 monthly_net_advance NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK(monthly_net_advance>=0),
 payday_rule TEXT CHECK(payday_rule IN ('next_month_day','current_month_day','next_month_first_working_day')),
 payday_day INTEGER CHECK(payday_day BETWEEN 1 AND 31),
 created_at TEXT NOT NULL,
 FOREIGN KEY(organisation_id,employee_id) REFERENCES employees(organisation_id,id),
 UNIQUE(organisation_id,id)
);
CREATE INDEX idx_payroll_contracts_employee_dates ON payroll_contracts(organisation_id,employee_id,start_date,end_date);
CREATE TABLE payroll_salary_agreements (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 contract_id TEXT NOT NULL,
 start_date TEXT NOT NULL,
 base_pay_type TEXT NOT NULL CHECK(base_pay_type IN ('monthly','monthly_day_based','hourly','contract_sum','contract_sum_x_qty')),
 hours_per_day NUMERIC(5,2) NOT NULL DEFAULT 8 CHECK(hours_per_day>0),
 rate NUMERIC(12,2) NOT NULL CHECK(rate>=0),
 fte NUMERIC(5,4) NOT NULL DEFAULT 1 CHECK(fte>0 AND fte<=1),
 is_full_time INTEGER NOT NULL DEFAULT 1 CHECK(is_full_time IN (0,1)),
 automatic_working_time INTEGER NOT NULL DEFAULT 1 CHECK(automatic_working_time IN (0,1)),
 account_override TEXT,
 created_at TEXT NOT NULL,
 FOREIGN KEY(organisation_id,contract_id) REFERENCES payroll_contracts(organisation_id,id),
 UNIQUE(organisation_id,id), UNIQUE(organisation_id,contract_id,start_date)
);
CREATE INDEX idx_payroll_salary_agreements_effective ON payroll_salary_agreements(organisation_id,contract_id,start_date);
CREATE TABLE payroll_contract_positions (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 contract_id TEXT NOT NULL,
 start_date TEXT NOT NULL,
 position TEXT NOT NULL,
 occupation_code TEXT,
 FOREIGN KEY(organisation_id,contract_id) REFERENCES payroll_contracts(organisation_id,id),
 UNIQUE(organisation_id,id), UNIQUE(organisation_id,contract_id,start_date)
);
CREATE TABLE payroll_tor_imports (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL REFERENCES organisations(id),
 source_hash TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('review','applied')),
 assumptions TEXT NOT NULL,
 created_by TEXT NOT NULL,
 created_at TEXT NOT NULL,
 UNIQUE(organisation_id,id), UNIQUE(organisation_id,source_hash)
);
CREATE TABLE payroll_tor_import_rows (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 import_id TEXT NOT NULL,
 row_number INTEGER NOT NULL,
 personal_id TEXT,
 source_name TEXT,
 start_date TEXT,
 end_date TEXT,
 contract_type TEXT,
 position TEXT,
 occupation_code TEXT,
 fte NUMERIC(5,4),
 workplace_address TEXT,
 errors TEXT NOT NULL DEFAULT '[]',
 applied_contract_id TEXT,
 FOREIGN KEY(organisation_id,import_id) REFERENCES payroll_tor_imports(organisation_id,id),
 UNIQUE(organisation_id,import_id,row_number)
);
INSERT INTO payroll_contracts(id,organisation_id,employee_id,contract_type,start_date,end_date,created_at)
 SELECT 'contract-' || id,organisation_id,id,
        CASE pay_basis WHEN 'board_fee' THEN 'board_member' WHEN 'income_line' THEN 'services' ELSE 'employment' END,
        COALESCE(employment_start_date,'2026-01-01'),employment_end_date,created_at
 FROM employees;
INSERT INTO payroll_salary_agreements(id,organisation_id,contract_id,start_date,base_pay_type,rate,fte,created_at)
 SELECT 'agreement-' || id,organisation_id,'contract-' || id,COALESCE(employment_start_date,'2026-01-01'),
        CASE pay_basis WHEN 'hourly' THEN 'hourly' WHEN 'income_line' THEN 'contract_sum' ELSE 'monthly' END,
        CASE pay_basis WHEN 'hourly' THEN hourly_rate WHEN 'income_line' THEN 0 ELSE gross_salary END,
        COALESCE(fte,1),created_at
 FROM employees;
