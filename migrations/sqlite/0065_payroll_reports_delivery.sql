ALTER TABLE employees ADD COLUMN report_language TEXT NOT NULL DEFAULT 'et' CHECK(report_language IN ('et','en','lv','lt'));
CREATE TABLE payroll_report_settings (
 organisation_id TEXT PRIMARY KEY, sender_name TEXT NOT NULL DEFAULT '', reply_to TEXT NOT NULL DEFAULT '', cc TEXT NOT NULL DEFAULT '',
 FOREIGN KEY(organisation_id) REFERENCES organisations(id)
);
CREATE TABLE payroll_deliveries (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL, pay_run_id TEXT NOT NULL, employee_id TEXT, kind TEXT NOT NULL CHECK(kind IN ('payslip','review')),
 recipient TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('Pending','Sent','Failed')), subject TEXT NOT NULL DEFAULT '', error TEXT, created_at TEXT NOT NULL, sent_at TEXT,
 FOREIGN KEY(organisation_id,pay_run_id) REFERENCES pay_runs(organisation_id,id),
 FOREIGN KEY(organisation_id,employee_id) REFERENCES employees(organisation_id,id)
);
CREATE INDEX payroll_deliveries_history ON payroll_deliveries(organisation_id,pay_run_id,created_at,id);
