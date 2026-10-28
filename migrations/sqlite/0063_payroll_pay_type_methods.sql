ALTER TABLE pay_component_types ADD COLUMN calculation_method TEXT NOT NULL DEFAULT 'fixed_sum';
ALTER TABLE pay_component_types ADD COLUMN default_rate NUMERIC(12,4);
ALTER TABLE pay_component_types ADD COLUMN default_percentage NUMERIC(7,4);
ALTER TABLE pay_component_types ADD COLUMN default_coefficient NUMERIC(12,4);
ALTER TABLE pay_component_types ADD COLUMN palk_row INTEGER NOT NULL DEFAULT 5 CHECK (palk_row IN (5,6,7,8,9,10,15,16,17,18));
ALTER TABLE pay_item_components ADD COLUMN calculation_method TEXT NOT NULL DEFAULT 'fixed_sum';
ALTER TABLE pay_item_components ADD COLUMN quantity NUMERIC(12,4);
ALTER TABLE pay_item_components ADD COLUMN rate NUMERIC(12,4);
ALTER TABLE pay_item_components ADD COLUMN coefficient NUMERIC(12,4);
ALTER TABLE pay_item_components ADD COLUMN percentage NUMERIC(7,4);
ALTER TABLE pay_item_components ADD COLUMN palk_row INTEGER NOT NULL DEFAULT 5 CHECK (palk_row IN (5,6,7,8,9,10,15,16,17,18));
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role,is_wage,active,tsd_payment_type,calculation_method,palk_row)
 SELECT organisations.id||'-component-'||p.preset, organisations.id, p.preset, p.name, 'income',
 CASE WHEN p.preset IN ('car_compensation','birth_allowance') THEN 0 ELSE 1 END,
 CASE WHEN p.preset IN ('car_compensation','birth_allowance') THEN 0 ELSE 1 END,
 CASE WHEN p.preset IN ('car_compensation','birth_allowance') THEN 0 ELSE 1 END,
 CASE WHEN p.preset IN ('car_compensation','birth_allowance') THEN 0 ELSE 1 END,
 CASE WHEN p.preset IN ('car_compensation','birth_allowance') THEN 0 ELSE 1 END,
 CASE WHEN p.preset IN ('car_compensation','birth_allowance') THEN 0 ELSE 1 END,
 'PAYROLL_DEDUCTION', 1, 1, p.code, p.method, p.row_no
 FROM organisations CROSS JOIN (SELECT 'car_compensation' preset,'Isikliku sõiduauto hüvitis' name,10 code,'fixed_sum' method,15 row_no UNION ALL
 SELECT 'birth_allowance','Sünnitoetus',14,'fixed_sum',16 UNION ALL
 SELECT 'work_accident_benefit','Tööõnnetushüvitis',32,'fixed_sum',17 UNION ALL
 SELECT 'notice_pay','Etteteatamisaja hüvitis',33,'average_working_day_pay',8 UNION ALL
 SELECT 'care_leave_pay','Hoolduspuhkuse tasu',10,'average_working_day_pay',9 UNION ALL
 SELECT 'child_leave_pay','Lapsepuhkuse tasu',10,'average_working_day_pay',9) p
 WHERE organisations.country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
UPDATE pay_component_types SET calculation_method='percentage_of_hourly_rate',default_percentage=150,palk_row=6 WHERE preset_key='overtime';
UPDATE pay_component_types SET calculation_method='percentage_of_hourly_rate',default_percentage=25,palk_row=7 WHERE preset_key='night_work';
UPDATE pay_component_types SET calculation_method='percentage_of_hourly_rate',default_percentage=100,palk_row=7 WHERE preset_key='public_holiday';
UPDATE pay_component_types SET calculation_method='percentage_of_base',palk_row=5 WHERE preset_key='bonus';
UPDATE pay_component_types SET calculation_method='average_monthly_pay',palk_row=8 WHERE preset_key='severance';
UPDATE pay_component_types SET calculation_method='average_working_day_pay',palk_row=8 WHERE preset_key='notice_pay';
UPDATE pay_component_types SET palk_row=CASE preset_key
 WHEN 'overtime' THEN 6 WHEN 'night_work' THEN 7 WHEN 'public_holiday' THEN 7
 WHEN 'bonus' THEN 5 WHEN 'thirteenth_salary' THEN 8 WHEN 'annual_leave' THEN 9
 WHEN 'unused_leave' THEN 9 WHEN 'expense_reimbursement' THEN 15
 WHEN 'employer_sick_pay' THEN 9 WHEN 'severance' THEN 8 ELSE 5 END;
DROP TRIGGER guard_pay_item_components_update;
UPDATE pay_item_components SET calculation_method=(SELECT t.calculation_method FROM pay_component_types t
 WHERE t.organisation_id=pay_item_components.organisation_id AND t.id=pay_item_components.type_id),
 palk_row=(SELECT t.palk_row FROM pay_component_types t
 WHERE t.organisation_id=pay_item_components.organisation_id AND t.id=pay_item_components.type_id);
CREATE TRIGGER guard_pay_item_components_update BEFORE UPDATE ON pay_item_components WHEN EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=OLD.organisation_id AND i.id=OLD.item_id AND r.status='Approved') OR EXISTS (SELECT 1 FROM pay_run_items i JOIN pay_runs r ON r.organisation_id=i.organisation_id AND r.id=i.pay_run_id WHERE i.organisation_id=NEW.organisation_id AND i.id=NEW.item_id AND r.status='Approved') BEGIN SELECT RAISE(ABORT,'approved payroll components are immutable'); END;
