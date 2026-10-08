"""No-network connector stub contracts."""
from __future__ import annotations

import pytest

from connectors import FastHRProvider, connector_for
from connectors.registry import PROVIDERS, REGISTRY, provider_metadata
from integrations import CATALOGUE


@pytest.mark.parametrize(
    "provider",
    ["quickbooks", "xero", "merit", "hmrc", "emta", "open_banking"],
)
def test_connector_stubs_are_explicitly_non_live(provider):
    connector = connector_for(provider)
    for result in (
        connector.check(),
        connector.pull("invoices", cursor="not-used"),
        connector.push("contacts", [{"name": "Brightline Media Ltd"}]),
    ):
        assert result.provider == provider
        assert not result.ok
        assert not result.live
        assert result.records == ()
        assert "no network request" in result.message
        assert "no accounting record was changed" in result.message


def test_unknown_connector_is_rejected():
    with pytest.raises(KeyError, match="Unknown connector"):
        connector_for("made-up-provider")


def test_registry_covers_every_catalogue_provider():
    catalogue_keys = {item.key for item in CATALOGUE}
    assert PROVIDERS == catalogue_keys
    for provider in catalogue_keys:
        credentials = {"token": "synthetic-token"} if provider == "fasthr" else None
        connector = connector_for(provider, credentials=credentials)
        assert connector.key == provider


def test_roadmap_connectors_are_explicitly_non_live():
    result = connector_for("personio").check()
    assert not result.ok
    assert not result.live
    assert result.operation == "check"
    assert "Adapter not yet built for this provider" in result.message
    assert "no network request was made" in result.message


def test_credential_field_metadata_is_ordered_and_complete():
    assert [field["name"] for field in provider_metadata("quickbooks")["credential_fields"]] == [
        "access_token", "realm_id", "sandbox",
    ]
    assert [field["name"] for field in provider_metadata("xero")["credential_fields"]] == [
        "access_token", "tenant_id",
    ]
    assert [field["name"] for field in provider_metadata("merit")["credential_fields"]] == [
        "api_id", "api_key",
    ]
    for provider in ("hmrc", "emta", "open_banking"):
        assert provider_metadata(provider)["credential_note"].startswith("TBD:")
    assert "Adapter not yet built" in provider_metadata("personio")["credential_note"]


def test_fasthr_registration_is_explicit_and_not_overwritten_by_roadmap_loop():
    metadata = provider_metadata("fasthr")
    assert metadata["registry_status"] == "Adapter ready"
    assert [field["name"] for field in metadata["credential_fields"]] == ["base_url", "token"]
    assert metadata["credential_fields"][0]["default"] == "https://fasthr.eu"
    assert metadata["credential_fields"][1]["input_type"] == "secret"
    connector = connector_for(
        "fasthr",
        credentials={"base_url": "https://hr.example.test/", "token": "synthetic-token"},
    )
    assert isinstance(connector, FastHRProvider)
    assert connector.base_url == "https://hr.example.test"
    assert REGISTRY["fasthr"].status == "Adapter ready"
