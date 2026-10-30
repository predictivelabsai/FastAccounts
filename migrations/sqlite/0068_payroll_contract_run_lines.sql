CREATE TABLE payroll_contract_run_lines (
 id TEXT PRIMARY KEY,
 organisation_id TEXT NOT NULL,
 pay_run_item_id TEXT NOT NULL,
 contract_id TEXT NOT NULL,
 agreement_id TEXT NOT NULL,
 contract_type TEXT NOT NULL CHECK(contract_type IN ('employment','board_member','services','other','none')),
 is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),
 payment_type INTEGER NOT NULL CHECK(payment_type IN (10,11,12,13,14,15,16,17,21,24,32,33)),
 effective_start TEXT NOT NULL,
 effective_end TEXT NOT NULL,
 gross NUMERIC(12,2) NOT NULL CHECK(gross>=0),
 monthly_net_advance NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK(monthly_net_advance>=0),
 FOREIGN KEY(organisation_id,pay_run_item_id) REFERENCES pay_run_items(organisation_id,id),
 FOREIGN KEY(organisation_id,contract_id) REFERENCES payroll_contracts(organisation_id,id),
 FOREIGN KEY(organisation_id,agreement_id) REFERENCES payroll_salary_agreements(organisation_id,id),
 UNIQUE(organisation_id,id)
);
CREATE INDEX idx_payroll_contract_run_lines_item ON payroll_contract_run_lines(organisation_id,pay_run_item_id);
