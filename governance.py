"""Invitations, close checklists, retention holds, and audit exports."""
from __future__ import annotations

import csv
import hashlib
import io
import secrets
from datetime import datetime, timedelta, timezone

from core_utils import audit, new_id, sha256_bytes, utc_now
from database import Database, get_database
from ledger import LedgerService
from organisations import ROLES, OrganisationService


CHECKLIST_ITEMS = (
    "bank_reconciled", "receivables_reviewed", "payables_reviewed",
    "evidence_complete", "tax_workpaper_reviewed", "trial_balance_reviewed",
)


class GovernanceService:
    def __init__(self, db: Database | None = None):
        self.db = db or get_database()

    def invite(self, organisation_id: str, *, email: str, role: str,
               actor: str, valid_days: int = 7) -> tuple[dict, str]:
        OrganisationService(self.db).require(organisation_id, actor, {"owner", "administrator"})
        if role not in ROLES or not 1 <= valid_days <= 30:
            raise ValueError("Invalid invitation role or validity")
        raw_token, invitation_id, now = secrets.token_urlsafe(32), new_id(), utc_now()
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires = (datetime.now(timezone.utc) + timedelta(days=valid_days)).isoformat(timespec="seconds")
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO invitations(id,organisation_id,email,role,token_hash,expires_at,invited_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (invitation_id, organisation_id, email.strip().lower(), role, token_hash, expires, actor, now),
            )
            audit(tx, organisation_id, actor, "invitation.created", "invitation", invitation_id,
                  {"email": email.strip().lower(), "role": role, "expires_at": expires})
        return self.db.one("SELECT id,organisation_id,email,role,status,expires_at,created_at FROM invitations WHERE id=?", (invitation_id,)) or {}, raw_token

    def accept_invitation(self, token: str, *, email: str) -> dict:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.db.transaction() as tx:
            invitation = tx.one("SELECT * FROM invitations WHERE token_hash=?", (digest,))
            if not invitation or invitation["status"] != "Pending":
                raise ValueError("Invitation is invalid or no longer pending")
            if invitation["email"].lower() != email.strip().lower():
                raise ValueError("Invitation email does not match the signed-in user")
            if datetime.fromisoformat(invitation["expires_at"]) < datetime.now(timezone.utc):
                tx.execute("UPDATE invitations SET status='Expired' WHERE id=?", (invitation["id"],))
                raise ValueError("Invitation has expired")
            existing = tx.one("SELECT id FROM memberships WHERE organisation_id=? AND lower(email)=lower(?)",
                              (invitation["organisation_id"], email.strip()))
            if not existing:
                tx.execute("INSERT INTO memberships(id,organisation_id,email,role,created_at) VALUES (?,?,?,?,?)",
                           (new_id(), invitation["organisation_id"], email.strip().lower(), invitation["role"], utc_now()))
            tx.execute("UPDATE invitations SET status='Accepted' WHERE id=?", (invitation["id"],))
            audit(tx, invitation["organisation_id"], email, "invitation.accepted", "invitation", invitation["id"])
        return OrganisationService(self.db).get(invitation["organisation_id"])

    def checklist(self, period_id: str) -> list[dict]:
        period = self.db.one("SELECT * FROM fiscal_periods WHERE id=?", (period_id,))
        if not period:
            raise KeyError("Period not found")
        with self.db.transaction() as tx:
            for item in CHECKLIST_ITEMS:
                if not tx.one("SELECT id FROM month_end_checklists WHERE period_id=? AND item_key=?", (period_id, item)):
                    tx.execute(
                        "INSERT INTO month_end_checklists(id,organisation_id,period_id,item_key) VALUES (?,?,?,?)",
                        (new_id(), period["organisation_id"], period_id, item),
                    )
        return self.db.rows("SELECT * FROM month_end_checklists WHERE period_id=? ORDER BY item_key", (period_id,))

    def set_checklist_item(self, period_id: str, item_key: str, *, status: str,
                           actor: str, notes: str = "") -> dict:
        if status not in {"Open", "Complete", "Not Applicable"}:
            raise ValueError("Invalid checklist status")
        self.checklist(period_id)
        now = utc_now()
        with self.db.transaction() as tx:
            row = tx.one("SELECT * FROM month_end_checklists WHERE period_id=? AND item_key=?", (period_id, item_key))
            if not row:
                raise KeyError("Checklist item not found")
            tx.execute(
                "UPDATE month_end_checklists SET status=?,completed_by=?,completed_at=?,notes=? WHERE id=?",
                (status, actor if status != "Open" else None, now if status != "Open" else None,
                 notes or None, row["id"]),
            )
            audit(tx, row["organisation_id"], actor, "close.checklist_updated", "month_end_checklist", row["id"],
                  {"item": item_key, "status": status})
        return self.db.one("SELECT * FROM month_end_checklists WHERE id=?", (row["id"],)) or {}

    def add_retention_hold(self, organisation_id: str, *, object_type: str, object_id: str,
                           retain_until: str, reason: str, actor: str) -> dict:
        if not reason.strip():
            raise ValueError("A statutory or legal retention reason is required")
        hold_id = new_id()
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO retention_holds(id,organisation_id,object_type,object_id,retain_until,reason,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (hold_id, organisation_id, object_type, object_id, retain_until, reason.strip(), actor, utc_now()),
            )
            audit(tx, organisation_id, actor, "retention.hold_created", "retention_hold", hold_id,
                  {"object_type": object_type, "object_id": object_id, "retain_until": retain_until})
        return self.db.one("SELECT * FROM retention_holds WHERE id=?", (hold_id,)) or {}

    def ledger_export(self, organisation_id: str, *, start: str, end: str, actor: str) -> bytes:
        rows = LedgerService(self.db).general_ledger(organisation_id, start=start, end=end)
        output = io.StringIO()
        fields = ["entry_date", "voucher_type", "voucher_code", "account_code", "account_name",
                  "debit", "credit", "currency", "contact_name", "memo"]
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)
        data = output.getvalue().encode()
        with self.db.transaction() as tx:
            export_id = new_id()
            tx.execute(
                "INSERT INTO accounting_exports(id,organisation_id,export_type,period_start,period_end,sha256,row_count,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (export_id, organisation_id, "general_ledger_csv", start, end,
                 sha256_bytes(data), len(rows), actor, utc_now()),
            )
            audit(tx, organisation_id, actor, "accounting.exported", "accounting_export", export_id,
                  {"row_count": len(rows), "sha256": sha256_bytes(data)})
        return data
