-- Part-time (FTE), hourly pay, board-fee pay basis, II pillar 0% for anyone not
-- in the funded pension scheme, and the 2026 social tax minimum obligation.
-- SQLite cannot drop a table CHECK, so employees is rebuilt; PostgreSQL uses the
-- ALTER-based equivalent in database._POSTGRES_PAYROLL_0006.
PRAGMA foreign_keys=OFF;
BEGIN;
CREATE TABLE employees_0006 (
 id TEXT PRIMARY KEY, organisation_id TEXT NOT NULL REFERENCES organisations(id),
 name TEXT NOT NULL, email TEXT, personal_id TEXT,
 gross_salary NUMERIC(12,2) CHECK(gross_salary>0),
 currency TEXT NOT NULL DEFAULT 'EUR' CHECK(currency='EUR'),
 funded_pension_percent NUMERIC(4,2) NOT NULL DEFAULT 2 CHECK(funded_pension_percent IN (0,2,4,6)),
 apply_tax_free_minimum INTEGER NOT NULL DEFAULT 0 CHECK(apply_tax_free_minimum IN (0,1)),
 board_member INTEGER NOT NULL DEFAULT 0 CHECK(board_member IN (0,1)),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)), created_at TEXT NOT NULL,
 pay_basis TEXT NOT NULL DEFAULT 'monthly' CHECK(pay_basis IN ('monthly','hourly','board_fee')),
 fte NUMERIC(5,4) NOT NULL DEFAULT 1 CHECK(fte>0 AND fte<=1),
 hourly_rate NUMERIC(12,4) CHECK(hourly_rate>0),
 social_tax_minimum_exemption TEXT,
 employment_start_date TEXT, employment_end_date TEXT,
 CONSTRAINT employees_pay_amount_check CHECK((pay_basis='hourly' AND hourly_rate IS NOT NULL) OR (pay_basis<>'hourly' AND gross_salary IS NOT NULL)),
 CONSTRAINT employees_board_basis_check CHECK((pay_basis='board_fee' AND board_member=1) OR (pay_basis<>'board_fee' AND board_member=0)),
 UNIQUE(organisation_id,name), UNIQUE(organisation_id,id)
);
INSERT INTO employees_0006(id,organisation_id,name,email,personal_id,gross_salary,currency,funded_pension_percent,
  apply_tax_free_minimum,board_member,active,created_at,pay_basis)
SELECT id,organisation_id,name,email,personal_id,gross_salary,currency,funded_pension_percent,
  apply_tax_free_minimum,board_member,active,created_at,
  CASE WHEN board_member=1 THEN 'board_fee' ELSE 'monthly' END
FROM employees;
DROP TABLE employees;
ALTER TABLE employees_0006 RENAME TO employees;
ALTER TABLE pay_run_items ADD COLUMN pay_basis TEXT NOT NULL DEFAULT 'monthly';
ALTER TABLE pay_run_items ADD COLUMN fte NUMERIC(5,4) NOT NULL DEFAULT 1;
ALTER TABLE pay_run_items ADD COLUMN hourly_rate NUMERIC(12,4);
ALTER TABLE pay_run_items ADD COLUMN hours NUMERIC(7,2);
ALTER TABLE pay_run_items ADD COLUMN minimum_wage NUMERIC(12,2);
ALTER TABLE pay_run_items ADD COLUMN social_tax_base NUMERIC(12,2);
ALTER TABLE pay_run_items ADD COLUMN social_tax_minimum_topup NUMERIC(12,2) NOT NULL DEFAULT 0;
ALTER TABLE pay_run_items ADD COLUMN social_tax_minimum_exemption TEXT;
-- Runs drafted before 0006 taxed actual pay only; record that base explicitly.
UPDATE pay_run_items SET pay_basis=CASE WHEN board_member=1 THEN 'board_fee' ELSE 'monthly' END, social_tax_base=gross;
COMMIT;
PRAGMA foreign_keys=ON;
