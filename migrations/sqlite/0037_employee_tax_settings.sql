-- Effective-dated employee elections; existing pay amounts remain untouched.
CREATE UNIQUE INDEX IF NOT EXISTS idx_employee_tenant_id ON employees(organisation_id,id);
CREATE TABLE employee_tax_settings (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL, employee_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('tax_free','pension','unemployment')),
 start_date TEXT NOT NULL,
 mode TEXT CHECK(mode IN ('maximum','limited','none')),
 amount NUMERIC(12,2), rate NUMERIC(3,0), applies INTEGER,
 UNIQUE(organisation_id,id), UNIQUE(organisation_id,employee_id,kind,start_date),
 FOREIGN KEY(organisation_id,employee_id) REFERENCES employees(organisation_id,id),
 CHECK((kind='tax_free' AND mode IS NOT NULL AND rate IS NULL AND applies IS NULL
        AND ((mode='limited' AND amount IS NOT NULL AND amount>=0) OR (mode IN ('maximum','none') AND amount IS NULL)))
    OR (kind='pension' AND rate IS NOT NULL AND rate IN (0,2,4,6) AND mode IS NULL AND amount IS NULL AND applies IS NULL)
    OR (kind='unemployment' AND applies IS NOT NULL AND applies IN (0,1) AND mode IS NULL AND amount IS NULL AND rate IS NULL))
);
INSERT INTO employee_tax_settings(id,organisation_id,employee_id,kind,start_date,mode)
SELECT id || '-tax-free',organisation_id,id,'tax_free',COALESCE(employment_start_date,'2026-01-01'),
 CASE WHEN apply_tax_free_minimum=1 THEN 'maximum' ELSE 'none' END FROM employees;
INSERT INTO employee_tax_settings(id,organisation_id,employee_id,kind,start_date,rate)
SELECT id || '-pension',organisation_id,id,'pension',COALESCE(employment_start_date,'2026-01-01'),funded_pension_percent FROM employees;
INSERT INTO employee_tax_settings(id,organisation_id,employee_id,kind,start_date,applies)
SELECT id || '-unemployment',organisation_id,id,'unemployment',COALESCE(employment_start_date,'2026-01-01'),
 CASE WHEN pay_basis='board_fee' THEN 0 ELSE 1 END FROM employees;
ALTER TABLE pay_item_context ADD COLUMN tax_free_mode TEXT;
ALTER TABLE pay_item_context ADD COLUMN tax_free_amount NUMERIC(12,2);
ALTER TABLE pay_item_context ADD COLUMN unemployment_applies INTEGER;
ALTER TABLE pay_item_context ADD COLUMN tax_free_setting_id TEXT;
ALTER TABLE pay_item_context ADD COLUMN pension_setting_id TEXT;
ALTER TABLE pay_item_context ADD COLUMN unemployment_setting_id TEXT;
-- SQLITE_TAX_HISTORY_IMMUTABILITY
CREATE TRIGGER guard_employee_tax_settings_update BEFORE UPDATE ON employee_tax_settings WHEN EXISTS (SELECT 1 FROM pay_item_context c JOIN pay_run_items i ON i.organisation_id=c.organisation_id AND i.id=c.item_id JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE c.organisation_id=OLD.organisation_id AND r.status='Approved' AND (c.tax_free_setting_id=OLD.id OR c.pension_setting_id=OLD.id OR c.unemployment_setting_id=OLD.id)) BEGIN SELECT RAISE(ABORT,'approved payroll tax settings are immutable'); END;
CREATE TRIGGER guard_employee_tax_settings_delete BEFORE DELETE ON employee_tax_settings WHEN EXISTS (SELECT 1 FROM pay_item_context c JOIN pay_run_items i ON i.organisation_id=c.organisation_id AND i.id=c.item_id JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE c.organisation_id=OLD.organisation_id AND r.status='Approved' AND (c.tax_free_setting_id=OLD.id OR c.pension_setting_id=OLD.id OR c.unemployment_setting_id=OLD.id)) BEGIN SELECT RAISE(ABORT,'approved payroll tax settings are immutable'); END;
