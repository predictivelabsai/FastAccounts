-- Services-contract pay uses explicit income lines without a monthly salary.
-- SQLite rebuilds employees solely to extend its existing CHECK constraints.
PRAGMA foreign_keys=OFF;
BEGIN;
CREATE TABLE employees_0035 (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL REFERENCES organisations(id),
 name TEXT NOT NULL, email TEXT, personal_id TEXT,
 gross_salary NUMERIC(12,2) CHECK(gross_salary>0),
 currency TEXT NOT NULL DEFAULT 'EUR' CHECK(currency='EUR'),
 funded_pension_percent NUMERIC(4,2) NOT NULL DEFAULT 2 CHECK(funded_pension_percent IN (0,2,4,6)),
 apply_tax_free_minimum INTEGER NOT NULL DEFAULT 0 CHECK(apply_tax_free_minimum IN (0,1)),
 board_member INTEGER NOT NULL DEFAULT 0 CHECK(board_member IN (0,1)),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL,
 pay_basis TEXT NOT NULL DEFAULT 'monthly' CHECK(pay_basis IN ('monthly','hourly','board_fee','income_line')),
 fte NUMERIC(5,4) NOT NULL DEFAULT 1 CHECK(fte>0 AND fte<=1),
 hourly_rate NUMERIC(12,4) CHECK(hourly_rate>0),
 social_tax_minimum_exemption TEXT,
 employment_start_date TEXT, employment_end_date TEXT,
 CONSTRAINT employees_pay_amount_check CHECK((pay_basis='hourly' AND hourly_rate IS NOT NULL) OR (pay_basis IN ('monthly','board_fee') AND gross_salary IS NOT NULL) OR (pay_basis='income_line' AND gross_salary IS NULL AND hourly_rate IS NULL)),
 CONSTRAINT employees_board_basis_check CHECK((pay_basis='board_fee' AND board_member=1) OR (pay_basis<>'board_fee' AND board_member=0)),
 UNIQUE(organisation_id,name), UNIQUE(organisation_id,id)
);
INSERT INTO employees_0035(id,organisation_id,name,email,personal_id,gross_salary,currency,funded_pension_percent,apply_tax_free_minimum,board_member,active,created_at,pay_basis,fte,hourly_rate,social_tax_minimum_exemption,employment_start_date,employment_end_date)
SELECT id,organisation_id,name,email,personal_id,gross_salary,currency,funded_pension_percent,apply_tax_free_minimum,board_member,active,created_at,pay_basis,fte,hourly_rate,social_tax_minimum_exemption,employment_start_date,employment_end_date FROM employees;
DROP TABLE employees;
ALTER TABLE employees_0035 RENAME TO employees;
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-contract',id,'contract','Töövõtulepingu tasu','income',1,1,1,1,1,0,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-base_adjustment',id,'base_adjustment','Põhipalga korrigeerimine','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
COMMIT;
PRAGMA foreign_keys=ON;
