CREATE TABLE invoice_schedules (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
 template_invoice_id TEXT REFERENCES invoices(id), contact_id TEXT NOT NULL,
 name TEXT, interval_kind TEXT NOT NULL CHECK(interval_kind IN ('weekly','monthly','quarterly','custom_days')),
 interval_days INTEGER CHECK(interval_days IS NULL OR interval_days BETWEEN 1 AND 365),
 next_run_date TEXT NOT NULL, end_date TEXT,
 auto_email INTEGER NOT NULL DEFAULT 0 CHECK(auto_email IN (0,1)),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 amount_type TEXT NOT NULL DEFAULT 'exclusive' CHECK(amount_type IN ('exclusive','inclusive','no_tax')),
 currency TEXT, reference TEXT, created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE invoice_schedule_lines (
 id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL REFERENCES invoice_schedules(id) ON DELETE CASCADE,
 line_number INTEGER NOT NULL, description TEXT NOT NULL,
 quantity NUMERIC(20,4) NOT NULL CHECK(quantity>0), unit_price NUMERIC(20,4) NOT NULL CHECK(unit_price>=0),
 account_id TEXT NOT NULL REFERENCES accounts(id), tax_code_id TEXT REFERENCES tax_codes(id),
 UNIQUE(schedule_id,line_number)
);
CREATE TABLE schedule_runs (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
 schedule_id TEXT NOT NULL REFERENCES invoice_schedules(id) ON DELETE CASCADE,
 period_start TEXT NOT NULL, run_date TEXT NOT NULL, invoice_id TEXT REFERENCES invoices(id),
 status TEXT NOT NULL DEFAULT 'Claimed' CHECK(status IN ('Claimed','Issued','Failed')),
 error_message TEXT, created_at TEXT NOT NULL, completed_at TEXT,
 UNIQUE(schedule_id,period_start)
);
CREATE TABLE invoice_reminder_events (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
 invoice_id TEXT NOT NULL REFERENCES invoices(id), ladder_stage INTEGER NOT NULL CHECK(ladder_stage BETWEEN 0 AND 2),
 due_date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('Sent','Failed')),
 delivery_id TEXT REFERENCES invoice_deliveries(id), error_message TEXT, created_at TEXT NOT NULL,
 UNIQUE(invoice_id,ladder_stage)
);
ALTER TABLE invoices ADD COLUMN reminders_disabled INTEGER NOT NULL DEFAULT 0 CHECK(reminders_disabled IN (0,1));
CREATE INDEX idx_invoice_schedules_due ON invoice_schedules(active,next_run_date);
CREATE INDEX idx_invoice_schedules_org ON invoice_schedules(organisation_id,active);
CREATE INDEX idx_schedule_runs_date ON schedule_runs(schedule_id,run_date);
CREATE INDEX idx_invoice_reminder_events_invoice ON invoice_reminder_events(invoice_id);
