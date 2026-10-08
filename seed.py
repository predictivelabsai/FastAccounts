"""Deterministic-shape, synthetic-only demo books for UK and Estonia."""
from __future__ import annotations

from banking import BankingService
from database import get_database
from documents import DocumentService
from organisations import OrganisationService


DEMO_EMAIL = "demo@fastaccounts.local"


def _seed_organisation(country: str) -> dict:
    """Enrich demo books through normal posting/reconciliation workflows."""
    import calendar
    from core_utils import money, new_id
    db = get_database()
    docs, banking = DocumentService(db), BankingService(db)
    name = "Northstar Studio Ltd" if country == "UK" else "Põhjatäht Teenused OÜ"
    organisation = db.one("SELECT * FROM organisations WHERE name=?", (name,))
    if not organisation:
        organisation = OrganisationService(db).create(
            name=name, country_code=country,
            entity_type="UK_COMPANY" if country == "UK" else "EE_OU", owner_email=DEMO_EMAIL,
            registration_no="09999991" if country == "UK" else "14999991",
            vat_no="GB999999973" if country == "UK" else "EE149999991")
    oid = organisation['id']
    with db.transaction() as tx:
        for month in range(1, 13):
            period = f'2026-{month:02d}'
            tx.execute("INSERT INTO fiscal_periods(id,organisation_id,code,starts_on,ends_on) VALUES (?,?,?,?,?) ON CONFLICT(organisation_id,code) DO NOTHING",
                       (new_id(), oid, period, period+'-01', f'{period}-{calendar.monthrange(2026, month)[1]}'))
    accounts = {r['system_role']: r['id'] for r in db.rows('SELECT * FROM accounts WHERE organisation_id=?', (oid,))}
    taxes = {r['code']: r['id'] for r in db.rows('SELECT * FROM tax_codes WHERE organisation_id=?', (oid,))}
    standard = 'UK20' if country == 'UK' else 'EE24'
    names = ({
        'customer': ['Brightline Media Ltd', 'Willow Design Ltd', 'Birch Research Ltd', 'Meadow Books Ltd', 'Harbour Training Ltd'],
        'supplier': ['Pine Cloud Ltd', 'Oak Office Ltd', 'River Print Ltd', 'Hillside Stays Ltd', 'Cedar Media Ltd'],
    } if country == 'UK' else {
        'customer': ['Sinilille Teenused OÜ', 'Kase Disain OÜ', 'Niidu Uuringud OÜ', 'Sadama Koolitus OÜ', 'Tamme Stuudio OÜ'],
        'supplier': ['Männi Pilveteenused OÜ', 'Kuuse Kontor OÜ', 'Jõe Trükikoda OÜ', 'Mäe Majutus OÜ', 'Saare Kirjastus OÜ'],
    })
    contacts = {}
    for kind, entries in names.items():
        contacts[kind] = []
        for index, contact_name in enumerate(entries, 1):
            contact = db.one('SELECT * FROM contacts WHERE organisation_id=? AND name=?', (oid, contact_name))
            if not contact:
                contact = docs.create_contact(oid, name=contact_name, country_code='GB' if country == 'UK' else 'EE',
                    contact_type=kind, email=f'{kind}{index}@example.invalid', address='1 Example Street')
            contacts[kind].append(contact)
    if not db.one("SELECT id FROM items WHERE organisation_id=? AND code='CONSULT'", (oid,)):
        docs.create_item(oid, code='CONSULT', name='Consulting service' if country == 'UK' else 'Nõustamisteenus', sales_account_id=accounts['SALES'],
                         tax_code_id=taxes[standard], unit_price='750')
    bank_name = "Operating account" if country == "UK" else "Arvelduskonto"
    bank = db.one("SELECT * FROM bank_accounts WHERE organisation_id=? AND name=?", (oid, bank_name))
    if not bank:
        bank = docs.create_bank_account(oid, name=bank_name, currency=organisation['base_currency'],
            iban='EE001010000000000001' if country == 'EE' else '', sort_code='12-34-56' if country == 'UK' else '')

    def bank_row(document, kind, amount, booking_date, suffix, reconcile=False):
        external_id = f'BANK-{country}-{suffix}'
        if db.one('SELECT id FROM bank_transactions WHERE organisation_id=? AND external_id=?', (oid, external_id)):
            return
        number = document['number'] if kind == 'invoice' else document['supplier_number']
        signed = amount if kind == 'invoice' else -amount
        content = ('date,amount,currency,counterparty,reference,id\n'
                   f"{booking_date},{signed},{organisation['base_currency']},{document['contact_name']},{number},{external_id}\n").encode()
        banking.import_csv(oid, bank['id'], content, actor=DEMO_EMAIL)
        transaction = db.one('SELECT id FROM bank_transactions WHERE organisation_id=? AND external_id=?', (oid, external_id))
        if reconcile:
            banking.reconcile_to_document(transaction['id'], target_type=kind, target_id=document['id'], actor=DEMO_EMAIL)

    for index in range(18):
        month, day = 5 + index // 3, 1 + index % 3
        issued = f'2026-{month:02d}-{day:02d}'
        reference = f'SALES-2026-{index+1:03d}'
        invoice = db.one('SELECT id FROM invoices WHERE organisation_id=? AND reference=?', (oid, reference))
        if invoice:
            invoice = docs.invoice(invoice['id'], oid)
        else:
            code, description = standard, 'Consulting engagement' if country == 'UK' else 'Nõustamisteenus'
            if country == 'EE' and index % 6 == 4:
                code, description = 'EE13', 'Külaliste majutus'
            elif country == 'EE' and index % 6 == 5:
                code, description = 'EE9', 'Trükitud raamatud'
            invoice = docs.create_invoice(oid, contact_id=contacts['customer'][index % 5]['id'], issue_date=issued,
                due_date='2026-09-10' if index == 12 else f'2026-{month:02d}-{day+14:02d}',
                actor=DEMO_EMAIL, reference=reference,
                lines=[dict(description=description, quantity=1, unit_price=str(600+index*85),
                            account_id=accounts['SALES'], tax_code_id=taxes[code])])
        if invoice['status'] == 'Draft':
            invoice = docs.issue_invoice(invoice['id'], actor=DEMO_EMAIL)
        partial = 9 <= index < 12
        amount = money(invoice['total']) / 2 if partial else money(invoice['total'])
        payment_date = f'2026-{max(7, month):02d}-{day+4:02d}'
        bank_row(invoice, 'invoice', money(amount), payment_date, f'RECEIPT-{index+1:03d}', reconcile=index < 12)
        if partial:
            bank_row(invoice, 'invoice', money(invoice['total'])-money(amount), '2026-09-08', f'BALANCE-{index+1:03d}')
    for index in range(8):
        month, day = 7 + index // 2, 1 + index % 2
        number = f'SUP-2026-{index+1:03d}'
        bill = db.one('SELECT id FROM bills WHERE organisation_id=? AND supplier_number=?', (oid, number))
        if bill:
            bill = docs.bill(bill['id'])
        else:
            code, description = standard, 'Office services' if country == 'UK' else 'Kontoriteenused'
            if country == 'EE' and index == 3:
                code, description = 'EE13', 'Majutus töölähetusel'
            elif country == 'EE' and index == 4:
                code, description = 'EE9', 'Erialaraamatud'
            bill = docs.create_bill(oid, contact_id=contacts['supplier'][index % 5]['id'], supplier_number=number,
                bill_date=f'2026-{month:02d}-{day:02d}', due_date=f'2026-{month:02d}-{day+14:02d}', actor=DEMO_EMAIL,
                lines=[dict(description=description, quantity=1, unit_price=str(120+index*65),
                            account_id=accounts['EXPENSE'], tax_code_id=taxes[code])])
        if bill['status'] == 'Draft':
            bill = (docs.submit_bill_for_review(bill['id'], actor=DEMO_EMAIL) if index == 7
                    else docs.approve_bill(bill['id'], actor=DEMO_EMAIL))
        if index < 7:
            amount = money(bill['total']) / 2 if index in (3, 4) else money(bill['total'])
            bank_row(bill, 'bill', money(amount), f'2026-{month:02d}-{day+4:02d}', f'PAYMENT-{index+1:03d}', reconcile=index < 5)
    return organisation


