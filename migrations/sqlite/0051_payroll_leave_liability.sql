CREATE TABLE payroll_leave_settings (
 organisation_id TEXT PRIMARY KEY REFERENCES organisations(id),
 basic_expiry_policy TEXT NOT NULL DEFAULT 'none' CHECK(basic_expiry_policy IN ('none','1_january_year_plus_2','31_december_year_plus_1')),
 extended_expiry_policy TEXT NOT NULL DEFAULT 'none' CHECK(extended_expiry_policy IN ('none','1_january_year_plus_2','31_december_year_plus_1')),
 reserve_posting_enabled INTEGER NOT NULL DEFAULT 0 CHECK(reserve_posting_enabled IN (0,1))
);
ALTER TABLE pay_runs ADD COLUMN show_leave_balance INTEGER NOT NULL DEFAULT 0 CHECK(show_leave_balance IN (0,1));
CREATE TABLE payroll_leave_reserve_posts (
 organisation_id TEXT NOT NULL REFERENCES organisations(id),
 period TEXT NOT NULL,
 posting_batch_id TEXT NOT NULL REFERENCES posting_batches(id),
 valuation_total NUMERIC(20,2) NOT NULL,
 created_by TEXT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY(organisation_id,period)
);
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role)
 SELECT id || '-PAYROLL_VACATION_RESERVE_EXPENSE',id,'6140','Vacation reserve expense','Expense','Debit','PAYROLL_VACATION_RESERVE_EXPENSE'
 FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role)
 SELECT id || '-PAYROLL_VACATION_RESERVE_LIABILITY',id,'2260','Vacation reserve liability','Liability','Credit','PAYROLL_VACATION_RESERVE_LIABILITY'
 FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
