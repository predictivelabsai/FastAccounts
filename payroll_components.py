"""Editable bureau defaults, frozen separately on each payroll item.

Defaults require accountant UAT against EMTA's social tax and withholding rules:
https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/sotsiaalmaks
https://www.emta.ee/ariklient/maksud-ja-tasumine/tulumaks-ja-sotsiaalmaks/maksumaarad
Bureau users may override every levy flag for each period.
"""
from core_utils import db_number, money

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
    'agreed_deduction': 16,
}

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
        values = (organisation_id + '-component-' + key, organisation_id, key, name, direction, *flags, role)
        if metadata_ready:
            values += (int(key not in {'bailiff', 'parental', 'annual_leave', 'unused_leave', 'employer_sick_pay',
                                      'severance', 'expense_reimbursement', 'salary_advance', 'advance_recovery',
                                      'alimony', 'union_fee', 'agreed_deduction'}), 1)
        if has_tsd:
            values += (TSD_PRESET_CODES[key],)
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
    if 'amount' in row:
        row['amount'] = db_number(money(row['amount']))
    return row