def _seed_automation(organisation: dict) -> None:
    from datetime import date, timedelta
    from automation import AutomationService
    db = get_database()
    oid, name = organisation['id'], "Retainer – Willow Design"
    if db.one("SELECT id FROM invoice_schedules WHERE organisation_id=? AND name=?", (oid, name)):
        return
    docs = DocumentService(db)
    contact = db.one("SELECT * FROM contacts WHERE organisation_id=? AND name=?", (oid, "Willow Design Ltd"))
    if not contact:
        contact = docs.create_contact(oid, name="Willow Design Ltd", country_code="GB",
                                      contact_type="customer", email="willow@example.invalid")
    reference = "AUTOMATION-WILLOW-TEMPLATE"
    invoice = db.one("SELECT id FROM invoices WHERE organisation_id=? AND reference=?", (oid, reference))
    if not invoice:
        account = db.one("SELECT id FROM accounts WHERE organisation_id=? AND system_role='SALES'", (oid,))
        tax = db.one("SELECT id FROM tax_codes WHERE organisation_id=? AND code='UK20'", (oid,))
        invoice = docs.create_invoice(oid, contact_id=contact['id'], issue_date=date.today().isoformat(),
            due_date=(date.today() + timedelta(days=14)).isoformat(), actor=DEMO_EMAIL, reference=reference,
            lines=[dict(description="Monthly design retainer", quantity=1, unit_price="750.00",
                        account_id=account['id'], tax_code_id=tax['id'])])
    AutomationService(db).create_schedule(oid, template_invoice_id=invoice['id'], interval_kind="monthly",
        next_run_date=date.today() + timedelta(days=7), name=name, auto_email=False, actor=DEMO_EMAIL)


