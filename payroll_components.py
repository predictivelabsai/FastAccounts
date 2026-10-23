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
    ('bailiff', 'Kinnipidamine kohtutäiturile', 'deduction', (0, 0, 0, 0, 0, 0), 'PAYROLL_BAILIFF'),
    ('author', 'Autori tasu', 'income', (1, 1, 0, 0, 0, 1), 'PAYROLL_DEDUCTION'),
    ('parental', 'Vanemapuhkused', 'income', (1, 0, 0, 0, 0, 0), 'PAYROLL_DEDUCTION'),
)
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
ROLES = ('PAYROLL_SALARY', 'PAYROLL_SOCIAL', 'PAYROLL_UI', *(a[2] for a in ACCOUNTS))


def seed_types(tx, organisation_id):
    for key, name, direction, flags, role in PRESETS:
        tx.execute('INSERT INTO pay_component_types(id,organisation_id,preset_key,name,direction,' +
                   ','.join(FLAGS) + ',liability_role) VALUES (' + ','.join('?' for _ in range(12)) +
                   ') ON CONFLICT(organisation_id,preset_key) DO NOTHING',
                   (organisation_id + '-component-' + key, organisation_id, key, name, direction, *flags, role))


def serialise(row):
    for key in FLAGS:
        row[key] = bool(row[key])
    if 'amount' in row:
        row['amount'] = db_number(money(row['amount']))
    return row
