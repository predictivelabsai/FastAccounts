-- Expanded editable Estonian payroll defaults. Existing rows and saved lines are preserved.
-- UNIQUE(organisation_id,preset_key) was created by migration 0034; reuse it.
-- Payroll rules: a correction inherits ordinary employment-pay levies.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-base_adjustment',id,'base_adjustment','Põhipalga korrigeerimine','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: services-contract default, without employment social minimum.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-contract',id,'contract','Töövõtulepingu tasu','income',1,1,1,1,1,0,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: net garnishment uses the separate bailiff liability.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-bailiff',id,'bailiff','Kinnipidamine kohtutäiturile','deduction',0,0,0,0,0,0,'PAYROLL_BAILIFF'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: uncertain author treatment defaults to fully taxable income pending UAT.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-author',id,'author','Autori tasu','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: uncertain employer parental pay defaults to fully taxable income, excluding state benefits.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-parental',id,'parental','Vanemapuhkused','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- EMTA Palgatulu: annual leave pay is ordinary taxable employment income.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-annual_leave',id,'annual_leave','Puhkusetasu','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- EMTA Palgatulu, TLS section 84: unused leave compensation carries all levies.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-unused_leave',id,'unused_leave','Kasutamata puhkuse hüvitis','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- EMTA Sotsiaalmaks, TTOS section 12^2: qualifying days 1-8 within limits, income tax only.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-employer_sick_pay',id,'employer_sick_pay','Tööandja haigushüvitis piirmäära ulatuses','income',1,0,0,0,0,0,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: overtime remuneration is ordinary taxable employment pay.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-overtime',id,'overtime','Ületunnitöö tasu','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: extra duties are ordinary taxable employment pay.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-extra_work',id,'extra_work','Lisatöö tasu','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: cash bonuses carry ordinary employment-pay levies.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-bonus',id,'bonus','Preemia ja boonus','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: a thirteenth salary carries ordinary employment-pay levies.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-thirteenth_salary',id,'thirteenth_salary','13. palk','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: public-holiday work remuneration carries all ordinary levies.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-public_holiday',id,'public_holiday','Riigipühal töötamise tasu','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: night-work remuneration carries ordinary employment-pay levies.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-night_work',id,'night_work','Öötöö tasu','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: rest-day work remuneration carries ordinary employment-pay levies.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-rest_day',id,'rest_day','Puhkepäeval töötamise tasu','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: standby remuneration uses the conservative taxable-pay default.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-standby',id,'standby','Valveaja tasu','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: substitution pay carries ordinary employment-pay levies.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-substitution',id,'substitution','Asendustasu','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: employment sales commission carries ordinary pay levies.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-commission',id,'commission','Müügitasu','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: employer-paid study leave uses the conservative taxable-pay default.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-study_leave',id,'study_leave','Õppepuhkuse tasu','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: retained average wages use the conservative taxable-pay default.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-average_pay',id,'average_pay','Keskmise töötasu säilitamine','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- EMTA Palgatulu: general agreed severance is fully taxable; statutory UI exceptions need review.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-severance',id,'severance','Töölepingu lõpetamise hüvitis','income',1,1,1,1,1,1,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules / TuMS section 12(3): documented employer costs only, no remuneration.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-expense_reimbursement',id,'expense_reimbursement','Dokumenteeritud kulude hüvitis','income',0,0,0,0,0,0,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: salary advance already paid reduces the remaining net payable only.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-salary_advance',id,'salary_advance','Väljamakstud palga ettemaks','deduction',0,0,0,0,0,0,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: prior-period advance recovery is a net deduction, never tax relief.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-advance_recovery',id,'advance_recovery','Varasema ettemaksu tasaarvestus','deduction',0,0,0,0,0,0,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: direct alimony withholding is net; bailiff orders use the bailiff preset.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-alimony',id,'alimony','Elatise kinnipidamine','deduction',0,0,0,0,0,0,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: union membership fees are net deductions without payroll tax relief.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-union_fee',id,'union_fee','Ametiühingu liikmemaksu kinnipidamine','deduction',0,0,0,0,0,0,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
-- Payroll rules: other agreed withholdings reduce net only, subject to lawful authority.
INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,income_tax,social_tax,ui_employee,ui_employer,funded_pension,social_minimum,liability_role)
SELECT id || '-component-agreed_deduction',id,'agreed_deduction','Muu kokkulepitud kinnipidamine','deduction',0,0,0,0,0,0,'PAYROLL_DEDUCTION'
FROM organisations WHERE country_code='EE' ON CONFLICT(organisation_id,preset_key) DO NOTHING;
