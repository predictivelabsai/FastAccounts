from __future__ import annotations

import pytest

from governance import CHECKLIST_ITEMS, GovernanceService
from organisations import OrganisationService


def test_invitation_token_is_hashed_and_acceptance_adds_membership(db,uk_org):
    service=GovernanceService(db)
    invitation,token=service.invite(uk_org["id"],email="accountant@example.test",role="accountant",actor="owner@example.test")
    stored=db.one("SELECT * FROM invitations WHERE id=?",(invitation["id"],))
    assert token not in stored["token_hash"]
    service.accept_invitation(token,email="accountant@example.test")
    assert OrganisationService(db).role(uk_org["id"],"accountant@example.test")=="accountant"
    with pytest.raises(ValueError,match="no longer pending"):
        service.accept_invitation(token,email="accountant@example.test")


def test_month_end_checklist_and_ledger_export_hash(db,uk_org):
    service=GovernanceService(db)
    period=db.one("SELECT * FROM fiscal_periods WHERE organisation_id=? ORDER BY starts_on LIMIT 1",(uk_org["id"],))
    assert len(service.checklist(period["id"]))==len(CHECKLIST_ITEMS)
    completed=service.set_checklist_item(period["id"],"bank_reconciled",status="Complete",actor="accountant@example.test")
    assert completed["status"]=="Complete"
    data=service.ledger_export(uk_org["id"],start=period["starts_on"],end=period["ends_on"],actor="accountant@example.test")
    assert data.startswith(b"entry_date,") and db.scalar("SELECT COUNT(*) FROM accounting_exports")==1
