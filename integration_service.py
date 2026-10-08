"""Secure connection state, sync ownership, conflicts, outbox, and webhooks."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

from cryptography.fernet import Fernet, InvalidToken

from connectors.base import ConnectorResult
from connectors.registry import PROVIDERS, connector_for, registration_for
from core_utils import audit, canonical_json, new_id, sha256_bytes, utc_now
from database import Database, get_database


class CredentialVault:
    def __init__(self, key: str | None = None, version: int | None = None):
        raw = (key if key is not None else os.getenv("FASTACCOUNTS_ENCRYPTION_KEY", "")).strip()
        if not raw:
            raise RuntimeError("FASTACCOUNTS_ENCRYPTION_KEY is required to store integration credentials")
        try:
            self.fernet = Fernet(raw.encode())
        except (ValueError, TypeError) as error:
            raise ValueError("FASTACCOUNTS_ENCRYPTION_KEY must be a valid Fernet key") from error
        self.version = version or int(os.getenv("FASTACCOUNTS_ENCRYPTION_KEY_VERSION", "1"))

    def encrypt(self, credentials: dict) -> str:
        return self.fernet.encrypt(canonical_json(credentials).encode()).decode()

    def decrypt(self, token: str) -> dict:
        try:
            return json.loads(self.fernet.decrypt(token.encode()).decode())
        except (InvalidToken, ValueError, json.JSONDecodeError) as error:
            raise ValueError("Integration credentials could not be decrypted") from error


class IntegrationService:
    def __init__(self, db: Database | None = None, vault: CredentialVault | None = None):
        self.db = db or get_database()
        self._vault = vault

    @property
    def vault(self) -> CredentialVault:
        if self._vault is None:
            self._vault = CredentialVault()
        return self._vault

    def configure(self, organisation_id: str, provider: str, *, credentials: dict,
                  config: dict, actor: str, external_tenant_id: str = "") -> dict:
        key = provider.strip().lower()
        try:
            registration_for(key)
        except KeyError as error:
            raise ValueError("Unknown integration provider") from error
        connection_id, now = new_id(), utc_now()
        encrypted = self.vault.encrypt(credentials)
        with self.db.transaction() as tx:
            existing = tx.one(
                "SELECT id FROM integration_connections WHERE organisation_id=? AND provider=?",
                (organisation_id, key),
            )
            if existing:
                connection_id = existing["id"]
                tx.execute(
                    "UPDATE integration_connections SET status='Configured',external_tenant_id=?,encrypted_credentials=?,encryption_key_version=?,config_json=?,updated_at=? WHERE id=?",
                    (external_tenant_id or None, encrypted, self.vault.version,
                     canonical_json(config), now, connection_id),
                )
            else:
                tx.execute(
                    "INSERT INTO integration_connections(id,organisation_id,provider,status,external_tenant_id,encrypted_credentials,encryption_key_version,config_json,created_at,updated_at) "
                    "VALUES (?,?,?,'Configured',?,?,?,?,?,?)",
                    (connection_id, organisation_id, key, external_tenant_id or None,
                     encrypted, self.vault.version, canonical_json(config), now, now),
                )
            audit(tx, organisation_id, actor, "integration.configured", "integration_connection", connection_id,
                  {"provider": key, "credential_fields": sorted(credentials), "config": config})
        return self.connection(connection_id, include_credentials=False)

    def connection(self, connection_id: str, *, include_credentials: bool = False) -> dict:
        row = self.db.one("SELECT * FROM integration_connections WHERE id=?", (connection_id,))
        if not row:
            raise KeyError("Integration connection not found")
        row["config"] = json.loads(row.pop("config_json"))
        encrypted = row.pop("encrypted_credentials", None)
        if include_credentials:
            row["credentials"] = self.vault.decrypt(encrypted) if encrypted else {}
        return row

    @staticmethod
    def public_connection(connection: dict) -> dict:
        """Return the API-safe connection fields only."""
        config = connection.get("config")
        if config is None:
            config = json.loads(connection.get("config_json", "{}"))
        return {
            "id": connection["id"],
            "provider": connection["provider"],
            "status": connection["status"],
            "external_tenant_id": connection.get("external_tenant_id"),
            "config": config,
            "updated_at": connection["updated_at"],
            "registry_status": registration_for(connection["provider"]).status,
        }

    def connections(self, organisation_id: str) -> list[dict]:
        rows = self.db.rows(
            "SELECT id,provider,status,external_tenant_id,config_json,updated_at "
            "FROM integration_connections WHERE organisation_id=? ORDER BY provider",
            (organisation_id,),
        )
        return [self.public_connection(row) for row in rows]

    def connection_for_provider(self, organisation_id: str, provider: str) -> dict:
        key = provider.strip().lower()
        try:
            registration_for(key)
        except KeyError as error:
            raise ValueError("Unknown integration provider") from error
        row = self.db.one(
            "SELECT * FROM integration_connections WHERE organisation_id=? AND provider=?",
            (organisation_id, key),
        )
        if not row:
            raise KeyError("Integration connection not found")
        row["config"] = json.loads(row.pop("config_json"))
        row.pop("encrypted_credentials", None)
        return row

    def test_connection(self, organisation_id: str, provider: str, *, credentials: dict,
                        config: dict, actor: str) -> ConnectorResult:
        key = provider.strip().lower()
        try:
            connector = connector_for(key, credentials=credentials, config=config)
        except KeyError as error:
            raise ValueError("Unknown integration provider") from error
        result = connector.check()
        connection = self.db.one(
            "SELECT id FROM integration_connections WHERE organisation_id=? AND provider=?",
            (organisation_id, key),
        )
        if connection:
            status = "Connected" if result.ok and result.live else "Error"
            self.set_status(connection["id"], status, actor=actor, message=result.message)
        return result

    def disconnect(self, organisation_id: str, provider: str, *, actor: str) -> dict:
        connection = self.connection_for_provider(organisation_id, provider)
        updated = self.set_status(
            connection["id"], "Disconnected", actor=actor,
            message="Connection disconnected by an authorised organisation member.",
        )
        return self.public_connection(updated)

    def set_status(self, connection_id: str, status: str, *, actor: str, message: str = "") -> dict:
        allowed = {"Disconnected", "Configured", "Connected", "Error", "Reauth Required"}
        if status not in allowed:
            raise ValueError("Invalid connection status")
        with self.db.transaction() as tx:
            row = tx.one("SELECT * FROM integration_connections WHERE id=?", (connection_id,))
            if not row:
                raise KeyError("Integration connection not found")
            tx.execute("UPDATE integration_connections SET status=?,updated_at=? WHERE id=?",
                       (status, utc_now(), connection_id))
            audit(tx, row["organisation_id"], actor, "integration.status_changed", "integration_connection", connection_id,
                  {"provider": row["provider"], "status": status, "message": message})
        return self.connection(connection_id)

    def map_record(self, organisation_id: str, *, provider: str, object_type: str,
                   local_id: str, external_id: str, ownership: str, direction: str,
                   external_version: str = "") -> dict:
        if ownership not in {"fastaccounts", "external", "manual"}:
            raise ValueError("Invalid record ownership")
        if direction not in {"import", "export", "bidirectional"}:
            raise ValueError("Invalid sync direction")
        mapping_id, now = new_id(), utc_now()
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO external_mappings(id,organisation_id,provider,object_type,local_id,external_id,external_version,ownership,direction,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (mapping_id, organisation_id, provider, object_type, local_id, external_id,
                 external_version or None, ownership, direction, now),
            )
        return self.db.one("SELECT * FROM external_mappings WHERE id=?", (mapping_id,)) or {}

    def start_sync(self, organisation_id: str, *, provider: str, direction: str,
                   object_type: str, cursor: str = "") -> dict:
        sync_id, now = new_id(), utc_now()
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO sync_runs(id,organisation_id,provider,direction,object_type,status,cursor_before,started_at,created_at) "
                "VALUES (?,?,?,?,?,'Running',?,?,?)",
                (sync_id, organisation_id, provider, direction, object_type, cursor or None, now, now),
            )
        return self.db.one("SELECT * FROM sync_runs WHERE id=?", (sync_id,)) or {}

    def complete_sync(self, sync_id: str, *, read_count: int = 0, write_count: int = 0,
                      cursor: str = "", error: str = "") -> dict:
        status = "Failed" if error else "Completed"
        with self.db.transaction() as tx:
            tx.execute(
                "UPDATE sync_runs SET status=?,read_count=?,write_count=?,cursor_after=?,error_message=?,completed_at=? WHERE id=?",
                (status, read_count, write_count, cursor or None, error or None, utc_now(), sync_id),
            )
        return self.db.one("SELECT * FROM sync_runs WHERE id=?", (sync_id,)) or {}

    def conflict(self, sync_id: str, *, provider: str, object_type: str,
                 conflict_type: str, local_id: str = "", external_id: str = "",
                 local: dict | None = None, external: dict | None = None) -> dict:
        sync = self.db.one("SELECT * FROM sync_runs WHERE id=?", (sync_id,))
        if not sync:
            raise KeyError("Sync run not found")
        conflict_id = new_id()
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT INTO sync_conflicts(id,organisation_id,sync_run_id,provider,object_type,local_id,external_id,conflict_type,local_json,external_json,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (conflict_id, sync["organisation_id"], sync_id, provider, object_type,
                 local_id or None, external_id or None, conflict_type,
                 canonical_json(local) if local is not None else None,
                 canonical_json(external) if external is not None else None, utc_now()),
            )
            tx.execute("UPDATE sync_runs SET conflict_count=conflict_count+1,status='Review Required' WHERE id=?", (sync_id,))
        return self.db.one("SELECT * FROM sync_conflicts WHERE id=?", (conflict_id,)) or {}

    def enqueue(self, organisation_id: str, *, topic: str, payload: dict,
                idempotency_key: str) -> dict:
        message_id, now = new_id(), utc_now()
        with self.db.transaction() as tx:
            existing = tx.one(
                "SELECT * FROM outbox_messages WHERE organisation_id=? AND topic=? AND idempotency_key=?",
                (organisation_id, topic, idempotency_key),
            )
            if existing:
                return existing
            tx.execute(
                "INSERT INTO outbox_messages(id,organisation_id,topic,payload_json,idempotency_key,available_at,created_at) VALUES (?,?,?,?,?,?,?)",
                (message_id, organisation_id, topic, canonical_json(payload), idempotency_key, now, now),
            )
        return self.db.one("SELECT * FROM outbox_messages WHERE id=?", (message_id,)) or {}

    def receive_webhook(self, provider: str, event_id: str, payload: bytes, *,
                        signature: str, secret: str, organisation_id: str | None = None) -> dict:
        expected = base64.b64encode(hmac.new(secret.encode(), payload, hashlib.sha256).digest()).decode()
        valid = hmac.compare_digest(expected, signature)
        receipt_id, now = new_id(), utc_now()
        with self.db.transaction() as tx:
            existing = tx.one("SELECT * FROM webhook_receipts WHERE provider=? AND external_event_id=?", (provider, event_id))
            if existing:
                return existing
            tx.execute(
                "INSERT INTO webhook_receipts(id,provider,external_event_id,organisation_id,signature_valid,payload_hash,received_at,status) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (receipt_id, provider, event_id, organisation_id, int(valid), sha256_bytes(payload),
                 now, "Received" if valid else "Rejected"),
            )
        return self.db.one("SELECT * FROM webhook_receipts WHERE id=?", (receipt_id,)) or {}
