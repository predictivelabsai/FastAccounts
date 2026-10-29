from datetime import date

from bureau_overview import PayrollBureauOverviewService
from organisations import OrganisationService


def test_bureau_overview_only_includes_the_signed_in_users_organisations(db, ee_org):
    service = OrganisationService(db)
    second = service.create(name='Second bureau client', country_code='EE', entity_type='EE_OU',
                            owner_email='other@example.test')
    third = service.create(name='Unrelated bureau client', country_code='EE', entity_type='EE_OU',
                           owner_email='other@example.test')
    with db.transaction() as tx:
        tx.execute('INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)',
                   ('member-second', second['id'], 'owner@example.test', 'accountant', '2026-01-01'))
    rows = PayrollBureauOverviewService(db).for_user('owner@example.test', today=date(2026, 10, 29))
    assert {row['id'] for row in rows} == {ee_org['id'], second['id']}
    assert next(row for row in rows if row['id'] == second['id'])['role'] == 'accountant'
    assert all(row['period'] == '2026-10' for row in rows)
    assert all(row['palk_due_date'] == row['tsd_due_date'] == '2026-11-10' for row in rows)
