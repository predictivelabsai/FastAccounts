-- Editable payroll components and explicit TSD liability reclassification.
-- No existing ledger lines or payroll totals are rewritten.
CREATE UNIQUE INDEX IF NOT EXISTS idx_pay_item_tenant_id ON pay_run_items(organisation_id,id);
CREATE TABLE IF NOT EXISTS pay_component_types (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL REFERENCES organisations(id),
 preset_key TEXT, name TEXT NOT NULL, direction TEXT NOT NULL CHECK(direction IN ('income','deduction')),
 income_tax INTEGER NOT NULL DEFAULT 0 CHECK(income_tax IN (0,1)),
 social_tax INTEGER NOT NULL DEFAULT 0 CHECK(social_tax IN (0,1)),
 ui_employee INTEGER NOT NULL DEFAULT 0 CHECK(ui_employee IN (0,1)),
 ui_employer INTEGER NOT NULL DEFAULT 0 CHECK(ui_employer IN (0,1)),
 funded_pension INTEGER NOT NULL DEFAULT 0 CHECK(funded_pension IN (0,1)),
 social_minimum INTEGER NOT NULL DEFAULT 0 CHECK(social_minimum IN (0,1)),
 liability_role TEXT NOT NULL DEFAULT 'PAYROLL_DEDUCTION',
 UNIQUE(organisation_id,preset_key), UNIQUE(organisation_id,id)
);
CREATE TABLE IF NOT EXISTS pay_item_components (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL, item_id TEXT NOT NULL,
 type_id TEXT NOT NULL, position INTEGER NOT NULL, name TEXT NOT NULL,
 amount NUMERIC(12,2) NOT NULL CHECK(amount<>0),
 direction TEXT NOT NULL CHECK(direction IN ('income','deduction')),
 income_tax INTEGER NOT NULL DEFAULT 0 CHECK(income_tax IN (0,1)),
 social_tax INTEGER NOT NULL DEFAULT 0 CHECK(social_tax IN (0,1)),
 ui_employee INTEGER NOT NULL DEFAULT 0 CHECK(ui_employee IN (0,1)),
 ui_employer INTEGER NOT NULL DEFAULT 0 CHECK(ui_employer IN (0,1)),
 funded_pension INTEGER NOT NULL DEFAULT 0 CHECK(funded_pension IN (0,1)),
 social_minimum INTEGER NOT NULL DEFAULT 0 CHECK(social_minimum IN (0,1)),
 liability_role TEXT NOT NULL,
 FOREIGN KEY(organisation_id,item_id) REFERENCES pay_run_items(organisation_id,id),
 FOREIGN KEY(organisation_id,type_id) REFERENCES pay_component_types(organisation_id,id),
 CHECK(direction='income' OR amount>0), UNIQUE(organisation_id,item_id,position)
);
CREATE TABLE IF NOT EXISTS pay_item_context (
 organisation_id TEXT NOT NULL, item_id TEXT NOT NULL,
 apply_tax_free_minimum INTEGER NOT NULL CHECK(apply_tax_free_minimum IN (0,1)),
 employment_start_date TEXT, employment_end_date TEXT,
 PRIMARY KEY(organisation_id,item_id),
 FOREIGN KEY(organisation_id,item_id) REFERENCES pay_run_items(organisation_id,id)
);
-- Existing items retain their totals; infer the historical allowance application
-- from the amount used, and retain current employment dates for draft editing.
INSERT INTO pay_item_context(organisation_id,item_id,apply_tax_free_minimum,employment_start_date,employment_end_date)
SELECT i.organisation_id,i.id,CASE WHEN i.tax_free_minimum>0 THEN 1 ELSE 0 END,e.employment_start_date,e.employment_end_date
FROM pay_run_items i JOIN employees e ON e.organisation_id=i.organisation_id AND e.id=i.employee_id
WHERE NOT EXISTS (SELECT 1 FROM pay_item_context c WHERE c.organisation_id=i.organisation_id AND c.item_id=i.id) ON CONFLICT(organisation_id,item_id) DO NOTHING;
CREATE TABLE IF NOT EXISTS pay_run_posting_accounts (
 organisation_id TEXT NOT NULL, pay_run_id TEXT NOT NULL, role TEXT NOT NULL, account_id TEXT NOT NULL,
 PRIMARY KEY(organisation_id,pay_run_id,role),
 FOREIGN KEY(organisation_id,pay_run_id) REFERENCES pay_runs(organisation_id,id),
 FOREIGN KEY(organisation_id,account_id) REFERENCES accounts(organisation_id,id)
);
CREATE TABLE IF NOT EXISTS pay_run_settlements (
 organisation_id TEXT NOT NULL, pay_run_id TEXT NOT NULL, posted_batch_id TEXT REFERENCES posting_batches(id),
 PRIMARY KEY(organisation_id,pay_run_id),
 FOREIGN KEY(organisation_id,pay_run_id) REFERENCES pay_runs(organisation_id,id)
);
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_SALARY_PAYABLE',id,'2250','Palgavõlg','Liability','Credit','PAYROLL_SALARY_PAYABLE' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_BAILIFF',id,'2251','Kohtutäituri kinnipidamised','Liability','Credit','PAYROLL_BAILIFF' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_DEDUCTION',id,'2252','Muud palga kinnipidamised','Liability','Credit','PAYROLL_DEDUCTION' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_SOCIAL_ACCRUED',id,'2253','Arvestatud sotsiaalmaks','Liability','Credit','PAYROLL_SOCIAL_ACCRUED' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_INCOME_WITHHELD',id,'2254','Kinnipeetud tulumaks','Liability','Credit','PAYROLL_INCOME_WITHHELD' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_PENSION_WITHHELD',id,'2255','Kinnipeetud kogumispension','Liability','Credit','PAYROLL_PENSION_WITHHELD' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_UI_ACCRUED',id,'2256','Arvestatud töötuskindlustusmaksed','Liability','Credit','PAYROLL_UI_ACCRUED' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_SOCIAL_PAYABLE',id,'2257','Tasumisele kuuluv sotsiaalmaks ja kogumispension','Liability','Credit','PAYROLL_SOCIAL_PAYABLE' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_INCOME_PAYABLE',id,'2258','Tasumisele kuuluv tulumaks','Liability','Credit','PAYROLL_INCOME_PAYABLE' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO accounts(id,organisation_id,code,name,account_type,normal_balance,system_role) SELECT id || '-PAYROLL_UI_PAYABLE',id,'2259','Tasumisele kuuluvad töötuskindlustusmaksed','Liability','Credit','PAYROLL_UI_PAYABLE' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role) SELECT id || '-component-bailiff',id,'bailiff','Kinnipidamine kohtutäiturile','deduction',0,0,0,0,0,0,'PAYROLL_BAILIFF' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role) SELECT id || '-component-author',id,'author','Autori tasu','income',1,1,0,0,0,1,'PAYROLL_DEDUCTION' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role) SELECT id || '-component-parental',id,'parental','Vanemapuhkused','income',1,0,0,0,0,0,'PAYROLL_DEDUCTION' FROM organisations WHERE country_code='EE' ON CONFLICT DO NOTHING;
-- SQLITE_PAYROLL_IMMUTABILITY
CREATE TRIGGER IF NOT EXISTS guard_pay_item_components_insert BEFORE INSERT ON pay_item_components WHEN EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=NEW.organisation_id AND i.id=NEW.item_id AND r.status='Approved') BEGIN SELECT RAISE(ABORT,'approved payroll components are immutable'); END;
CREATE TRIGGER IF NOT EXISTS guard_pay_item_components_update BEFORE UPDATE ON pay_item_components WHEN EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=OLD.organisation_id AND i.id=OLD.item_id AND r.status='Approved') OR EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=NEW.organisation_id AND i.id=NEW.item_id AND r.status='Approved') BEGIN SELECT RAISE(ABORT,'approved payroll components are immutable'); END;
CREATE TRIGGER IF NOT EXISTS guard_pay_item_components_delete BEFORE DELETE ON pay_item_components WHEN EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=OLD.organisation_id AND i.id=OLD.item_id AND r.status='Approved') BEGIN SELECT RAISE(ABORT,'approved payroll components are immutable'); END;
CREATE TRIGGER IF NOT EXISTS guard_pay_item_context_insert BEFORE INSERT ON pay_item_context WHEN EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=NEW.organisation_id AND i.id=NEW.item_id AND r.status='Approved') BEGIN SELECT RAISE(ABORT,'approved payroll components are immutable'); END;
CREATE TRIGGER IF NOT EXISTS guard_pay_item_context_update BEFORE UPDATE ON pay_item_context WHEN EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=OLD.organisation_id AND i.id=OLD.item_id AND r.status='Approved') OR EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=NEW.organisation_id AND i.id=NEW.item_id AND r.status='Approved') BEGIN SELECT RAISE(ABORT,'approved payroll components are immutable'); END;
CREATE TRIGGER IF NOT EXISTS guard_pay_item_context_delete BEFORE DELETE ON pay_item_context WHEN EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=OLD.organisation_id AND i.id=OLD.item_id AND r.status='Approved') BEGIN SELECT RAISE(ABORT,'approved payroll components are immutable'); END;
