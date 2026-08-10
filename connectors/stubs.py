"""Explicit no-network stubs for planned external providers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ConnectorResult


SUPPORTED_PROVIDERS = {
    "quickbooks", "xero", "merit", "hmrc", "emta", "open_banking",
}


@dataclass(frozen=True)
class StubConnector:
    key: str

    def _result(self, operation: str) -> ConnectorResult:
        return ConnectorResult(
            provider=self.key,
            operation=operation,
            ok=False,
            live=False,
            message=(
                "Planning stub only: no credential was read, no network request "
                "was made, and no accounting record was changed."
            ),
        )

    def check(self) -> ConnectorResult:
        return self._result("check")

    def pull(self, object_type: str, *, cursor: str | None = None) -> ConnectorResult:
        del cursor
        return self._result(f"pull:{object_type}")

    def push(self, object_type: str, records: list[dict[str, Any]]) -> ConnectorResult:
        del records
        return self._result(f"push:{object_type}")


def connector_for(provider: str) -> StubConnector:
    key = provider.strip().lower()
    if key not in SUPPORTED_PROVIDERS:
        raise KeyError(f"Unknown connector: {provider}")
    return StubConnector(key)
