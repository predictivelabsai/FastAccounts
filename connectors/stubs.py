"""Explicit no-network stubs for planned external providers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import ConnectorResult


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


@dataclass(frozen=True)
class RoadmapStubConnector(StubConnector):
    """A no-network connector for catalogue entries whose adapter is unbuilt."""

    def _result(self, operation: str) -> ConnectorResult:
        return ConnectorResult(
            provider=self.key,
            operation=operation,
            ok=False,
            live=False,
            message=(
                "Adapter not yet built for this provider; see the integrations page; "
                "no credential was read, no network request was made, and no accounting "
                "record was changed."
            ),
        )


def connector_for(provider: str) -> StubConnector:
    """Compatibility import; the registry is the canonical dispatcher."""
    from .registry import connector_for as registry_connector_for

    return registry_connector_for(provider)
