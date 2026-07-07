"""Pytest configuration for the Beatbot custom integration tests."""

import pytest
from awesomeversion import AwesomeVersion
from homeassistant.loader import Integration

from custom_components.beatbot.iot.const import DOMAIN

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def load_core_format_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let the custom-component harness load the Core-format manifest.

    Home Assistant requires a version for custom integrations, while built-in
    Core integrations must omit it. This repository targets Core, so provide a
    test-only version through the loader instead of changing the manifest.
    """
    original_version = Integration.version.fget

    def _version(integration: Integration) -> AwesomeVersion | None:
        if integration.domain == DOMAIN:
            return AwesomeVersion("0.0.0")
        assert original_version is not None
        return original_version(integration)

    monkeypatch.setattr(Integration, "version", property(_version))
