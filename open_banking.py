"""Tenant-scoped GoCardless consent links and manual, idempotent bank feeds."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlparse

import httpx

from banking import BankingService
from connectors.providers import OpenBankingProvider, ProviderError
from connectors.registry import connector_for
from core_utils import audit, canonical_json, utc_now
from database import get_database
from integration_service import IntegrationService


class OpenBankingService:
    def __init__(self, db=None, provider=None):
        self.db = db or get_database()
        self.integrations = IntegrationService(self.db)
        self.provider = provider

    def configure(self, organisation_id, secret_id, secret_key, actor):
        if not secret_id or not secret_key:
            raise ValueError("GoCardless secret ID and secret key are required")
        connection = self.integrations.configure(organisation_id, "open_banking",
            credentials={"secret_id": secret_id, "secret_key": secret_key}, config={}, actor=actor)
        return self.integrations.public_connection(connection)

    def _connection(self, organisation_id):
        connection = self.integrations.connection_for_provider(organisation_id, "open_banking")
        if connection["status"] == "Disconnected":
            raise ValueError("GoCardless connection is disconnected; configure it again")
        return connection

    def _provider(self, connection):
        if self.provider is not None:
            return self.provider
        private = self.integrations.connection(connection["id"], include_credentials=True)
        provider = connector_for("open_banking", credentials=private["credentials"])
        encrypted = connection["config"].get("access_token_encrypted")
        if encrypted:
            provider.access_token = self.integrations.vault.decrypt(encrypted)["access_token"]
        return provider

    def _save(self, connection, config, actor, *, status=None, provider=None):
        if provider is not None and getattr(provider, "access_token", ""):
            config["access_token_encrypted"] = self.integrations.vault.encrypt(
                {"access_token": provider.access_token})
        status = status or connection["status"]
        with self.db.transaction() as tx:
            tx.execute("UPDATE integration_connections SET config_json=?,status=?,updated_at=? "
                       "WHERE id=? AND organisation_id=?",
                       (canonical_json(config), status, utc_now(), connection["id"], connection["organisation_id"]))
            audit(tx, connection["organisation_id"], actor, "open_banking.updated", "integration_connection",
                  connection["id"], {"status": status})
        return self.integrations.public_connection(self.integrations.connection(connection["id"]))

    def _request(self, connection, provider, method, *args, actor="system", **kwargs):
        try:
            return getattr(provider, method)(*args, **kwargs)
        except (ProviderError, httpx.RequestError) as error:
            status = "Reauth Required" if isinstance(error, ProviderError) and OpenBankingProvider._status_code(error) in {401, 403} else "Error"
            self._save(connection, dict(connection["config"]), actor, status=status)
            message = "GoCardless request failed. Re-link the bank to renew access." if status == "Reauth Required" else "GoCardless request failed. Try again later."
            raise ValueError(message) from error

    def start_link(self, organisation_id, *, institution_id, redirect_url, actor):
        if not institution_id or urlparse(redirect_url).scheme not in {"https", "http"} or not urlparse(redirect_url).netloc:
            raise ValueError("A bank institution and HTTP redirect URL are required")
        connection = self._connection(organisation_id)
        provider = self._provider(connection)
        credentials = self.integrations.connection(connection["id"], include_credentials=True)["credentials"]
        self._request(connection, provider, "fetch_token", credentials["secret_id"], credentials["secret_key"], actor=actor)
        requisition = self._request(connection, provider, "create_requisition", actor=actor,
            redirect=redirect_url, institution_id=institution_id, reference=organisation_id)
        config = {"requisition_id": requisition["id"], "requisition_status": requisition.get("status", "CR"),
                  "account_ids": [], "account_mappings": {}}
        self._save(connection, config, actor, status="Configured", provider=provider)
        return {"link": requisition["link"], "requisition_id": requisition["id"]}

    def complete_link(self, organisation_id, *, actor):
        connection = self._connection(organisation_id)
        config = dict(connection["config"])
        if not config.get("requisition_id"):
            raise ValueError("Start a bank consent link first")
        provider = self._provider(connection)
        requisition = self._request(connection, provider, "get_requisition", config["requisition_id"], actor=actor)
        config["requisition_status"] = requisition["status"]
        config["account_ids"] = requisition.get("accounts") or []
        config["account_mappings"] = {key: value for key, value in config.get("account_mappings", {}).items()
                                      if key in config["account_ids"]}
        status = "Connected" if requisition["status"] == "LN" and config["account_ids"] else (
            "Reauth Required" if requisition["status"] in {"EX", "RJ"} else "Configured")
        return self._save(connection, config, actor, status=status, provider=provider)

    @staticmethod
    def _accepted(connection, account_id):
        if connection["status"] != "Connected" or connection["config"].get("requisition_status") != "LN":
            raise ValueError("Bank consent has not been completed")
        if account_id not in connection["config"].get("account_ids", []):
            raise ValueError("GoCardless account is not in this organisation's completed requisition")

    def link_account(self, organisation_id, *, gocardless_account_id, bank_account_id, actor):
        connection = self._connection(organisation_id)
        self._accepted(connection, gocardless_account_id)
        bank = self.db.one("SELECT id FROM bank_accounts WHERE id=? AND organisation_id=?",
                           (bank_account_id, organisation_id))
        if not bank:
            raise ValueError("Bank account is not in this organisation")
        config = dict(connection["config"])
        config.setdefault("account_mappings", {})[gocardless_account_id] = bank_account_id
        self._save(connection, config, actor)
        return {"gocardless_account_id": gocardless_account_id, "bank_account_id": bank_account_id}

    def institutions(self, country, *, organisation_id=None):
        country = country.upper()
        if country == "UK":
            country = "GB"
        if len(country) != 2 or not country.isalpha():
            raise ValueError("Country must be a two-letter code")
        if organisation_id:
            connection = self._connection(organisation_id)
            provider = self._provider(connection)
            return self._request(connection, provider, "institutions", country)
        if self.provider is None:
            raise ValueError("An organisation connection is required")
        return self.provider.institutions(country)

    def accounts(self, organisation_id):
        connection = self._connection(organisation_id)
        if connection["status"] != "Connected":
            return []
        provider = self._provider(connection)
        accounts = []
        for account_id in connection["config"].get("account_ids", []):
            self._accepted(connection, account_id)
            details = self._request(connection, provider, "get_account", account_id)
            accounts.append({"gocardless_account_id": account_id,
                "bank_account_id": connection["config"].get("account_mappings", {}).get(account_id),
                "iban": details.get("iban", ""), "status": details.get("status", ""),
                "balances": self._request(connection, provider, "balances", account_id).get("balances", [])})
        return accounts

    def pull(self, organisation_id, *, gocardless_account_id, actor):
        connection = self._connection(organisation_id)
        self._accepted(connection, gocardless_account_id)
        bank_id = connection["config"].get("account_mappings", {}).get(gocardless_account_id)
        if not bank_id or not self.db.one("SELECT id FROM bank_accounts WHERE id=? AND organisation_id=?",
                                         (bank_id, organisation_id)):
            raise ValueError("Link this GoCardless account to an organisation bank account first")
        provider = self._provider(connection)
        payload = self._request(connection, provider, "transactions", gocardless_account_id, actor=actor,
            date_from=(date.today() - timedelta(days=90)).isoformat())
        rows = []
        for transaction in payload["transactions"].get("booked", []):
            amount = Decimal(transaction["transactionAmount"]["amount"])
            if not amount.is_finite():
                raise ValueError("Bank transaction amount must be finite")
            rows.append({"external_id": transaction.get("transactionId", ""),
                "booking_date": transaction.get("bookingDate") or transaction.get("valueDate"),
                "value_date": transaction.get("valueDate"), "amount": amount,
                "currency": transaction["transactionAmount"].get("currency") or transaction.get("currencyCode"),
                "counterparty": (transaction.get("creditorName") if amount < 0 else transaction.get("debtorName"))
                    or transaction.get("creditorName") or transaction.get("debtorName") or "",
                "reference": transaction.get("remittanceInformationUnstructured") or
                    " ".join(transaction.get("remittanceInformationUnstructuredArray") or []),
                "raw": transaction})
        summary = BankingService(self.db)._import(organisation_id, bank_id,
            canonical_json(rows).encode(), "open_banking", rows, actor)
        self._save(connection, dict(connection["config"]), actor, provider=provider)
        return summary
