CREATE TABLE payroll_withholding_recipients (
 id TEXT NOT NULL, organisation_id TEXT NOT NULL, name TEXT NOT NULL,
 registry_code TEXT NOT NULL, iban TEXT NOT NULL, reference_number TEXT,
 default_description TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY (organisation_id,id), UNIQUE (organisation_id,registry_code),
 FOREIGN KEY (organisation_id) REFERENCES organisations(id)
);
CREATE TABLE payroll_withholding_agreements (
 id TEXT NOT NULL, organisation_id TEXT NOT NULL, employee_id TEXT NOT NULL,
 recipient_id TEXT NOT NULL, component_type TEXT NOT NULL CHECK(component_type IN ('alimony','bailiff','union_fee','agreed_deduction','third_pillar')),
 method TEXT NOT NULL CHECK(method IN ('fixed_sum','percent_of_gross','sum_x_qty','third_pillar_net')),
 start_date TEXT NOT NULL, end_date TEXT, monthly_amount NUMERIC(12,2), percentage NUMERIC(7,4),
 quantity NUMERIC(12,4), rate NUMERIC(12,4), total_cap NUMERIC(12,2), withheld_to_date NUMERIC(12,2) NOT NULL DEFAULT 0,
 payment_description TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY (organisation_id,id),
 FOREIGN KEY (organisation_id,employee_id) REFERENCES employees(organisation_id,id),
 FOREIGN KEY (organisation_id,recipient_id) REFERENCES payroll_withholding_recipients(organisation_id,id),
 CHECK(end_date IS NULL OR end_date >= start_date), CHECK(total_cap IS NULL OR total_cap >= 0),
 CHECK(withheld_to_date >= 0)
);
CREATE INDEX payroll_withholding_agreements_active ON payroll_withholding_agreements(organisation_id,employee_id,active,start_date,end_date);
CREATE TABLE payroll_withholding_run_lines (
 id TEXT NOT NULL, organisation_id TEXT NOT NULL, pay_run_id TEXT NOT NULL,
 pay_run_item_id TEXT NOT NULL, agreement_id TEXT NOT NULL, recipient_id TEXT NOT NULL,
 employee_id TEXT NOT NULL, component_type TEXT NOT NULL, amount NUMERIC(12,2) NOT NULL,
 generated INTEGER NOT NULL DEFAULT 1, description TEXT NOT NULL DEFAULT '',
 PRIMARY KEY (organisation_id,id), UNIQUE(organisation_id,pay_run_id,agreement_id),
 FOREIGN KEY (organisation_id,pay_run_id) REFERENCES pay_runs(organisation_id,id),
 FOREIGN KEY (organisation_id,pay_run_item_id) REFERENCES pay_run_items(organisation_id,id),
 FOREIGN KEY (organisation_id,agreement_id) REFERENCES payroll_withholding_agreements(organisation_id,id),
 FOREIGN KEY (organisation_id,recipient_id) REFERENCES payroll_withholding_recipients(organisation_id,id),
 FOREIGN KEY (organisation_id,employee_id) REFERENCES employees(organisation_id,id), CHECK(amount >= 0)
);
CREATE TABLE payroll_withholding_payout_batches (
 id TEXT NOT NULL, organisation_id TEXT NOT NULL, pay_run_id TEXT NOT NULL,
 payout_batch_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Draft', created_at TEXT NOT NULL,
 PRIMARY KEY(organisation_id,id), UNIQUE(organisation_id,payout_batch_id),
 FOREIGN KEY(organisation_id,pay_run_id) REFERENCES pay_runs(organisation_id,id),
 FOREIGN KEY(organisation_id,payout_batch_id) REFERENCES payroll_payout_batches(organisation_id,id)
);
CREATE TABLE payroll_withholding_payout_lines (
 id TEXT NOT NULL, organisation_id TEXT NOT NULL, withholding_payout_id TEXT NOT NULL,
 recipient_id TEXT NOT NULL, amount NUMERIC(12,2) NOT NULL, iban TEXT NOT NULL,
 description TEXT NOT NULL, employee_references TEXT NOT NULL DEFAULT '[]',
 PRIMARY KEY(organisation_id,id),
 FOREIGN KEY(organisation_id,withholding_payout_id) REFERENCES payroll_withholding_payout_batches(organisation_id,id),
 FOREIGN KEY(organisation_id,recipient_id) REFERENCES payroll_withholding_recipients(organisation_id,id), CHECK(amount > 0)
);
