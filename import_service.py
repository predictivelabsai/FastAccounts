"""Accountant-reviewed staging and application of connector records."""
from __future__ import annotations

import json
import base64
import binascii
from datetime import date
import sqlite3
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from psycopg.errors import UniqueViolation

import connectors.registry as connector_registry
from connectors.providers import FASTHR_NO_PAY_AMOUNT
from core_utils import (
    audit,
    canonical_json,
    db_number,
    money,
    new_id,
    sha256_bytes,
    utc_now,
)
from database import Database, get_database
from documents import DocumentService
from integration_service import AccountMappingService, IntegrationService
from payroll import PayrollConflict, PayrollService
from ledger import LedgerService, PostingLine
from journal_import_repository import JournalImportRepository
from master_data_import import MasterDataImportService

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
FILE_IMPORT_PROVIDER = "file_import"
MAX_FILE_IMPORT_CHARS = 2_000_000
OBJECT_TYPES = {
    "journal": "journal",
    "employee": "employee",
    "employees": "employee",
    "contact": "contact",
    "contacts": "contact",
    "sales_invoice": "sales_invoice",
    "sales_invoices": "sales_invoice",
    "purchase_invoice": "purchase_invoice",
    "purchase_invoices": "purchase_invoice",
    "payment": "payment",
    "payments": "payment",
    "account": "account",
    "accounts": "account",
    "gl_entry": "gl_entry",
    "gl_entries": "gl_entry",
    "g_entries": "gl_entry",
}


