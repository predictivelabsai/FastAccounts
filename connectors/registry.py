"""Canonical connector registry and configure-dialog field metadata."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal, Mapping

import integrations

from .base import Connector
from .providers import FastHRProvider, MeritProvider, QuickBooksProvider, XeroProvider
from .stubs import RoadmapStubConnector, StubConnector


RegistryStatus = Literal["Adapter ready", "Planning stub", "Roadmap · adapter not built"]
ConnectorFactory = Callable[[Mapping[str, Any], Mapping[str, Any]], Connector]


@dataclass(frozen=True)
class CredentialField:
    name: str
    label: str
    input_type: Literal["text", "secret", "boolean"] = "text"
    required: bool = True
    default: str | bool | None = None
    note: str = ""


@dataclass(frozen=True)
class ConnectorRegistration:
    status: RegistryStatus
    factory: ConnectorFactory
    credential_fields: tuple[CredentialField, ...] = ()
    credential_note: str = ""


def _planning_stub(key: str) -> ConnectorFactory:
    def build(_credentials: Mapping[str, Any], _config: Mapping[str, Any]) -> Connector:
        return StubConnector(key)

    return build


def _roadmap_stub(key: str) -> ConnectorFactory:
    def build(_credentials: Mapping[str, Any], _config: Mapping[str, Any]) -> Connector:
        return RoadmapStubConnector(key)

    return build


_ROADMAP_NOTE = (
    "Adapter not yet built for this provider; credential fields will be defined "
    "when provider access and the reviewed data contract are agreed."
)


REGISTRY: dict[str, ConnectorRegistration] = {
    "fasthr": ConnectorRegistration(
        status="Adapter ready",
        factory=lambda credentials, config: FastHRProvider(
            base_url=credentials.get("base_url") or config.get("base_url") or FastHRProvider.default_base_url,
            token=credentials.get("token", ""),
        ),
        credential_fields=(
            CredentialField("base_url", "Base URL", required=True, default=FastHRProvider.default_base_url),
            CredentialField("token", "API token", "secret"),
        ),
        credential_note="Pull-only employee master-data access.",
    ),
    "quickbooks": ConnectorRegistration(
        status="Adapter ready",
        factory=lambda credentials, config: QuickBooksProvider(
            access_token=credentials.get("access_token", ""),
            realm_id=credentials.get("realm_id") or config.get("realm_id", ""),
            sandbox=credentials.get("sandbox", config.get("sandbox", True)),
        ),
        credential_fields=(
            CredentialField("access_token", "Access token", "secret"),
            CredentialField("realm_id", "Company realm ID"),
            CredentialField("sandbox", "Use sandbox", "boolean", required=False, default=True),
        ),
    ),
    "xero": ConnectorRegistration(
        status="Adapter ready",
        factory=lambda credentials, config: XeroProvider(
            access_token=credentials.get("access_token", ""),
            tenant_id=credentials.get("tenant_id") or config.get("tenant_id", ""),
        ),
        credential_fields=(
            CredentialField("access_token", "Access token", "secret"),
            CredentialField("tenant_id", "Tenant ID"),
        ),
    ),
    "merit": ConnectorRegistration(
        status="Adapter ready",
        factory=lambda credentials, config: MeritProvider(
            api_id=credentials.get("api_id") or config.get("api_id", ""),
            api_key=credentials.get("api_key", ""),
        ),
        credential_fields=(
            CredentialField("api_id", "API ID"),
            CredentialField("api_key", "API key", "secret"),
        ),
    ),
    "hmrc": ConnectorRegistration(
        status="Planning stub",
        factory=_planning_stub("hmrc"),
        credential_note=(
            "TBD: the production credential exchange depends on HMRC application "
            "approval and fraud-prevention-header readiness."
        ),
    ),
    "emta": ConnectorRegistration(
        status="Planning stub",
        factory=_planning_stub("emta"),
        credential_note=(
            "TBD: direct e-MTA filing needs a supported channel or X-Road service "
            "agreement; reviewed exports need no provider credential."
        ),
    ),
    "open_banking": ConnectorRegistration(
        status="Planning stub",
        factory=_planning_stub("open_banking"),
        credential_note=(
            "TBD: credential fields depend on the selected AISP and its consent "
            "lifecycle."
        ),
    ),
}

for _integration in integrations.CATALOGUE:
    if _integration.key not in REGISTRY:
        REGISTRY[_integration.key] = ConnectorRegistration(
            status="Roadmap · adapter not built",
            factory=_roadmap_stub(_integration.key),
            credential_note=_ROADMAP_NOTE,
        )


def registration_for(provider: str) -> ConnectorRegistration:
    key = provider.strip().lower()
    try:
        return REGISTRY[key]
    except KeyError as error:
        raise KeyError(f"Unknown connector: {provider}") from error


def connector_for(
    provider: str,
    *,
    credentials: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> Connector:
    """Construct a connector without retaining the caller's credential payload."""
    registration = registration_for(provider)
    return registration.factory(dict(credentials or {}), dict(config or {}))


def provider_metadata(provider: str) -> dict[str, Any]:
    registration = registration_for(provider)
    return {
        "registry_status": registration.status,
        "credential_fields": [asdict(field) for field in registration.credential_fields],
        "credential_note": registration.credential_note,
    }


PROVIDERS = frozenset(REGISTRY)
