"""External accounting, filing-agent, bank, HR, and payroll connectors."""

from .base import Connector, ConnectorResult
from .providers import (
    BambooHRProvider,
    EMTAExportProvider,
    FastHRProvider,
    HMRCProvider,
    MeritProvider,
    OpenBankingProvider,
    PersonioProvider,
    ProviderError,
    QuickBooksProvider,
    XeroProvider,
)
from .registry import PROVIDERS, REGISTRY, connector_for, provider_metadata
from .stubs import RoadmapStubConnector, StubConnector

__all__ = [
    "BambooHRProvider", "Connector", "ConnectorResult", "EMTAExportProvider", "FastHRProvider", "HMRCProvider",
    "MeritProvider", "OpenBankingProvider", "PROVIDERS", "ProviderError",
    "PersonioProvider", "QuickBooksProvider", "REGISTRY", "RoadmapStubConnector", "StubConnector",
    "XeroProvider", "connector_for", "provider_metadata",
]
