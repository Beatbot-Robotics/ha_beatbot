"""Tests for the Beatbot API client (region-based base URL resolution)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.beatbot_home import api as api_mod
from custom_components.beatbot_home.api import BeatbotAPI
from custom_components.beatbot_home.iot.const import (
    BEATBOT_API_BASE_URL,
    REGION_API_BASE_URL,
)


def _api_for_region(region: str | None) -> BeatbotAPI:
    """Build a BeatbotAPI with a config entry carrying the given region."""
    data = {} if region is None else {"region": region}
    entry = SimpleNamespace(data=data)
    # hass/session are unused at construction time; __init__ only stores them
    # and resolves the base URL from the entry.
    return BeatbotAPI(None, entry, None)


@pytest.mark.parametrize(
    ("region", "expected_base"),
    [
        ("cn", REGION_API_BASE_URL["cn"]),
        ("na", REGION_API_BASE_URL["na"]),
        ("eu", REGION_API_BASE_URL["eu"]),
        (None, BEATBOT_API_BASE_URL),        # missing region -> dev fallback
        ("unknown-region", BEATBOT_API_BASE_URL),  # unmapped region -> fallback
    ],
)
def test_api_base_url_resolves_by_region(
    region: str | None, expected_base: str, monkeypatch
) -> None:
    """With DEV_MODE off, the base URL follows the token's region claim."""
    monkeypatch.setattr(api_mod, "DEV_MODE", False)

    api = _api_for_region(region)

    assert api._base_url == expected_base


@pytest.mark.parametrize("region", ["cn", "na", "eu", None, "unknown"])
def test_api_dev_mode_forces_local(region: str | None, monkeypatch) -> None:
    """With DEV_MODE on, the local dev backend is used regardless of region."""
    monkeypatch.setattr(api_mod, "DEV_MODE", True)

    api = _api_for_region(region)

    assert api._base_url == BEATBOT_API_BASE_URL
