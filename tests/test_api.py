"""Tests for the Home Assistant OAuth adapter."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp import ClientError, ClientResponseError
from beatbot_cloud import (
    BeatbotAuthenticationError,
    BeatbotClient,
    BeatbotConnectionError,
)
from beatbot_cloud.const import REGION_API_BASE_URL
import pytest

from homeassistant.exceptions import ConfigEntryAuthFailed

from custom_components.beatbot.api import async_get_access_token

REQUEST_INFO = SimpleNamespace(real_url="https://oauth.beatbot.com/oauth2/token")


@pytest.mark.parametrize(
    ("region", "expected_base"),
    [
        ("cn", REGION_API_BASE_URL["cn"]),
        ("na", REGION_API_BASE_URL["na"]),
        ("eu", REGION_API_BASE_URL["eu"]),
    ],
)
def test_api_base_url_resolves_by_region(region: str, expected_base: str) -> None:
    """The library client resolves the resource API from the token region."""
    api = BeatbotClient(region, SimpleNamespace(), "access-token")

    assert api._base_url == expected_base


@pytest.mark.parametrize("region", [None, "unknown-region"])
def test_api_rejects_missing_or_unknown_region(region: str | None) -> None:
    """A missing or unmapped region never falls back to another backend."""
    with pytest.raises(ValueError):
        BeatbotClient(region, SimpleNamespace(), "access-token")


async def test_access_token_provider_refreshes_and_returns_current_token() -> None:
    """Ask Home Assistant to refresh before returning the current token."""
    session = SimpleNamespace(
        token={"access_token": "new-token"},
        async_ensure_token_valid=AsyncMock(),
    )

    assert await async_get_access_token(session) == "new-token"
    session.async_ensure_token_valid.assert_awaited_once()


@pytest.mark.parametrize("access_token", [None, "", 123])
async def test_access_token_provider_rejects_missing_token(
    access_token: object,
) -> None:
    """An invalid refreshed token requires user reauthentication."""
    session = SimpleNamespace(
        token={"access_token": access_token},
        async_ensure_token_valid=AsyncMock(),
    )

    with pytest.raises(BeatbotAuthenticationError):
        await async_get_access_token(session)


@pytest.mark.parametrize("token", [None, [], "token"])
async def test_access_token_provider_rejects_invalid_token_mapping(
    token: object,
) -> None:
    """An invalid stored token cannot provide library credentials."""
    session = SimpleNamespace(
        token=token,
        async_ensure_token_valid=AsyncMock(),
    )

    with pytest.raises(BeatbotAuthenticationError):
        await async_get_access_token(session)


async def test_access_token_provider_translates_token_property_error() -> None:
    """A missing token mapping never leaks its raw lookup error."""

    class BrokenTokenSession:
        async def async_ensure_token_valid(self) -> None:
            return

        @property
        def token(self) -> dict:
            raise KeyError("token")

    with pytest.raises(BeatbotAuthenticationError):
        await async_get_access_token(BrokenTokenSession())


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_terminal_refresh_error_requires_reauthentication(status: int) -> None:
    """Classify terminal OAuth client errors as authentication failures."""
    session = SimpleNamespace(
        token={"access_token": "old"},
        async_ensure_token_valid=AsyncMock(
            side_effect=ClientResponseError(REQUEST_INFO, (), status=status)
        ),
    )

    with pytest.raises(BeatbotAuthenticationError):
        await async_get_access_token(session)


@pytest.mark.parametrize(
    "error",
    [
        ClientResponseError(REQUEST_INFO, (), status=408),
        ClientResponseError(REQUEST_INFO, (), status=429),
        ClientResponseError(REQUEST_INFO, (), status=500),
        ClientError(),
        TimeoutError(),
    ],
)
async def test_retryable_refresh_error_is_connection_failure(
    error: Exception,
) -> None:
    """Keep transient OAuth failures retryable instead of starting reauth."""
    session = SimpleNamespace(
        token={"access_token": "old"},
        async_ensure_token_valid=AsyncMock(side_effect=error),
    )

    with pytest.raises(BeatbotConnectionError):
        await async_get_access_token(session)


@pytest.mark.parametrize(
    "error",
    [
        AttributeError("invalid response"),
        KeyError("expires_in"),
        TypeError("invalid token"),
        ValueError("invalid expires_in"),
        OverflowError(),
    ],
)
async def test_invalid_refresh_response_is_connection_failure(
    error: Exception,
) -> None:
    """Keep malformed refresh responses contained and retryable."""
    session = SimpleNamespace(
        token={"access_token": "old"},
        async_ensure_token_valid=AsyncMock(side_effect=error),
    )

    with pytest.raises(BeatbotConnectionError) as exc_info:
        await async_get_access_token(session)
    assert exc_info.value.__cause__ is error


async def test_config_entry_auth_failure_is_translated() -> None:
    """Translate Home Assistant's auth signal into the library contract."""
    session = SimpleNamespace(
        token={"access_token": "old"},
        async_ensure_token_valid=AsyncMock(side_effect=ConfigEntryAuthFailed),
    )

    with pytest.raises(BeatbotAuthenticationError):
        await async_get_access_token(session)