class ImportService:
    def __init__(self, db: Database | None = None, *, integration: IntegrationService | None = None):
        self.db = db or get_database()
        self.integration = integration or IntegrationService(self.db)
        self.payroll = PayrollService(self.db)
        self.documents = DocumentService(self.db)
        self.account_mappings = AccountMappingService(self.db)
        self.APPLY_HANDLERS = {
            "employee": self._apply_employee,
            "contact": self._apply_contact,
            "purchase_invoice": self._apply_purchase_invoice,
            "sales_invoice": self._apply_sales_invoice,
            "payment": self._apply_payment,
            "account": self._apply_account,
            "gl_entry": self._apply_gl_entry,
            "journal": self._apply_journal,
        }

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
        if key == FILE_IMPORT_PROVIDER:
            resolved_credentials = dict(credentials or {})
            if "xlsx_base64" in resolved_credentials:
                encoded = resolved_credentials.pop("xlsx_base64")
                if not isinstance(encoded, str) or len(encoded) > 2_666_668:
                    raise ValueError("Journal workbook must be an XLSX file under 2 MB")
                try:
                    resolved_credentials["workbook_content"] = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error) as error:
                    raise ValueError("Journal workbook is not a valid XLSX file") from error
            csv_content = resolved_credentials.get("csv_content", "")
            if not isinstance(csv_content, str):
                raise ValueError("CSV content must be text")
            if len(csv_content) > MAX_FILE_IMPORT_CHARS:
                raise ValueError(
                    f"CSV content exceeds the {MAX_FILE_IMPORT_CHARS} character limit"
                )
            return key, resolved_credentials, dict(config or {})
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
        key, resolved_credentials, resolved_config = self._connection_material(
            organisation_id, provider, credentials, config
        )
        if key == FILE_IMPORT_PROVIDER and object_type not in {"employee", "employees", "journal"}:
            raise ValueError("File import supports employees and journals only")
        requested_type = object_type.strip().lower()
        canonical_type = OBJECT_TYPES.get(requested_type)
        if canonical_type is None:
            raise ValueError(f"Unsupported reviewed import object type: {object_type}")
        object_type = (
            requested_type
            if canonical_type == "employee" and key != FILE_IMPORT_PROVIDER
            else canonical_type
        )
        connector = connector_registry.connector_for(
            key, credentials=resolved_credentials, config=resolved_config
        )
        declared = getattr(connector, "PULL_OBJECT_TYPES", ("employee", "employees"))
        supported = {OBJECT_TYPES.get(str(item).strip().lower(), str(item).strip().lower()) for item in declared}
        if canonical_type not in supported:
            raise ValueError(f"{key} does not support reviewed import object type '{canonical_type}'")
        cursor_before = (
            None
            if key == FILE_IMPORT_PROVIDER
            else self._last_cursor(organisation_id, key, object_type)
        )
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
            result = connector.pull(object_type, cursor=cursor_before)
            if not result.ok:
                raise ValueError(result.message or f"{key} did not return {object_type} records")
            records = list(result.records)
            if any(not isinstance(record, Mapping) for record in records):
                raise ValueError(f"Connector {object_type} records must be objects")
            cursor_after = result.cursor if result.cursor is not None else cursor_before
            self._stage_records(
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
        canonical_type = OBJECT_TYPES.get(object_type, object_type)
        with self.db.transaction() as tx:
            for payload in records:
                external_id = self._external_id(payload)
                matched_id, review_note, match = self._local_match(
                    tx, organisation_id, provider, object_type, external_id, payload
                )
                warning = payload.get("import_warning")
                if not review_note and isinstance(warning, str) and warning:
                    review_note = warning
                if canonical_type == "journal":
                    review_note = self._journal_review(tx, organisation_id, payload)["warning"]
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
                        "matched_local_employee_id=?,matched_local_id=?,match_json=?,"
                        "review_note=?,updated_at=? "
                        "WHERE organisation_id=? AND id=?",
                        (
                            canonical_json(payload),
                            matched_id if canonical_type == "employee" else None,
                            matched_id,
                            canonical_json(match) if match else None,
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
                        "matched_local_id,match_json,review_note,created_at,updated_at) "
                        "VALUES (?,?,?,?,?,?,?,'Pending',?,?,?,?,?,?)",
                        (
                            staged_id,
                            organisation_id,
                            sync_id,
                            provider,
                            object_type,
                            external_id,
                            canonical_json(payload),
                            matched_id if canonical_type == "employee" else None,
                            matched_id,
                            canonical_json(match) if match else None,
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
    def _employee_match(tx, organisation_id: str, payload: Mapping[str, Any], *, match_name: bool = False) -> tuple[str | None, str | None, dict | None]:
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
            if not match_name:
                return None, None, None
            name = payload.get("name")
            if not isinstance(name, str) or not name.strip():
                return None, None, None
            matches = tx.rows(
                "SELECT id,name FROM employees WHERE organisation_id=? AND lower(trim(name))=lower(?)",
                (organisation_id, name.strip()),
            )
            if len(matches) == 1:
                return matches[0]["id"], None, {"strategy": "name", "name": name.strip()}
            if len(matches) > 1:
                return None, "Ambiguous employee match: " + ", ".join(item["name"] for item in matches), None
            return None, None, None
        matches = tx.rows(
            "SELECT id,name,email,personal_id FROM employees WHERE organisation_id=? AND ("
            + " OR ".join(clauses)
            + ") ORDER BY name,id",
            tuple(params),
        )
        if len(matches) == 1:
            strategy = "email" if email and str(matches[0].get("email", "")).strip().lower() == email.lower() else "personal_id"
            return matches[0]["id"], None, {"strategy": strategy, strategy: email if strategy == "email" else personal_id}
        if len(matches) > 1:
            names = ", ".join(item["name"] for item in matches)
            return None, f"Ambiguous employee match: {names}", None
        return None, None, None

    def _local_match(
        self, tx, organisation_id: str, provider: str, object_type: str,
        external_id: str | None, payload: Mapping[str, Any]
    ) -> tuple[str | None, str | None, dict | None]:
        canonical_type = OBJECT_TYPES.get(object_type, object_type)
        if external_id:
            mapping = tx.one(
                "SELECT local_id FROM external_mappings WHERE organisation_id=? AND provider=? "
                "AND object_type=? AND external_id=? AND direction IN ('import','bidirectional')",
                (organisation_id, provider, object_type, external_id),
            )
            if mapping:
                return mapping["local_id"], None, {
                    "strategy": "external_mapping", "external_id": external_id
                }
        if canonical_type == "employee":
            return self._employee_match(tx, organisation_id, payload, match_name=provider == "smartaccounts")
        if canonical_type == "contact":
            registration = self._text(payload, "registration_no", "registry_code", "registration_code")
            email = self._text(payload, "email")
            if registration:
                rows = tx.rows(
                    "SELECT id,name FROM contacts WHERE organisation_id=? AND trim(registration_no)=?",
                    (organisation_id, registration),
                )
                if len(rows) == 1:
                    return rows[0]["id"], None, {"strategy": "registry_code", "registry_code": registration}
                if len(rows) > 1:
                    return None, "Ambiguous contact registry-code match", None
            if email:
                rows = tx.rows(
                    "SELECT id,name FROM contacts WHERE organisation_id=? AND lower(trim(email))=lower(?)",
                    (organisation_id, email),
                )
                if len(rows) == 1:
                    return rows[0]["id"], None, {"strategy": "email", "email": email}
                if len(rows) > 1:
                    return None, "Ambiguous contact email match", None
        if canonical_type in {"purchase_invoice", "sales_invoice"}:
            sales = canonical_type == "sales_invoice"
            table = "invoices" if sales else "bills"
            number_col = "number" if sales else "supplier_number"
            party_key = "buyer_name" if sales else "supplier_name"
            party_name = self._text(payload, party_key, "contact_name", "customer_name" if sales else "vendor_name")
            number = self._text(payload, "number", "external_number", "invoice_number", "supplier_number")
            if party_name and number:
                rows = tx.rows(
                    f"SELECT d.id FROM {table} d JOIN contacts c ON c.id=d.contact_id "
                    f"WHERE d.organisation_id=? AND lower(trim(c.name))=lower(?) AND d.{number_col}=?",
                    (organisation_id, party_name, number),
                )
                if len(rows) == 1:
                    return rows[0]["id"], None, {
                        "strategy": "natural_key", "party_name": party_name, "number": number
                    }
                if len(rows) > 1:
                    return None, f"Ambiguous {canonical_type.replace('_', ' ')} match", None
        return None, None, None

    @staticmethod
    def _text(payload: Mapping[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if value not in (None, ""):
                return str(value).strip()
        return ""

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
            "SELECT s.*,e.name AS matched_local_employee_name,"
            "CASE WHEN s.object_type='contact' THEN c.name "
            "WHEN s.object_type='purchase_invoice' THEN bc.name||' / '||b.supplier_number "
            "WHEN s.object_type='sales_invoice' THEN ic.name||' / '||COALESCE(i.number,'Draft') "
            "WHEN s.object_type IN ('employee','employees') THEN e.name END AS matched_local_name "
            "FROM import_staged_records s "
            "LEFT JOIN employees e ON e.organisation_id=s.organisation_id "
            "AND e.id=s.matched_local_employee_id "
            "LEFT JOIN contacts c ON c.organisation_id=s.organisation_id AND c.id=s.matched_local_id "
            "LEFT JOIN bills b ON b.organisation_id=s.organisation_id AND b.id=s.matched_local_id "
            "LEFT JOIN contacts bc ON bc.id=b.contact_id "
            "LEFT JOIN invoices i ON i.organisation_id=s.organisation_id AND i.id=s.matched_local_id "
            "LEFT JOIN contacts ic ON ic.id=i.contact_id WHERE s.organisation_id=?"
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
            record["match"] = json.loads(record["match_json"]) if record.get("match_json") else None
            if record["object_type"] == "journal":
                record["journal_review"] = self._journal_review(self.db, organisation_id, record["external_payload"])
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
            "reviewed_at": sync.get("reviewed_at"),
            "reviewed_by": sync.get("reviewed_by"),
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
        posting_date: str | None = None,
    ) -> dict:
        key = provider.strip().lower()
        sync = self.db.one(
            "SELECT * FROM sync_runs WHERE organisation_id=? AND provider=? AND id=?",
            (organisation_id, key, sync_run_id),
        )
        if not sync:
            raise KeyError("Sync run not found")
        object_type = OBJECT_TYPES.get(sync["object_type"], sync["object_type"])
        handler = self.APPLY_HANDLERS.get(object_type)
        if handler is None:
            raise ValueError(f"Staged {sync['object_type']} records cannot be applied")
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
                if object_type == "journal":
                    outcomes.append(handler(organisation_id, sync, row, actor, posting_date))
                else:
                    outcomes.append(handler(organisation_id, sync, row, actor))
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
        self._refresh_sync_state(organisation_id, sync_run_id, actor=actor)
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

    def _journal_review(self, tx, organisation_id: str, payload: dict) -> dict:
        repository = JournalImportRepository(tx, organisation_id)
        lines = []
        debit = credit = Decimal("0")
        warning = payload.get("import_warning")
        for source in payload.get("lines", []):
            line = dict(source)
            account = repository.resolve_account(str(line.get("account_code") or ""))
            line["account_id"] = account["id"] if account else None
            line["local_account_code"] = account["code"] if account else None
            line["warning"] = None if account else "Journal account is unmapped"
            if not account:
                warning = warning or "Journal account is unmapped"
            try:
                dr, cr = money(line.get("debit") or "0"), money(line.get("credit") or "0")
                if (not dr.is_finite() or not cr.is_finite() or dr < 0 or cr < 0 or (dr > 0 and cr > 0)
                        or dr != Decimal(str(line.get("debit") or "0"))
                        or cr != Decimal(str(line.get("credit") or "0"))):
                    raise ValueError("Invalid journal amounts")
                debit += dr
                credit += cr
            except (ValueError, InvalidOperation):
                warning = "Journal line contains an invalid amount, date or formula"
            lines.append(line)
        balanced = debit == credit
        if not balanced:
            warning = "Journal block is unbalanced"
        elif debit <= 0 or not lines:
            warning = warning or "Journal block must contain a positive balanced posting"
        return {"lines": lines, "debit_total": str(debit), "credit_total": str(credit),
                "balanced": balanced, "warning": warning, "valid": not warning}

    def _apply_journal(self, organisation_id, sync, row, actor, posting_date=None):
        payload = json.loads(row["external_payload_json"])
        with self.db.transaction() as tx:
            repository = JournalImportRepository(tx, organisation_id)
            repository.lock()
            current = repository.staged(row["id"])
            if current and current["status"] == "Rejected":
                return {"staged_id": row["id"], "outcome": "failed",
                        "reason": "Only pending or failed journal proposals can be applied"}
            if not current or current["status"] not in {"Pending", "Failed", "Applied"}:
                raise ValueError("Only pending or failed journal proposals can be applied")
            existing = repository.posted(row["external_id"])
            if existing:
                return self._mark_applied(tx, organisation_id, sync, row, actor, existing["id"], "unchanged")
            if current["status"] == "Applied":
                raise ValueError("Only pending or failed journal proposals can be applied")
            review = self._journal_review(tx, organisation_id, payload)
            if not review["valid"]:
                raise ValueError(review["warning"])
            day = payload.get("date") or posting_date
            if not day:
                raise ValueError("Set a posting date before applying the journal")
            day = date.fromisoformat(day).isoformat()
            lines = [PostingLine(account_id=line["account_id"],
                                 debit=money(line.get("debit") or "0"), credit=money(line.get("credit") or "0"),
                                 memo=line.get("description") or payload["name"])
                     for line in review["lines"] if money(line.get("debit") or "0") or money(line.get("credit") or "0")]
            batch = LedgerService(self.db).post(
                organisation_id=organisation_id, voucher_type="file_journal", voucher_id=row["external_id"],
                voucher_code=payload["name"], posting_date=day, lines=lines, actor=actor,
                currency=repository.currency(), tx=tx)
            self._upsert_external_mapping(tx, organisation_id, sync["provider"], "journal", batch["id"], row["external_id"], payload)
            return self._mark_applied(tx, organisation_id, sync, row, actor, batch["id"])

    def _reject(self, organisation_id: str, row: dict, actor: str) -> dict:
        if row["status"] == "Applied":
            return {
                "staged_id": row["id"],
                "outcome": "failed",
                "reason": "An applied record cannot be rejected",
            }
        now = utc_now()
        with self.db.transaction() as tx:
            if row["object_type"] == "journal":
                repository = JournalImportRepository(tx, organisation_id)
                repository.lock()
                current = repository.staged(row["id"])
                if current and current["status"] == "Applied":
                    return {"staged_id": row["id"], "outcome": "failed",
                            "reason": "An applied record cannot be rejected"}
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

    def _apply_employee(self, organisation_id: str, sync: dict, row: dict, actor: str) -> dict:
        payload = json.loads(row["external_payload_json"])
        external_id = row.get("external_id")
        if not external_id:
            raise ValueError("External ID is required to apply an employee record")
        changes = {field: payload[field] for field in EMPLOYEE_FIELDS if field in payload}
        if not isinstance(changes.get("name"), str) or not changes["name"].strip():
            raise ValueError("Employee name is required")
        warning = payload.get("import_warning")
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
            # A connector warning (e.g. FastHR without any pay amount) skips the record
            # instead of guessing; an already-linked employee keeps its local pay terms.
            if isinstance(warning, str) and warning and (
                not existing or warning != FASTHR_NO_PAY_AMOUNT
            ):
                raise ValueError(warning)
            if (
                not existing
                and "gross_salary" not in changes
                and changes.get("pay_basis", "monthly") != "hourly"
            ):
                raise ValueError("Gross salary is required")
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
                "matched_local_id=?,review_note=NULL,updated_at=? WHERE organisation_id=? AND id=?",
                (employee["id"], employee["id"], utc_now(), organisation_id, row["id"]),
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

    def _mapping_values(self, payload: Mapping[str, Any]) -> tuple[str | None, str]:
        payload_hash = self._text(payload, "payload_hash", "hash")
        external_version = self._text(payload, "external_version", "version") or payload_hash or None
        last_hash = payload_hash or sha256_bytes(canonical_json(payload).encode())
        return external_version, last_hash

    def _upsert_external_mapping(
        self, tx, organisation_id: str, provider: str, object_type: str,
        local_id: str, external_id: str, payload: Mapping[str, Any]
    ) -> None:
        external_version, last_hash = self._mapping_values(payload)
        existing = tx.one(
            "SELECT id,local_id FROM external_mappings WHERE organisation_id=? AND provider=? "
            "AND object_type=? AND external_id=?",
            (organisation_id, provider, object_type, external_id),
        )
        if existing:
            if existing["local_id"] != local_id:
                raise ValueError("External record is already mapped to another local record")
            tx.execute(
                "UPDATE external_mappings SET external_version=?,ownership='external',"
                "direction='import',last_hash=?,updated_at=? WHERE id=?",
                (external_version, last_hash, utc_now(), existing["id"]),
            )
            return
        local = tx.one(
            "SELECT id FROM external_mappings WHERE organisation_id=? AND provider=? "
            "AND object_type=? AND local_id=?",
            (organisation_id, provider, object_type, local_id),
        )
        if local:
            raise ValueError("Local record is already mapped to another external record")
        tx.execute(
            "INSERT INTO external_mappings(id,organisation_id,provider,object_type,local_id,"
            "external_id,external_version,ownership,direction,last_hash,updated_at) "
            "VALUES (?,?,?,?,?,?,?,'external','import',?,?)",
            (new_id(), organisation_id, provider, object_type, local_id, external_id,
             external_version, last_hash, utc_now()),
        )

    def _mark_applied(
        self, tx, organisation_id: str, sync: dict, row: dict, actor: str,
        local_id: str | None, outcome: str = "applied"
    ) -> dict:
        tx.execute(
            "UPDATE import_staged_records SET status='Applied',matched_local_id=?,"
            "review_note=NULL,updated_at=? WHERE organisation_id=? AND id=?",
            (local_id, utc_now(), organisation_id, row["id"]),
        )
        audit(tx, organisation_id, actor, "integration.staged_applied",
              "import_staged_record", row["id"],
              {"sync_run_id": sync["id"], "local_id": local_id, "outcome": outcome})
        result = {"staged_id": row["id"], "outcome": outcome}
        if local_id:
            result["local_id"] = local_id
        return result

    @staticmethod
    def _contact_type(payload: Mapping[str, Any], required: str | None = None) -> str:
        supplied = str(payload.get("contact_type") or "").strip().lower()
        if supplied in {"customer", "supplier", "both"}:
            value = supplied
        else:
            client = bool(payload.get("is_client", payload.get("is_customer", False)))
            supplier = bool(payload.get("is_supplier", payload.get("is_vendor", False)))
            if not client and not supplier and required:
                value = required
            else:
                value = "both" if client == supplier else "customer" if client else "supplier"
        if required and value != required:
            value = "both"
        return value

    def _contact_payload(self, payload: Mapping[str, Any], role: str | None = None) -> dict[str, Any]:
        nested: Mapping[str, Any] = payload
        for key in (("supplier", "vendor") if role == "supplier" else ("buyer", "customer", "client") if role == "customer" else ("contact",)):
            candidate = payload.get(key)
            if isinstance(candidate, Mapping):
                nested = candidate
                break
        name_keys = ("name", "supplier_name", "vendor_name") if role == "supplier" else ("name", "buyer_name", "customer_name", "client_name")
        return {
            "name": self._text(nested, *name_keys) or self._text(payload, *name_keys),
            "registration_no": self._text(nested, "registration_no", "registry_code", "registration_code"),
            "vat_no": self._text(nested, "vat_no", "vat_number"),
            "email": self._text(nested, "email"),
            "address": self._text(nested, "address"),
            "country_code": self._text(nested, "country_code", "country"),
            "contact_type": self._contact_type(nested, role),
            "external_id": self._text(nested, "external_id", "id") or self._text(payload, f"{role}_external_id" if role else "contact_external_id"),
        }

    def _find_or_create_contact(
        self, tx, organisation_id: str, provider: str, payload: Mapping[str, Any],
        actor: str, role: str | None = None, matched_id: str | None = None
    ) -> tuple[dict, bool]:
        values = self._contact_payload(payload, role)
        contact = None
        if matched_id and role is None:
            contact = tx.one(
                "SELECT * FROM contacts WHERE organisation_id=? AND id=?",
                (organisation_id, matched_id),
            )
        if not contact and values["external_id"]:
            mapping = tx.one(
                "SELECT local_id FROM external_mappings WHERE organisation_id=? AND provider=? "
                "AND object_type='contact' AND external_id=? AND direction IN ('import','bidirectional')",
                (organisation_id, provider, values["external_id"]),
            )
            if mapping:
                contact = tx.one(
                    "SELECT * FROM contacts WHERE organisation_id=? AND id=?",
                    (organisation_id, mapping["local_id"]),
                )
        if not contact and values["registration_no"]:
            contact = tx.one(
                "SELECT * FROM contacts WHERE organisation_id=? AND registration_no=?",
                (organisation_id, values["registration_no"]),
            )
        if not contact and values["email"]:
            contact = tx.one(
                "SELECT * FROM contacts WHERE organisation_id=? AND lower(trim(email))=lower(?)",
                (organisation_id, values["email"]),
            )
        if not contact and values["name"]:
            contact = tx.one(
                "SELECT * FROM contacts WHERE organisation_id=? AND lower(trim(name))=lower(?)",
                (organisation_id, values["name"]),
            )
        created = False
        if not contact:
            if not values["name"]:
                raise ValueError("Contact name is required")
            country = values["country_code"] or tx.scalar(
                "SELECT country_code FROM organisations WHERE id=?", (organisation_id,)
            )
            contact = self.documents.create_contact(
                organisation_id, name=values["name"], country_code=str(country),
                contact_type=values["contact_type"], email=values["email"],
                vat_no=values["vat_no"], registration_no=values["registration_no"],
                address=values["address"], tx=tx,
            )
            created = True
        elif role and contact["contact_type"] not in {role, "both"}:
            tx.execute(
                "UPDATE contacts SET contact_type='both',updated_at=? "
                "WHERE organisation_id=? AND id=?",
                (utc_now(), organisation_id, contact["id"]),
            )
            contact["contact_type"] = "both"
        if values["external_id"]:
            self._upsert_external_mapping(
                tx, organisation_id, provider, "contact", contact["id"],
                values["external_id"], payload
            )
        return contact, created

    def _apply_contact(self, organisation_id: str, sync: dict, row: dict, actor: str) -> dict:
        payload = json.loads(row["external_payload_json"])
        external_id = row.get("external_id")
        if not external_id:
            raise ValueError("External ID is required to apply a contact record")
        with self.db.transaction() as tx:
            contact, created = self._find_or_create_contact(
                tx, organisation_id, sync["provider"], payload, actor,
                matched_id=row.get("matched_local_id")
            )
            self._upsert_external_mapping(
                tx, organisation_id, sync["provider"], "contact", contact["id"],
                external_id, payload
            )
            return self._mark_applied(
                tx, organisation_id, sync, row, actor, contact["id"],
                "applied" if created else "unchanged"
            )

    def _document_lines(self, tx, organisation_id: str, provider: str, payload: Mapping[str, Any]) -> list[dict]:
        source = payload.get("lines") or payload.get("items")
        if not isinstance(source, list) or not source:
            raise ValueError("At least one document line is required")
        result: list[dict] = []
        for raw in source:
            if not isinstance(raw, Mapping):
                raise ValueError("Document lines must be objects")
            account_id = self._text(raw, "account_id")
            if not account_id:
                local_code = self._text(raw, "local_account_code", "account_code")
                external_code = self._text(raw, "external_account_code")
                if external_code:
                    mapping = tx.one(
                        "SELECT local_account_code FROM account_mappings WHERE organisation_id=? "
                        "AND provider=? AND external_account_code=? AND status<>'Disabled' "
                        "ORDER BY CASE status WHEN 'Confirmed' THEN 0 ELSE 1 END LIMIT 1",
                        (organisation_id, provider, external_code),
                    )
                    local_code = mapping["local_account_code"] if mapping else ""
                account = tx.one(
                    "SELECT id FROM accounts WHERE organisation_id=? AND code=? AND active=1",
                    (organisation_id, local_code),
                ) if local_code else None
                account_id = account["id"] if account else ""
            if not account_id:
                raise ValueError("A mapped local account is required for every document line")
            tax_code_id = self._text(raw, "tax_code_id") or None
            if not tax_code_id:
                tax_code = self._text(raw, "tax_code")
                if tax_code:
                    found = tx.one(
                        "SELECT id FROM tax_codes WHERE organisation_id=? AND code=? AND active=1 "
                        "ORDER BY valid_from DESC LIMIT 1", (organisation_id, tax_code)
                    )
                    tax_code_id = found["id"] if found else None
            quantity = Decimal(self._text(raw, "quantity", "qty") or "1")
            unit_price_text = self._text(raw, "unit_price", "price", "net_unit_price")
            if not unit_price_text:
                total_text = self._text(raw, "net_amount", "line_total", "total")
                if not total_text:
                    raise ValueError("A unit price is required for every document line")
                unit_price_text = str(Decimal(total_text) / quantity)
            result.append({
                "description": self._text(raw, "description", "name") or "Imported line",
                "quantity": quantity,
                "unit_price": Decimal(unit_price_text),
                "account_id": account_id,
                "tax_code_id": tax_code_id,
            })
        return result

    def _apply_purchase_invoice(self, organisation_id: str, sync: dict, row: dict, actor: str) -> dict:
        payload = json.loads(row["external_payload_json"])
        external_id = row.get("external_id")
        if not external_id:
            raise ValueError("External ID is required to apply a purchase invoice")
        with self.db.transaction() as tx:
            existing_mapping = tx.one(
                "SELECT local_id FROM external_mappings WHERE organisation_id=? AND provider=? "
                "AND object_type='purchase_invoice' AND external_id=?",
                (organisation_id, sync["provider"], external_id),
            )
            existing_id = existing_mapping["local_id"] if existing_mapping else row.get("matched_local_id")
            if existing_id:
                existing = tx.one(
                    "SELECT id FROM bills WHERE organisation_id=? AND id=?",
                    (organisation_id, existing_id),
                )
                if existing:
                    self._upsert_external_mapping(
                        tx, organisation_id, sync["provider"], "purchase_invoice",
                        existing["id"], external_id, payload
                    )
                    return self._mark_applied(
                        tx, organisation_id, sync, row, actor, existing["id"], "unchanged"
                    )
            contact, _ = self._find_or_create_contact(
                tx, organisation_id, sync["provider"], payload, actor, role="supplier"
            )
            supplier_number = self._text(payload, "external_number", "supplier_number", "invoice_number", "number")
            bill_date = self._text(payload, "bill_date", "invoice_date", "date")
            due_date = self._text(payload, "due_date") or bill_date
            bill = self.documents.create_bill(
                organisation_id, contact_id=contact["id"], supplier_number=supplier_number,
                bill_date=bill_date, due_date=due_date,
                lines=self._document_lines(tx, organisation_id, sync["provider"], payload),
                actor=actor, currency=self._text(payload, "currency") or None,
                reference=self._text(payload, "reference"), notes=self._text(payload, "notes"), tx=tx,
            )
            expected = self._text(payload, "total", "gross_total", "amount_total")
            if expected and money(expected) != money(bill["total"]):
                raise ValueError("Purchase invoice line totals do not match the payload total")
            self._upsert_external_mapping(
                tx, organisation_id, sync["provider"], "purchase_invoice", bill["id"], external_id, payload
            )
            return self._mark_applied(tx, organisation_id, sync, row, actor, bill["id"])

    def _apply_sales_invoice(self, organisation_id: str, sync: dict, row: dict, actor: str) -> dict:
        payload = json.loads(row["external_payload_json"])
        external_id = row.get("external_id")
        if not external_id:
            raise ValueError("External ID is required to apply a sales invoice")
        with self.db.transaction() as tx:
            existing_mapping = tx.one(
                "SELECT local_id FROM external_mappings WHERE organisation_id=? AND provider=? "
                "AND object_type='sales_invoice' AND external_id=?",
                (organisation_id, sync["provider"], external_id),
            )
            existing_id = existing_mapping["local_id"] if existing_mapping else row.get("matched_local_id")
            if existing_id:
                existing = tx.one(
                    "SELECT id FROM invoices WHERE organisation_id=? AND id=?",
                    (organisation_id, existing_id),
                )
                if existing:
                    self._upsert_external_mapping(
                        tx, organisation_id, sync["provider"], "sales_invoice",
                        existing["id"], external_id, payload
                    )
                    return self._mark_applied(
                        tx, organisation_id, sync, row, actor, existing["id"], "unchanged"
                    )
            contact, _ = self._find_or_create_contact(
                tx, organisation_id, sync["provider"], payload, actor, role="customer"
            )
            issue_date = self._text(payload, "issue_date", "invoice_date", "date")
            invoice = self.documents.create_invoice(
                organisation_id, contact_id=contact["id"], issue_date=issue_date,
                due_date=self._text(payload, "due_date") or None,
                lines=self._document_lines(tx, organisation_id, sync["provider"], payload),
                actor=actor, currency=self._text(payload, "currency") or None,
                amount_type=self._text(payload, "amount_type") or "exclusive",
                reference=self._text(payload, "external_number", "invoice_number", "number", "reference"),
                notes=self._text(payload, "notes"), tx=tx,
            )
            self._upsert_external_mapping(
                tx, organisation_id, sync["provider"], "sales_invoice", invoice["id"], external_id, payload
            )
            return self._mark_applied(tx, organisation_id, sync, row, actor, invoice["id"])

    def _apply_payment(self, organisation_id: str, sync: dict, row: dict, actor: str) -> dict:
        payload = json.loads(row["external_payload_json"])
        external_id = row.get("external_id")
        if not external_id:
            raise ValueError("External ID is required to apply a payment")
        document_external_id = self._text(
            payload, "document_external_id", "invoice_external_id", "bill_external_id"
        )
        document_type = self._text(payload, "document_type").lower()
        payment_type = self._text(payload, "payment_type").lower()
        if not payment_type:
            payment_type = "supplier_payment" if document_type in {"bill", "purchase_invoice"} or payload.get("bill_external_id") else "customer_receipt"
        mapping_type = "purchase_invoice" if payment_type == "supplier_payment" else "sales_invoice"
        with self.db.transaction() as tx:
            payment_mapping = tx.one(
                "SELECT local_id FROM external_mappings WHERE organisation_id=? AND provider=? "
                "AND object_type='payment' AND external_id=?",
                (organisation_id, sync["provider"], external_id),
            )
            if payment_mapping and tx.one(
                "SELECT id FROM payments WHERE organisation_id=? AND id=?",
                (organisation_id, payment_mapping["local_id"]),
            ):
                return self._mark_applied(
                    tx, organisation_id, sync, row, actor, payment_mapping["local_id"], "unchanged"
                )
            mapping = tx.one(
                "SELECT local_id FROM external_mappings WHERE organisation_id=? AND provider=? "
                "AND object_type=? AND external_id=? AND direction IN ('import','bidirectional')",
                (organisation_id, sync["provider"], mapping_type, document_external_id),
            ) if document_external_id else None
            if not mapping:
                raise ValueError("no local document linked for this payment")
            table = "bills" if mapping_type == "purchase_invoice" else "invoices"
            document = tx.one(
                f"SELECT * FROM {table} WHERE organisation_id=? AND id=?",
                (organisation_id, mapping["local_id"]),
            )
            if not document:
                raise ValueError("no local document linked for this payment")
            amount = self._text(payload, "amount", "total")
            payment = self.documents.record_payment(
                organisation_id, payment_type=payment_type,
                bank_account_id=self._text(payload, "bank_account_id"),
                payment_date=self._text(payload, "payment_date", "date"), amount=amount,
                actor=actor, contact_id=document["contact_id"],
                reference=self._text(payload, "reference"),
                allocations=[{"document_type": "bill" if mapping_type == "purchase_invoice" else "invoice",
                              "document_id": document["id"], "amount": amount}], tx=tx,
            )
            self._upsert_external_mapping(
                tx, organisation_id, sync["provider"], "payment", payment["id"], external_id, payload
            )
            return self._mark_applied(tx, organisation_id, sync, row, actor, payment["id"])

    def _apply_account(self, organisation_id: str, sync: dict, row: dict, actor: str) -> dict:
        payload = json.loads(row["external_payload_json"])
        external_code = self._text(payload, "external_account_code", "code")
        external_id = row.get("external_id") or external_code
        local_code = self._text(payload, "local_account_code") or external_code
        with self.db.transaction() as tx:
            mapping = self.account_mappings.suggest(
                tx, organisation_id, sync["provider"], external_account_code=external_code,
                external_account_name=self._text(payload, "external_account_name", "name"),
                local_account_code=local_code,
            )
            audit(tx, organisation_id, actor, "integration.account_mapping_suggested",
                  "account_mapping", mapping["id"], {"provider": sync["provider"]})
            self._upsert_external_mapping(
                tx, organisation_id, sync["provider"], "account", mapping["id"],
                external_id, payload
            )
            return self._mark_applied(tx, organisation_id, sync, row, actor, mapping["id"])

    def _apply_gl_entry(self, organisation_id: str, sync: dict, row: dict, actor: str) -> dict:
        payload = json.loads(row["external_payload_json"])
        external_id = row.get("external_id")
        if not external_id:
            raise ValueError("External ID is required to apply a GL entry")
        external_code = self._text(payload, "external_account_code", "account_code")
        with self.db.transaction() as tx:
            mapping = tx.one(
                "SELECT local_account_code FROM account_mappings WHERE organisation_id=? "
                "AND provider=? AND external_account_code=? "
                "ORDER BY CASE status WHEN 'Confirmed' THEN 0 WHEN 'Suggested' THEN 1 ELSE 2 END,id LIMIT 1",
                (organisation_id, sync["provider"], external_code),
            )
            tx.execute(
                "INSERT INTO external_gl_entries(id,organisation_id,provider,external_id,"
                "external_batch_ref,entry_date,external_account_code,local_account_code,"
                "description,document,debit,credit,dims_json,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(organisation_id,provider,external_id) DO NOTHING",
                (new_id(), organisation_id, sync["provider"], external_id,
                 self._text(payload, "external_batch_ref", "batch_ref") or external_id,
                 self._text(payload, "entry_date", "date"), external_code,
                 mapping["local_account_code"] if mapping else None,
                 self._text(payload, "description") or None,
                 self._text(payload, "document", "document_number") or None,
                 db_number(money(payload.get("debit", 0))),
                 db_number(money(payload.get("credit", 0))),
                 canonical_json(payload.get("dimensions", payload.get("dims", {}))), utc_now()),
            )
            stored = tx.one(
                "SELECT id FROM external_gl_entries WHERE organisation_id=? AND provider=? AND external_id=?",
                (organisation_id, sync["provider"], external_id),
            )
            self._upsert_external_mapping(
                tx, organisation_id, sync["provider"], "gl_entry", stored["id"],
                external_id, payload
            )
            return self._mark_applied(tx, organisation_id, sync, row, actor, stored["id"])

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
                    row.get("matched_local_id") or row.get("matched_local_employee_id"),
                    row.get("external_id"),
                    f"{OBJECT_TYPES.get(sync['object_type'], sync['object_type'])}_import_validation",
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

    def _refresh_sync_state(self, organisation_id: str, sync_run_id: str, *, actor: str) -> None:
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
                "UPDATE sync_runs SET status=?,write_count=?,reviewed_at=?,reviewed_by=? "
                "WHERE organisation_id=? AND id=?",
                (status, counts.get("Applied", 0), utc_now(), actor, organisation_id, sync_run_id),
            )
