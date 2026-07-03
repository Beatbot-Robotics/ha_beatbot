"""Tests for the Beatbot API client (region-based base URL resolution)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.beatbot.api import BeatbotAPI
from custom_components.beatbot.iot.const import REGION_API_BASE_URL


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
    ],
)
def test_api_base_url_resolves_by_region(
    region: str, expected_base: str
) -> None:
    """The base URL follows the entry's region claim."""
    api = _api_for_region(region)

    assert api._base_url == expected_base


@pytest.mark.parametrize("region", [None, "unknown-region"])
def test_api_rejects_missing_or_unknown_region(region: str | None) -> None:
    """A missing or unmapped region raises instead of silently falling back."""
    with pytest.raises(ValueError):
        _api_for_region(region)
