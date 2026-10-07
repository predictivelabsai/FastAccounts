CREATE TABLE employees (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL REFERENCES organisations(id),
 name TEXT NOT NULL, email TEXT, personal_id TEXT,
 gross_salary NUMERIC(12,2) NOT NULL CHECK(gross_salary>0),
 currency TEXT NOT NULL DEFAULT 'EUR' CHECK(currency='EUR'),
 funded_pension_percent NUMERIC(4,2) NOT NULL DEFAULT 2,
 apply_tax_free_minimum INTEGER NOT NULL DEFAULT 0 CHECK(apply_tax_free_minimum IN (0,1)),
 board_member INTEGER NOT NULL DEFAULT 0 CHECK(board_member IN (0,1)),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL,
 CHECK(funded_pension_percent IN (2,4,6) OR (board_member=1 AND funded_pension_percent=0)),
 UNIQUE(organisation_id,name), UNIQUE(organisation_id,id)
);
CREATE TABLE pay_runs (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL REFERENCES organisations(id),
 period TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Draft' CHECK(status IN ('Draft','Approved')),
 total_gross NUMERIC(20,2) NOT NULL, total_net NUMERIC(20,2) NOT NULL,
 total_employer_cost NUMERIC(20,2) NOT NULL, notes TEXT,
 posted_batch_id TEXT REFERENCES posting_batches(id), created_by TEXT NOT NULL,
 created_at TEXT NOT NULL, approved_at TEXT,
 UNIQUE(organisation_id,id)
);
CREATE UNIQUE INDEX idx_pay_runs_period ON pay_runs(organisation_id,period);
CREATE TABLE pay_run_items (
 id TEXT PRIMARY KEY, pay_run_id TEXT NOT NULL, organisation_id TEXT NOT NULL,
 employee_id TEXT NOT NULL, employee_name TEXT NOT NULL, gross_salary NUMERIC(12,2) NOT NULL,
 board_member INTEGER NOT NULL CHECK(board_member IN (0,1)),
 funded_pension_percent NUMERIC(4,2) NOT NULL,
 gross NUMERIC(12,2) NOT NULL, funded_pension NUMERIC(12,2) NOT NULL,
 ui_employee NUMERIC(12,2) NOT NULL, tax_free_minimum NUMERIC(12,2) NOT NULL,
 income_tax NUMERIC(12,2) NOT NULL, net NUMERIC(12,2) NOT NULL,
 withholding_total NUMERIC(12,2) NOT NULL, social_tax NUMERIC(12,2) NOT NULL,
 ui_employer NUMERIC(12,2) NOT NULL, employer_cost NUMERIC(20,2) NOT NULL,
 FOREIGN KEY(organisation_id,pay_run_id) REFERENCES pay_runs(organisation_id,id),
 FOREIGN KEY(organisation_id,employee_id) REFERENCES employees(organisation_id,id),
 UNIQUE(organisation_id,pay_run_id,employee_id)
);
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_SALARY',id,'6110','Salary expense','Expense','Debit','PAYROLL_SALARY' FROM organisations WHERE country_code='EE';
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_SOCIAL',id,'6120','Social tax expense','Expense','Debit','PAYROLL_SOCIAL' FROM organisations WHERE country_code='EE';
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_UI',id,'6130','Employer unemployment expense','Expense','Debit','PAYROLL_UI' FROM organisations WHERE country_code='EE';
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_NET',id,'2210','Employee net payable','Liability','Credit','PAYROLL_NET' FROM organisations WHERE country_code='EE';
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_INCOME_TAX',id,'2220','Payroll income tax payable','Liability','Credit','PAYROLL_INCOME_TAX' FROM organisations WHERE country_code='EE';
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_WITHHOLDING',id,'2230','Employee pension and unemployment payable','Liability','Credit','PAYROLL_WITHHOLDING' FROM organisations WHERE country_code='EE';
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_EMPLOYER_TAX',id,'2240','Employer payroll taxes payable','Liability','Credit','PAYROLL_EMPLOYER_TAX' FROM organisations WHERE country_code='EE';
