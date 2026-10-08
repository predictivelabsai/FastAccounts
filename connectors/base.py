"""Provider-neutral connector contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ConnectorResult:
    """Stable connector response that makes non-live behavior unambiguous."""

    provider: str
    operation: str
    ok: bool
    live: bool
    message: str
    records: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    cursor: str | None = None


class Connector(Protocol):
    key: str

    def check(self) -> ConnectorResult: ...

    def pull(self, object_type: str, *, cursor: str | None = None) -> ConnectorResult: ...

    def push(self, object_type: str, records: list[dict[str, Any]]) -> ConnectorResult: ...
