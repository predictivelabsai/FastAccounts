ALTER TABLE pay_component_types ADD COLUMN tsd_payment_type INTEGER NOT NULL DEFAULT 10;
ALTER TABLE pay_item_components ADD COLUMN tsd_payment_type INTEGER NOT NULL DEFAULT 10;
UPDATE pay_component_types SET tsd_payment_type=CASE preset_key
 WHEN 'board_fee' THEN 21 WHEN 'contract' THEN 17 WHEN 'employer_sick_pay' THEN 24
 WHEN 'severance' THEN 33 WHEN 'author' THEN 17 WHEN 'parental' THEN 10
 WHEN 'expense_reimbursement' THEN 16 WHEN 'bailiff' THEN 16
 WHEN 'salary_advance' THEN 16 WHEN 'advance_recovery' THEN 16
 WHEN 'alimony' THEN 16 WHEN 'union_fee' THEN 16 WHEN 'agreed_deduction' THEN 16
 ELSE 10 END;
DROP TRIGGER guard_pay_item_components_update;
UPDATE pay_item_components SET tsd_payment_type=(SELECT t.tsd_payment_type FROM pay_component_types t
 WHERE t.organisation_id=pay_item_components.organisation_id AND t.id=pay_item_components.type_id);
CREATE TRIGGER guard_pay_item_components_update BEFORE UPDATE ON pay_item_components WHEN EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=OLD.organisation_id AND i.id=OLD.item_id AND r.status='Approved') OR EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=NEW.organisation_id AND i.id=NEW.item_id AND r.status='Approved') BEGIN SELECT RAISE(ABORT,'approved payroll components are immutable'); END;