def _seed_payroll(organisation: dict) -> None:
    from payroll import PayrollService
    from core_utils import new_id
    db = get_database()
    service = PayrollService(db)
    org_id = organisation['id']
    existing = {e['name']: e for e in service.employees(org_id)}
    employees = [
        dict(name='Mari Maasikas', gross_salary='2000.00', apply_tax_free_minimum=True),
        dict(name='Jaan Tamm', gross_salary='2400.00'),
        dict(name='Kati Kask', gross_salary='3200.00', funded_pension_percent=4),
        dict(name='Peeter Saar', gross_salary='1800.00'),
        dict(name='Liis Kuusk', gross_salary='1250.00'),
        dict(name='Toomas Oja', gross_salary='1500.00', board_member=True),
    ]
    for index, employee in enumerate(employees, 1):
        legacy = existing.get('Demo ' + employee['name'])
        if legacy and employee['name'] not in existing:
            service.save_employee(org_id, actor=DEMO_EMAIL, employee_id=legacy['id'], name=employee['name'])
        elif employee['name'] not in existing:
            service.save_employee(org_id, actor=DEMO_EMAIL, email=f'payroll{index}@example.invalid', **employee)
    for period in ('2026-07', '2026-08', '2026-09', '2026-10'):
        with db.transaction() as tx:
            tx.execute("INSERT INTO fiscal_periods(id,organisation_id,code,starts_on,ends_on) VALUES (?,?,?,?,?) ON CONFLICT(organisation_id,code) DO NOTHING",
                       (new_id(), org_id, period, period+'-01', period+('-30' if period.endswith('09') else '-31')))
        run = next((r for r in service.runs(org_id) if r['period'] == period), None)
        if run is None:
            run = service.create_run(org_id, period=period, actor=DEMO_EMAIL)
        if run['status'] == 'Draft' and period != '2026-10':
            service.approve(org_id, run['id'], actor=DEMO_EMAIL)


