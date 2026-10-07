"""No-network connector stub contracts."""
from __future__ import annotations

import pytest

from connectors import connector_for


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
