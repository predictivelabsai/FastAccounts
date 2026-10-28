"""Editable bureau defaults, frozen separately on each payroll item.

Defaults require accountant UAT against EMTA's social tax and withholding rules:
https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/sotsiaalmaks
https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/maksumaarad
Bureau users may override every levy flag for each period.
"""
from core_utils import db_number, money
from decimal import Decimal
from datetime import date
from payroll_rules import rules_for

CALCULATION_METHODS = ('fixed_sum', 'sum_x_qty_x_coef', 'percentage_of_base',
    'percentage_of_hourly_rate', 'piece_rate', 'hourly', 'average_monthly_pay',
    'average_hourly_pay', 'average_working_day_pay', 'gross_up_from_net',
    'monthly_salary', 'monthly_salary_day_based', 'contract_sum',
    'contract_sum_x_quantity', 'percentage')
PALK_ROWS = (5, 6, 7, 8, 9, 10, 15, 16, 17, 18)


def calculate_component_amount(method, *, amount=0, rate=0, quantity=1, coefficient=1,
                               percentage=0, base_pay=0, hourly_rate=0, hours=0,
                               average_monthly_pay=0, average_hourly_pay=0,
                               average_working_day_pay=0, net_target=0,
                               pension_percent=0, unemployment=True, exemption=0,
                               income_tax_rate=Decimal('0.22'), unemployment_rate=Decimal('0.016')):
    """Pure Decimal component calculator. Rates and percentages are entered as human units."""
    d = lambda value: Decimal(str(value or 0))
    method = method or 'fixed_sum'
    if method not in CALCULATION_METHODS:
        raise ValueError('Choose a supported calculation method')
    if method == 'fixed_sum':
        result = d(amount)
    elif method in ('sum_x_qty_x_coef', 'contract_sum_x_quantity'):
        result = d(rate) * d(quantity) * (d(coefficient) if method == 'sum_x_qty_x_coef' else Decimal(1))
    elif method in ('percentage_of_base', 'percentage'):
        result = d(base_pay) * d(percentage) / 100
    elif method == 'percentage_of_hourly_rate':
        result = d(hourly_rate) * d(percentage) / 100 * d(hours if quantity is None else quantity)
    elif method == 'piece_rate':
        result = d(rate) * d(quantity)
    elif method == 'hourly':
        result = d(rate) * d(hours if quantity is None else quantity)
    elif method == 'average_monthly_pay':
        result = d(average_monthly_pay) * d(quantity)
    elif method == 'average_hourly_pay':
        result = d(average_hourly_pay) * d(quantity)
    elif method == 'average_working_day_pay':
        result = d(average_working_day_pay) * d(quantity)
    elif method == 'monthly_salary_day_based':
        result = d(amount) * d(quantity)
    elif method in ('monthly_salary', 'contract_sum'):
        result = d(amount)
    elif method == 'gross_up_from_net':
        # Search cents in ascending order. This gives the smallest gross whose
        # rounded net reaches the requested amount, including tax plateaus.
        target = money(net_target)
        lo, hi = 0, max(1, int(target * 3 * 100) + 100)
        def net(cents):
            gross = Decimal(cents) / 100
            pension = money(gross * d(pension_percent) / 100)
            ui = money(gross * d(unemployment_rate)) if unemployment else Decimal(0)
            tax_base = max(Decimal(0), gross - pension - ui - d(exemption))
            return gross - pension - ui - money(tax_base * d(income_tax_rate))
        while lo < hi:
            mid = (lo + hi) // 2
            if net(mid) >= target:
                hi = mid
            else:
                lo = mid + 1
        result = Decimal(lo) / 100
    else:
        result = d(amount)
    return money(result)

FLAGS = ('income_tax', 'social_tax', 'ui_employee', 'ui_employer',
         'funded_pension', 'social_minimum')
FLAG_LABELS = ('Income tax', 'Social tax', 'Employee unemployment insurance',
               'Employer unemployment insurance', 'Funded pension', 'Counts towards social tax minimum')
