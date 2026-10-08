"""Accountant-reviewed staging and application of connector employee records."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from psycopg.errors import UniqueViolation

import connectors.registry as connector_registry
from core_utils import audit, canonical_json, new_id, utc_now
from database import Database, get_database
from integration_service import IntegrationService
from payroll import PayrollConflict, PayrollService


EMPLOYEE_FIELDS = {
    "name",
    "email",
    "personal_id",
    "gross_salary",
    "funded_pension_percent",
    "apply_tax_free_minimum",
    "board_member",
    "active",
    "pay_basis",
    "fte",
    "hourly_rate",
    "social_tax_minimum_exemption",
    "employment_start_date",
    "employment_end_date",
}
EMPLOYEE_COMPARE_FIELDS = tuple(sorted(EMPLOYEE_FIELDS))
DECIMAL_EMPLOYEE_FIELDS = {"gross_salary", "funded_pension_percent", "fte", "hourly_rate"}
STAGED_STATUSES = ("Pending", "Approved", "Rejected", "Applied", "Failed")


class ImportService:
    def __init__(self, db: Database | None = None, *, integration: IntegrationService | None = None):
        self.db = db or get_database()
        self.integration = integration or IntegrationService(self.db)
        self.payroll = PayrollService(self.db)

    def _connection_material(
        self,
        organisation_id: str,
        provider: str,
        credentials: dict | None,
        config: dict | None,
    ) -> tuple[str, dict, dict]:
        key = provider.strip().lower()
        try:
            connector_registry.registration_for(key)
        except KeyError as error:
            raise ValueError("Unknown integration provider") from error
        row = self.db.one(
            "SELECT encrypted_credentials,config_json FROM integration_connections "
            "WHERE organisation_id=? AND provider=?",
            (organisation_id, key),
        )
        if not row:
            raise KeyError("Integration connection must be configured before syncing")
        stored_credentials = (
            self.integration.vault.decrypt(row["encrypted_credentials"])
            if row.get("encrypted_credentials")
            else {}
        )
        stored_config = json.loads(row.get("config_json") or "{}")
        return (
            key,
            dict(stored_credentials if credentials is None else credentials),
            dict(stored_config if config is None else config),
        )

    def _last_cursor(self, organisation_id: str, provider: str, object_type: str) -> str | None:
        row = self.db.one(
            "SELECT cursor_after FROM sync_runs WHERE organisation_id=? AND provider=? "
            "AND object_type=? AND direction='import' AND cursor_after IS NOT NULL "
            "AND status IN ('Completed','Review Required') ORDER BY created_at DESC,id DESC LIMIT 1",
            (organisation_id, provider, object_type),
        )
        return row["cursor_after"] if row else None

    def run_sync(
        self,
        organisation_id: str,
        provider: str,
        object_type: str,
        *,
        actor: str,
        credentials: dict | None = None,
        config: dict | None = None,
    ) -> dict:
        if object_type not in {"employee", "employees"}:
            raise ValueError("The reviewed import pipeline currently supports employees only")
        key, resolved_credentials, resolved_config = self._connection_material(
            organisation_id, provider, credentials, config
        )
        cursor_before = self._last_cursor(organisation_id, key, object_type)
        sync = self.integration.start_sync(
            organisation_id,
            provider=key,
            direction="import",
            object_type=object_type,
            cursor=cursor_before or "",
        )
        sync_id = sync["id"]
        try:
            with self.db.transaction() as tx:
                audit(
                    tx,
                    organisation_id,
                    actor,
                    "integration.sync_started",
                    "sync_run",
                    sync_id,
                    {"provider": key, "object_type": object_type},
                )
            connector = connector_registry.connector_for(
                key, credentials=resolved_credentials, config=resolved_config
            )
            result = connector.pull(object_type, cursor=cursor_before)
            if not result.ok:
                raise ValueError(result.message or f"{key} did not return employee records")
            records = list(result.records)
            if any(not isinstance(record, Mapping) for record in records):
                raise ValueError("Connector employee records must be objects")
            cursor_after = result.cursor if result.cursor is not None else cursor_before
            staged_ids = self._stage_records(
                organisation_id,
                sync_id,
                key,
                object_type,
                [dict(record) for record in records],
                cursor_after,
                actor,
            )
        except Exception as error:
            safe_error = str(error) if isinstance(error, (ValueError, KeyError)) else "Connector pull failed"
            self.integration.complete_sync(sync_id, error=safe_error)
            with self.db.transaction() as tx:
                audit(
                    tx,
                    organisation_id,
                    actor,
                    "integration.sync_failed",
                    "sync_run",
                    sync_id,
                    {"provider": key, "object_type": object_type},
                )
            if isinstance(error, (ValueError, KeyError)):
                raise
            raise ValueError(safe_error) from error
        return self.get_staged(organisation_id, sync_run_id=sync_id)["summary"]

    def _stage_records(
        self,
        organisation_id: str,
        sync_id: str,
        provider: str,
        object_type: str,
        records: list[dict[str, Any]],
        cursor_after: str | None,
        actor: str,
    ) -> list[str]:
        now = utc_now()
        staged_ids: list[str] = []
        with self.db.transaction() as tx:
            for payload in records:
                external_id = self._external_id(payload)
                matched_id, review_note = self._employee_match(tx, organisation_id, payload)
                existing = None
                if external_id:
                    existing = tx.one(
                        "SELECT id FROM import_staged_records WHERE organisation_id=? "
                        "AND sync_run_id=? AND provider=? AND object_type=? AND external_id=? "
                        "AND status='Pending'",
                        (organisation_id, sync_id, provider, object_type, external_id),
                    )
                if existing:
                    staged_id = existing["id"]
                    tx.execute(
                        "UPDATE import_staged_records SET external_payload_json=?,"
                        "matched_local_employee_id=?,review_note=?,updated_at=? "
                        "WHERE organisation_id=? AND id=?",
                        (
                            canonical_json(payload),
                            matched_id,
                            review_note,
                            now,
                            organisation_id,
                            staged_id,
                        ),
                    )
                else:
                    staged_id = new_id()
                    tx.execute(
                        "INSERT INTO import_staged_records(id,organisation_id,sync_run_id,provider,"
                        "object_type,external_id,external_payload_json,status,matched_local_employee_id,"
                        "review_note,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'Pending',?,?,?,?)",
                        (
                            staged_id,
                            organisation_id,
                            sync_id,
                            provider,
                            object_type,
                            external_id,
                            canonical_json(payload),
                            matched_id,
                            review_note,
                            now,
                            now,
                        ),
                    )
                    staged_ids.append(staged_id)
            self.integration.complete_sync(
                sync_id,
                read_count=len(records),
                cursor=cursor_after or "",
                review_required=bool(staged_ids),
                tx=tx,
            )
            audit(
                tx,
                organisation_id,
                actor,
                "integration.records_staged",
                "sync_run",
                sync_id,
                {
                    "provider": provider,
                    "object_type": object_type,
                    "read_count": len(records),
                    "staged_record_ids": staged_ids,
                },
            )
        return staged_ids

    @staticmethod
    def _external_id(payload: Mapping[str, Any]) -> str | None:
        value = payload.get("external_id")
        if value in (None, ""):
            value = payload.get("id")
        if value in (None, ""):
            return None
        return str(value).strip() or None

    @staticmethod
    def _employee_match(tx, organisation_id: str, payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
        email = payload.get("email")
        personal_id = payload.get("personal_id")
        email = email.strip() if isinstance(email, str) else ""
        personal_id = personal_id.strip() if isinstance(personal_id, str) else ""
        clauses: list[str] = []
        params: list[Any] = [organisation_id]
        if email:
            clauses.append("lower(trim(email))=lower(?)")
            params.append(email)
        if personal_id:
            clauses.append("trim(personal_id)=?")
            params.append(personal_id)
        if not clauses:
            return None, None
        matches = tx.rows(
            "SELECT id,name FROM employees WHERE organisation_id=? AND ("
            + " OR ".join(clauses)
            + ") ORDER BY name,id",
            tuple(params),
        )
        if len(matches) == 1:
            return matches[0]["id"], None
        if len(matches) > 1:
            names = ", ".join(item["name"] for item in matches)
            return None, f"Ambiguous employee match: {names}"
        return None, None

    def get_staged(
        self,
        organisation_id: str,
        sync_run_id: str | None = None,
        status: str | None = None,
    ) -> dict:
        if status is not None and status not in STAGED_STATUSES:
            raise ValueError("Invalid staged-record status")
        if sync_run_id:
            sync = self.db.one(
                "SELECT * FROM sync_runs WHERE organisation_id=? AND id=?",
                (organisation_id, sync_run_id),
            )
            if not sync:
                raise KeyError("Sync run not found")
        query = (
            "SELECT s.*,e.name AS matched_local_employee_name FROM import_staged_records s "
            "LEFT JOIN employees e ON e.organisation_id=s.organisation_id "
            "AND e.id=s.matched_local_employee_id WHERE s.organisation_id=?"
        )
        params: list[Any] = [organisation_id]
        if sync_run_id:
            query += " AND s.sync_run_id=?"
            params.append(sync_run_id)
        if status:
            query += " AND s.status=?"
            params.append(status)
        query += " ORDER BY s.created_at,s.id"
        records = self.db.rows(query, tuple(params))
        for record in records:
            record["external_payload"] = json.loads(record.pop("external_payload_json"))
        summary = self._sync_summary(organisation_id, sync_run_id) if sync_run_id else None
        return {"summary": summary, "records": records}

    def _sync_summary(self, organisation_id: str, sync_run_id: str) -> dict:
        sync = self.db.one(
            "SELECT * FROM sync_runs WHERE organisation_id=? AND id=?",
            (organisation_id, sync_run_id),
        )
        if not sync:
            raise KeyError("Sync run not found")
        counts = {status: 0 for status in STAGED_STATUSES}
        for row in self.db.rows(
            "SELECT status,COUNT(*) AS record_count FROM import_staged_records "
            "WHERE organisation_id=? AND sync_run_id=? GROUP BY status",
            (organisation_id, sync_run_id),
        ):
            counts[row["status"]] = int(row["record_count"])
        return {
            "id": sync["id"],
            "provider": sync["provider"],
            "object_type": sync["object_type"],
            "direction": sync["direction"],
            "status": sync["status"],
            "read_count": sync["read_count"],
            "write_count": sync["write_count"],
            "conflict_count": sync["conflict_count"],
            "staged_counts": counts,
            "cursor_before": sync.get("cursor_before"),
            "cursor_after": sync.get("cursor_after"),
            "cursor": sync.get("cursor_after"),
            "error_message": sync.get("error_message"),
            "started_at": sync.get("started_at"),
            "completed_at": sync.get("completed_at"),
            "created_at": sync["created_at"],
        }

    def syncs(self, organisation_id: str, provider: str, *, limit: int = 50) -> list[dict]:
        key = provider.strip().lower()
        rows = self.db.rows(
            "SELECT id FROM sync_runs WHERE organisation_id=? AND provider=? "
            "ORDER BY created_at DESC,id DESC LIMIT ?",
            (organisation_id, key, max(1, min(limit, 200))),
        )
        return [self._sync_summary(organisation_id, row["id"]) for row in rows]

    def apply_staged(
        self,
        organisation_id: str,
        provider: str,
        sync_run_id: str,
        decisions: Mapping[str, str],
        *,
        actor: str,
    ) -> dict:
        key = provider.strip().lower()
        sync = self.db.one(
            "SELECT * FROM sync_runs WHERE organisation_id=? AND provider=? AND id=?",
            (organisation_id, key, sync_run_id),
        )
        if not sync:
            raise KeyError("Sync run not found")
        if sync["object_type"] not in {"employee", "employees"}:
            raise ValueError("Only staged employee records can be applied")
        invalid = {value for value in decisions.values() if value not in {"apply", "reject"}}
        if invalid:
            raise ValueError("Decisions must be 'apply' or 'reject'")
        rows = self.db.rows(
            "SELECT * FROM import_staged_records WHERE organisation_id=? AND provider=? "
            "AND sync_run_id=? ORDER BY created_at,id",
            (organisation_id, key, sync_run_id),
        )
        by_id = {row["id"]: row for row in rows}
        unknown = sorted(set(decisions) - set(by_id))
        if unknown:
            raise KeyError("Staged record not found")
        outcomes: list[dict[str, Any]] = []
        conflicts_raised = 0
        for staged_id, decision in decisions.items():
            row = by_id[staged_id]
            if decision == "reject":
                outcomes.append(self._reject(organisation_id, row, actor))
                continue
            try:
                outcomes.append(self._apply_one(organisation_id, sync, row, actor))
            except (
                ValueError,
                KeyError,
                PayrollConflict,
                InvalidOperation,
                sqlite3.IntegrityError,
                UniqueViolation,
            ) as error:
                reason = str(error.args[0] if isinstance(error, KeyError) else error)
                outcomes.append(self._fail_one(organisation_id, sync, row, actor, reason))
                conflicts_raised += 1
        self._refresh_sync_state(organisation_id, sync_run_id)
        counts = {name: 0 for name in ("applied", "updated", "unchanged", "rejected", "failed")}
        for outcome in outcomes:
            counts[outcome["outcome"]] += 1
        return {
            "sync_run_id": sync_run_id,
            **counts,
            "conflicts_raised": conflicts_raised,
            "outcomes": outcomes,
            "summary": self._sync_summary(organisation_id, sync_run_id),
        }

    def _reject(self, organisation_id: str, row: dict, actor: str) -> dict:
        if row["status"] == "Applied":
            return {
                "staged_id": row["id"],
                "outcome": "failed",
                "reason": "An applied record cannot be rejected",
            }
        now = utc_now()
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE import_staged_records SET status='Rejected',review_note=NULL,updated_at=? "
                "WHERE organisation_id=? AND id=?",
                (now, organisation_id, row["id"]),
            )
            audit(
                tx,
                organisation_id,
                actor,
                "integration.staged_rejected",
                "import_staged_record",
                row["id"],
                {"sync_run_id": row["sync_run_id"]},
            )
        return {"staged_id": row["id"], "outcome": "rejected"}

    def _apply_one(self, organisation_id: str, sync: dict, row: dict, actor: str) -> dict:
        payload = json.loads(row["external_payload_json"])
        external_id = row.get("external_id")
        if not external_id:
            raise ValueError("External ID is required to apply an employee record")
        changes = {field: payload[field] for field in EMPLOYEE_FIELDS if field in payload}
        if not isinstance(changes.get("name"), str) or not changes["name"].strip():
            raise ValueError("Employee name is required")
        if "gross_salary" not in changes and changes.get("pay_basis", "monthly") != "hourly":
            raise ValueError("Gross salary is required")
        with self.db.transaction() as tx:
            mapping = tx.one(
                "SELECT * FROM external_mappings WHERE organisation_id=? AND provider=? "
                "AND object_type=? AND external_id=?",
                (organisation_id, sync["provider"], sync["object_type"], external_id),
            )
            employee_id = mapping["local_id"] if mapping else row.get("matched_local_employee_id")
            existing = None
            if employee_id:
                existing = tx.one(
                    "SELECT * FROM employees WHERE organisation_id=? AND id=?",
                    (organisation_id, employee_id),
                )
                if not existing:
                    raise ValueError("Mapped employee no longer exists")
            self._assert_name_available(tx, organisation_id, changes["name"].strip(), employee_id)
            outcome = "applied"
            if existing and self._employee_unchanged(existing, changes):
                employee = self.payroll._serialize_employee(dict(existing))
                outcome = "unchanged"
            else:
                employee = self.payroll.save_employee(
                    organisation_id,
                    employee_id=employee_id,
                    actor=actor,
                    tx=tx,
                    **changes,
                )
                outcome = "updated" if existing else "applied"
            if mapping is None:
                local_mapping = tx.one(
                    "SELECT external_id FROM external_mappings WHERE organisation_id=? AND provider=? "
                    "AND object_type=? AND local_id=?",
                    (organisation_id, sync["provider"], sync["object_type"], employee["id"]),
                )
                if local_mapping:
                    raise ValueError("Employee is already mapped to another external record")
                tx.execute(
                    "INSERT INTO external_mappings(id,organisation_id,provider,object_type,local_id,"
                    "external_id,ownership,direction,updated_at) VALUES (?,?,?,?,?,?,'external','import',?)",
                    (
                        new_id(),
                        organisation_id,
                        sync["provider"],
                        sync["object_type"],
                        employee["id"],
                        external_id,
                        utc_now(),
                    ),
                )
            tx.execute(
                "UPDATE import_staged_records SET status='Applied',matched_local_employee_id=?,"
                "review_note=NULL,updated_at=? WHERE organisation_id=? AND id=?",
                (employee["id"], utc_now(), organisation_id, row["id"]),
            )
            audit(
                tx,
                organisation_id,
                actor,
                "integration.staged_applied",
                "import_staged_record",
                row["id"],
                {
                    "sync_run_id": sync["id"],
                    "employee_id": employee["id"],
                    "outcome": outcome,
                },
            )
        return {
            "staged_id": row["id"],
            "outcome": outcome,
            "employee_id": employee["id"],
        }

    @staticmethod
    def _assert_name_available(tx, organisation_id: str, name: str, employee_id: str | None) -> None:
        existing = tx.one(
            "SELECT id FROM employees WHERE organisation_id=? AND name=?",
            (organisation_id, name),
        )
        if existing and existing["id"] != employee_id:
            raise PayrollConflict("An employee with this name already exists")

    def _employee_unchanged(self, existing: dict, changes: dict) -> bool:
        candidate = dict(existing)
        adjusted = dict(changes)
        if "pay_basis" in adjusted and "board_member" not in adjusted:
            adjusted["board_member"] = adjusted["pay_basis"] == "board_fee"
        if "board_member" in adjusted and "pay_basis" not in adjusted:
            if adjusted["board_member"] in (True, 1):
                adjusted["pay_basis"] = "board_fee"
            elif candidate.get("pay_basis") == "board_fee":
                adjusted["pay_basis"] = "monthly"
        candidate.update(adjusted)
        validated = self.payroll._employee_values(candidate)
        for field in EMPLOYEE_COMPARE_FIELDS:
            if not self._same_employee_value(field, existing.get(field), validated.get(field)):
                return False
        return True

    @staticmethod
    def _same_employee_value(field: str, left: Any, right: Any) -> bool:
        if field in DECIMAL_EMPLOYEE_FIELDS:
            if left in (None, "") or right in (None, ""):
                return left in (None, "") and right in (None, "")
            return Decimal(str(left)) == Decimal(str(right))
        if field in {"board_member", "active", "apply_tax_free_minimum"}:
            return bool(left) == bool(right)
        return left == right

    def _fail_one(
        self,
        organisation_id: str,
        sync: dict,
        row: dict,
        actor: str,
        reason: str,
    ) -> dict:
        conflict_id, now = new_id(), utc_now()
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE import_staged_records SET status='Failed',review_note=?,updated_at=? "
                "WHERE organisation_id=? AND id=?",
                (reason, now, organisation_id, row["id"]),
            )
            tx.execute(
                "INSERT INTO sync_conflicts(id,organisation_id,sync_run_id,provider,object_type,"
                "local_id,external_id,conflict_type,local_json,external_json,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    conflict_id,
                    organisation_id,
                    sync["id"],
                    sync["provider"],
                    sync["object_type"],
                    row.get("matched_local_employee_id"),
                    row.get("external_id"),
                    "employee_import_validation",
                    None,
                    canonical_json({"staged_record_id": row["id"], "reason": reason}),
                    now,
                ),
            )
            tx.execute(
                "UPDATE sync_runs SET conflict_count=conflict_count+1,status='Review Required' "
                "WHERE organisation_id=? AND id=?",
                (organisation_id, sync["id"]),
            )
            audit(
                tx,
                organisation_id,
                actor,
                "integration.staged_failed",
                "import_staged_record",
                row["id"],
                {"sync_run_id": sync["id"], "conflict_id": conflict_id},
            )
        return {"staged_id": row["id"], "outcome": "failed", "reason": reason}

    def _refresh_sync_state(self, organisation_id: str, sync_run_id: str) -> None:
        with self.db.transaction() as tx:
            counts = {
                row["status"]: int(row["record_count"])
                for row in tx.rows(
                    "SELECT status,COUNT(*) AS record_count FROM import_staged_records "
                    "WHERE organisation_id=? AND sync_run_id=? GROUP BY status",
                    (organisation_id, sync_run_id),
                )
            }
            status = (
                "Review Required"
                if counts.get("Pending", 0) or counts.get("Approved", 0) or counts.get("Failed", 0)
                else "Completed"
            )
            tx.execute(
                "UPDATE sync_runs SET status=?,write_count=? WHERE organisation_id=? AND id=?",
                (status, counts.get("Applied", 0), organisation_id, sync_run_id),
            )