SAMPLE_PAYROLL_ORG = "Demo OÜ (sample payroll)"
# Seven synthetic Estonian employees (FastHRM fixture ee_sample_employees.json,
# test IDs only) covering full-time, part-time, hourly, II pillar 0/2/4/6%,
# the basic exemption, the social tax minimum and a board-member fee.
SAMPLE_PAYROLL_EMPLOYEES = [
    dict(name='Mari Tamm', personal_id='48803142718', email='mari.tamm@demo-ou.example', gross_salary='946.00',
         apply_tax_free_minimum=True, employment_start_date='2024-04-01'),
    dict(name='Jaan Kask', personal_id='37911025128', email='jaan.kask@demo-ou.example', gross_salary='2400.00',
         employment_start_date='2019-09-16'),
    dict(name='Kadri Saar', personal_id='49207253384', email='kadri.saar@demo-ou.example', gross_salary='3800.00',
         funded_pension_percent=4, employment_start_date='2021-02-01'),
    dict(name='Andres Mets', personal_id='37501302245', email='andres.mets@demo-ou.example', gross_salary='5500.00',
         funded_pension_percent=6, employment_start_date='2018-05-02'),
    dict(name='Liis Kuusk', personal_id='60106094177', email='liis.kuusk@demo-ou.example', gross_salary='700.00',
         fte='0.5', funded_pension_percent=0, apply_tax_free_minimum=True, employment_start_date='2025-08-18'),
    dict(name='Peeter Oja', personal_id='39610216556', email='peeter.oja@demo-ou.example', pay_basis='hourly',
         hourly_rate='8.00', apply_tax_free_minimum=True, employment_start_date='2026-01-05'),
    dict(name='Toomas Rebane', personal_id='37204181439', email='toomas.rebane@demo-ou.example', pay_basis='board_fee',
         gross_salary='1500.00', funded_pension_percent=2, employment_start_date='2018-01-10'),
]
# Hours for the hourly employee: September approved, October left as a draft to review.
SAMPLE_PAYROLL_RUNS = {'2026-09': '168', '2026-10': '176'}


def _seed_sample_payroll() -> dict:
    """Clearly labelled sample-payroll organisation, created through the normal services."""
    import calendar
    from core_utils import new_id
    from payroll import PayrollService
    db = get_database()
    organisation = db.one("SELECT * FROM organisations WHERE name=?", (SAMPLE_PAYROLL_ORG,))
    if not organisation:
        organisation = OrganisationService(db).create(
            name=SAMPLE_PAYROLL_ORG, country_code="EE", entity_type="EE_OU", owner_email=DEMO_EMAIL,
            registration_no="14999992")
    oid = organisation['id']
    service = PayrollService(db)
    existing = {e['name']: e for e in service.employees(oid)}
    for employee in SAMPLE_PAYROLL_EMPLOYEES:
        if employee['name'] not in existing:
            service.save_employee(oid, actor=DEMO_EMAIL, **employee)
    hourly = {e['id']: e for e in service.employees(oid) if e['pay_basis'] == 'hourly'}
    for period, hours in SAMPLE_PAYROLL_RUNS.items():
        year, month = map(int, period.split('-'))
        with db.transaction() as tx:
            tx.execute("INSERT INTO fiscal_periods(id,organisation_id,code,starts_on,ends_on) VALUES (?,?,?,?,?) ON CONFLICT(organisation_id,code) DO NOTHING",
                       (new_id(), oid, period, period+'-01', f'{period}-{calendar.monthrange(year, month)[1]}'))
        run = next((r for r in service.runs(oid) if r['period'] == period), None)
        if run is None:
            run = service.create_run(oid, period=period, actor=DEMO_EMAIL, hours={eid: hours for eid in hourly})
        if run['status'] == 'Draft' and period != '2026-10':
            service.approve(oid, run['id'], actor=DEMO_EMAIL)
    return organisation


def seed_demo() -> list[dict]:
    """Seed the UK and Estonian demo books (returned) plus the sample-payroll organisation."""
    db = get_database()
    db.migrate()
    organisations = [_seed_organisation("UK"), _seed_organisation("EE")]
    _seed_automation(organisations[0])
    _seed_payroll(organisations[1])
    _seed_sample_payroll()
    return organisations


if __name__ == "__main__":
    for organisation in seed_demo():
        print(f"Seeded {organisation['name']} ({organisation['id']})")
    sample = get_database().one("SELECT id,name FROM organisations WHERE name=?", (SAMPLE_PAYROLL_ORG,))
    print(f"Seeded {sample['name']} ({sample['id']})")
