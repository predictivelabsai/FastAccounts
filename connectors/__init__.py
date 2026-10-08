"""External accounting, filing-agent, bank, HR, and payroll connectors."""

from .base import Connector, ConnectorResult
from .providers import (
    EMTAExportProvider,
    FastHRProvider,
    HMRCProvider,
    MeritProvider,
    OpenBankingProvider,
    ProviderError,
    QuickBooksProvider,
    XeroProvider,
)
from .registry import PROVIDERS, REGISTRY, connector_for, provider_metadata
from .stubs import RoadmapStubConnector, StubConnector

__all__ = [
    "Connector", "ConnectorResult", "EMTAExportProvider", "FastHRProvider", "HMRCProvider",
    "MeritProvider", "OpenBankingProvider", "PROVIDERS", "ProviderError",
    "QuickBooksProvider", "REGISTRY", "RoadmapStubConnector", "StubConnector",
    "XeroProvider", "connector_for", "provider_metadata",
]