PRESETS = (
    # Payroll rules: a correction inherits ordinary employment-pay levies.
    ('base_adjustment', 'Põhipalga korrigeerimine', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: services-contract default, without employment social minimum.
    ('contract', 'Töövõtulepingu tasu', 'income', (1, 1, 1, 1, 1, 0), 'PAYROLL_DEDUCTION'),
    # Payroll rules: net garnishment uses the separate bailiff liability.
    ('bailiff', 'Kinnipidamine kohtutäiturile', 'deduction', (0, 0, 0, 0, 0, 0), 'PAYROLL_BAILIFF'),
    # Payroll rules: uncertain author treatment defaults to fully taxable income pending UAT.
    ('author', 'Autori tasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: uncertain employer parental pay defaults to fully taxable income, excluding state benefits.
    ('parental', 'Vanemapuhkused', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # EMTA Palgatulu: annual leave pay is ordinary taxable employment income.
    ('annual_leave', 'Puhkusetasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # EMTA Palgatulu, TLS section 84: unused leave compensation carries all levies.
    ('unused_leave', 'Kasutamata puhkuse hüvitis', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # EMTA Sotsiaalmaks, TTOS section 12^2: qualifying days 1-8 within limits, income tax only.
    ('employer_sick_pay', 'Tööandja haigushüvitis piirmäära ulatuses', 'income', (1, 0, 0, 0, 0, 0), 'PAYROLL_DEDUCTION'),
    # Payroll rules: overtime remuneration is ordinary taxable employment pay.
    ('overtime', 'Ületunnitöö tasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: extra duties are ordinary taxable employment pay.
    ('extra_work', 'Lisatöö tasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: cash bonuses carry ordinary employment-pay levies.
    ('bonus', 'Preemia ja boonus', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: a thirteenth salary carries ordinary employment-pay levies.
    ('thirteenth_salary', '13. palk', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: public-holiday work remuneration carries all ordinary levies.
    ('public_holiday', 'Riigipühal töötamise tasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: night-work remuneration carries ordinary employment-pay levies.
    ('night_work', 'Öötöö tasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: rest-day work remuneration carries ordinary employment-pay levies.
    ('rest_day', 'Puhkepäeval töötamise tasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: standby remuneration uses the conservative taxable-pay default.
    ('standby', 'Valveaja tasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: substitution pay carries ordinary employment-pay levies.
    ('substitution', 'Asendustasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: employment sales commission carries ordinary pay levies.
    ('commission', 'Müügitasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: employer-paid study leave uses the conservative taxable-pay default.
    ('study_leave', 'Õppepuhkuse tasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules: retained average wages use the conservative taxable-pay default.
    ('average_pay', 'Keskmise töötasu säilitamine', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # EMTA Palgatulu: general agreed severance is fully taxable; statutory UI exceptions need review.
    ('severance', 'Töölepingu lõpetamise hüvitis', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    # Payroll rules / TuMS section 12(3): documented employer costs only, no remuneration.
    ('expense_reimbursement', 'Dokumenteeritud kulude hüvitis', 'income', (0, 0, 0, 0, 0, 0), 'PAYROLL_DEDUCTION'),
    # Payroll rules: salary advance already paid reduces the remaining net payable only.
    ('salary_advance', 'Väljamakstud palga ettemaks', 'deduction', (0, 0, 0, 0, 0, 0), 'PAYROLL_DEDUCTION'),
    # Payroll rules: prior-period advance recovery is a net deduction, never tax relief.
    ('advance_recovery', 'Varasema ettemaksu tasaarvestus', 'deduction', (0, 0, 0, 0, 0, 0), 'PAYROLL_DEDUCTION'),
    # Payroll rules: direct alimony withholding is net; bailiff orders use the bailiff preset.
    ('alimony', 'Elatise kinnipidamine', 'deduction', (0, 0, 0, 0, 0, 0), 'PAYROLL_DEDUCTION'),
    # Payroll rules: union membership fees are net deductions without payroll tax relief.
    ('union_fee', 'Ametiühingu liikmemaksu kinnipidamine', 'deduction', (0, 0, 0, 0, 0, 0), 'PAYROLL_DEDUCTION'),
    # Payroll rules: other agreed withholdings reduce net only, subject to lawful authority.
    ('agreed_deduction', 'Muu kokkulepitud kinnipidamine', 'deduction', (0, 0, 0, 0, 0, 0), 'PAYROLL_DEDUCTION'),
    ('car_compensation', 'Isikliku sõiduauto hüvitis', 'income', (0, 0, 0, 0, 0, 0), 'PAYROLL_DEDUCTION'),
    ('birth_allowance', 'Sünnitoetus', 'income', (0, 0, 0, 0, 0, 0), 'PAYROLL_DEDUCTION'),
    ('work_accident_benefit', 'Tööõnnetushüvitis', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    ('notice_pay', 'Etteteatamisaja hüvitis', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    ('care_leave_pay', 'Hoolduspuhkuse tasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
    ('child_leave_pay', 'Lapsepuhkuse tasu', 'income', (1, 1, 1, 1, 1, 1), 'PAYROLL_DEDUCTION'),
)

TSD_PRESET_CODES = {
    'base_adjustment': 10, 'contract': 17, 'bailiff': 16, 'author': 17,
    'parental': 10, 'annual_leave': 10, 'unused_leave': 10,
    'employer_sick_pay': 24, 'overtime': 10, 'extra_work': 10,
    'bonus': 10, 'thirteenth_salary': 10, 'public_holiday': 10,
    'night_work': 10, 'rest_day': 10, 'standby': 10, 'substitution': 10,
    'commission': 10, 'study_leave': 10, 'average_pay': 10,
    'severance': 33, 'expense_reimbursement': 16, 'salary_advance': 16,
    'advance_recovery': 16, 'alimony': 16, 'union_fee': 16,
    'agreed_deduction': 16, 'car_compensation': 10, 'birth_allowance': 14,
    'work_accident_benefit': 32, 'notice_pay': 33, 'care_leave_pay': 10,
    'child_leave_pay': 10,
}

PRESET_METHODS = {
    'overtime': ('percentage_of_hourly_rate', 150, 6),
    'night_work': ('percentage_of_hourly_rate', 25, 7),
    'public_holiday': ('percentage_of_hourly_rate', 100, 7),
    'bonus': ('percentage_of_base', 0, 5),
    'severance': ('average_monthly_pay', 0, 8),
    'notice_pay': ('average_working_day_pay', 0, 8),
    'car_compensation': ('fixed_sum', 0, 15),
    'birth_allowance': ('fixed_sum', 0, 16),
    'work_accident_benefit': ('fixed_sum', 0, 17),
    'care_leave_pay': ('average_working_day_pay', 0, 9),
    'child_leave_pay': ('average_working_day_pay', 0, 9),
}
PRESET_PALK_ROWS = {
    'base_adjustment': 5, 'contract': 5, 'author': 5, 'parental': 9,
    'annual_leave': 9, 'unused_leave': 9, 'employer_sick_pay': 9,
    'overtime': 6, 'extra_work': 5, 'bonus': 5, 'thirteenth_salary': 8,
    'public_holiday': 7, 'night_work': 7, 'rest_day': 7, 'standby': 5,
    'substitution': 5, 'commission': 5, 'study_leave': 9, 'average_pay': 9,
    'severance': 8, 'expense_reimbursement': 15,
    'car_compensation': 15, 'birth_allowance': 16,
    'work_accident_benefit': 17, 'notice_pay': 8,
    'care_leave_pay': 9, 'child_leave_pay': 9,
}
_CAR_RULES = rules_for(date(2026, 1, 1))
PRESET_DEFAULTS = {'car_compensation': (_CAR_RULES.private_car_rate_per_km, None,
                                        _CAR_RULES.private_car_monthly_limit)}

# Translation keys describe the preset basis, independently of editable organisation names.
PRESET_DESCRIPTIONS = {
    'base_adjustment': 'Gross employment pay correction. All ordinary levies apply.',
    'contract': 'Services-contract remuneration. Confirm recipient levies; no automatic employment social minimum.',
    'bailiff': 'Net withholding under a bailiff order, posted to the bailiff liability.',
    'author': 'Author remuneration. Fully taxable default; accountant must confirm the contract and recipient treatment.',
    'parental': 'Employer parental-leave payment. Fully taxable default; confirm the payment basis and levies. Excludes state benefits.',
    'annual_leave': 'Annual leave pay entered by the bureau. All ordinary employment levies apply.',
    'unused_leave': 'Compensation for unused annual leave. All ordinary employment levies apply.',
    'employer_sick_pay': 'Employer sick pay for days 1 to 8 within statutory limits and with a valid certificate. Income tax only; split any excess into taxable pay.',
    'overtime': 'Overtime remuneration. All ordinary employment levies apply.',
    'extra_work': 'Remuneration for additional duties. All ordinary employment levies apply.',
    'bonus': 'Cash bonus or award for work. All ordinary employment levies apply.',
    'thirteenth_salary': 'Additional annual salary payment. All ordinary employment levies apply.',
    'public_holiday': 'Remuneration for work on a public holiday. All ordinary employment levies apply.',
    'night_work': 'Remuneration for night work. All ordinary employment levies apply.',
    'rest_day': 'Remuneration for work on a rest day. All ordinary employment levies apply.',
    'standby': 'Standby remuneration. Fully taxable default; confirm the agreement.',
    'substitution': 'Remuneration for covering another employee. All ordinary employment levies apply.',
    'commission': 'Sales commission under an employment contract. All ordinary employment levies apply.',
    'study_leave': 'Employer-paid study leave. Fully taxable default; confirm entitlement.',
    'average_pay': 'Average wages retained during an absence. Fully taxable default; confirm the legal basis.',
    'severance': 'General agreed termination compensation, including notice compensation. Fully taxable default; review statutory unemployment insurance exceptions.',
    'expense_reimbursement': 'Reimbursement of documented employer business costs only. All levies off; excludes allowances, private costs and remuneration.',
    'salary_advance': 'Salary advance already paid for this period. Deduct from net once; this line does not execute payment.',
    'advance_recovery': 'Recovery of an earlier salary advance from net pay. Do not also deduct it as a current advance.',
    'alimony': 'Direct alimony withholding from net pay. Use the bailiff category for bailiff orders.',
    'union_fee': 'Agreed union membership fee withheld from net pay. No payroll tax relief.',
    'agreed_deduction': 'Other lawfully agreed withholding from net pay. No change to tax bases.',
    'car_compensation': 'Business use of a private car. Default exemption reference is EUR 0.30/km up to EUR 335/month; verify records, eligibility and current legal limits before approval.',
    'birth_allowance': 'Birth allowance using TSD type 14. Confirm recipient and legal eligibility.',
    'work_accident_benefit': 'Work-accident benefit using TSD type 32. Confirm the legal basis and applicable levies.',
    'notice_pay': 'Notice-period compensation using the average working-day pay method and TSD type 33.',
    'care_leave_pay': 'Care-leave payment. Confirm the payer and legal basis.',
    'child_leave_pay': 'Child-leave payment. Confirm the payer and legal basis.',
}
ACCOUNTS = (
    ('2250', 'Palgavõlg', 'PAYROLL_SALARY_PAYABLE'),
    ('2251', 'Kohtutäituri kinnipidamised', 'PAYROLL_BAILIFF'),
    ('2252', 'Muud palga kinnipidamised', 'PAYROLL_DEDUCTION'),
    ('2253', 'Arvestatud sotsiaalmaks', 'PAYROLL_SOCIAL_ACCRUED'),
    ('2254', 'Kinnipeetud tulumaks', 'PAYROLL_INCOME_WITHHELD'),
    ('2255', 'Kinnipeetud kogumispension', 'PAYROLL_PENSION_WITHHELD'),
    ('2256', 'Arvestatud töötuskindlustusmaksed', 'PAYROLL_UI_ACCRUED'),
    ('2257', 'Tasumisele kuuluv sotsiaalmaks ja kogumispension', 'PAYROLL_SOCIAL_PAYABLE'),
    ('2258', 'Tasumisele kuuluv tulumaks', 'PAYROLL_INCOME_PAYABLE'),
    ('2259', 'Tasumisele kuuluvad töötuskindlustusmaksed', 'PAYROLL_UI_PAYABLE'),
)
ROLES = ('PAYROLL_SALARY', 'PAYROLL_SOCIAL', 'PAYROLL_UI',
         'PAYROLL_VACATION_RESERVE_EXPENSE', 'PAYROLL_VACATION_RESERVE_LIABILITY',
         *(a[2] for a in ACCOUNTS))


def seed_types(tx, organisation_id):
    if tx.dialect == 'postgres':
        metadata_ready = bool(tx.one("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='pay_component_types' AND column_name='is_wage'"))
    else:
        metadata_ready = 'is_wage' in {row['name'] for row in tx.rows('PRAGMA table_info(pay_component_types)')}
    for key, name, direction, flags, role in PRESETS:
        has_tsd = ('tsd_payment_type' in {row['name'] for row in tx.rows('PRAGMA table_info(pay_component_types)')}
                   if tx.dialect != 'postgres' else bool(tx.one("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='pay_component_types' AND column_name='tsd_payment_type'")))
        fields = ','.join(FLAGS) + ',liability_role' + (',is_wage,active' if metadata_ready else '') + (',tsd_payment_type' if has_tsd else '')
        method, pct, _ = PRESET_METHODS.get(key, ('fixed_sum', 0, 5))
        palk_row = PRESET_PALK_ROWS.get(key, 5)
        method_ready = (bool(tx.one("SELECT 1 FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='pay_component_types' AND column_name='calculation_method'"))
                        if tx.dialect == 'postgres' else 'calculation_method' in {row['name'] for row in tx.rows('PRAGMA table_info(pay_component_types)')})
        if method_ready:
            fields += ',calculation_method,default_rate,default_percentage,default_coefficient,palk_row'
        values = (organisation_id + '-component-' + key, organisation_id, key, name, direction, *flags, role)
        if metadata_ready:
            values += (int(key not in {'bailiff', 'parental', 'annual_leave', 'unused_leave', 'employer_sick_pay',
                                      'severance', 'expense_reimbursement', 'salary_advance', 'advance_recovery',
                                      'alimony', 'union_fee', 'agreed_deduction', 'car_compensation', 'birth_allowance'}), 1)
        if has_tsd:
            values += (TSD_PRESET_CODES[key],)
        if method_ready:
            rate, _, coefficient = PRESET_DEFAULTS.get(key, (None, None, None))
            values += (method, db_number(rate) if rate is not None else None, pct or None,
                       db_number(coefficient) if coefficient is not None else None, palk_row)
        tx.execute('INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,' + fields +
                   ') VALUES (' + ','.join('?' for _ in values) +
                   ') ON CONFLICT(organisation_id,preset_key) DO NOTHING',
                   values)


def serialise(row):
    if 'preset_key' in row:
        row['description'] = PRESET_DESCRIPTIONS.get(row['preset_key'], '')
    for key in FLAGS:
        row[key] = bool(row[key])
    for key in ('is_wage', 'active'):
        if key in row:
            row[key] = bool(row[key])
    for key in ('default_rate', 'default_percentage', 'default_coefficient', 'quantity', 'rate', 'coefficient', 'percentage'):
        if key in row and row[key] is not None:
            row[key] = db_number(Decimal(str(row[key])))
    if 'amount' in row:
        row['amount'] = db_number(money(row['amount']))
    return row
