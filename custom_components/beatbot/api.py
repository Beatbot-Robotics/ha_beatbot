"""Home Assistant OAuth adapter for the Beatbot cloud client."""

from __future__ import annotations

from aiohttp import ClientError, ClientResponseError
from beatbot_cloud import (
    BeatbotAuthenticationError,
    BeatbotConnectionError,
)

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow

BeatbotAuthError = BeatbotAuthenticationError

__all__ = [
    "BeatbotAuthError",
    "BeatbotConnectionError",
    "async_get_access_token",
]


async def async_get_access_token(
    session: config_entry_oauth2_flow.OAuth2Session,
) -> str:
    """Return a valid token and translate OAuth failures for the library."""
    try:
        await session.async_ensure_token_valid()
    except ConfigEntryAuthFailed as err:
        raise BeatbotAuthenticationError from err
    except ClientResponseError as err:
        if 400 <= err.status < 500 and err.status not in (408, 429):
            raise BeatbotAuthenticationError from err
        raise BeatbotConnectionError("OAuth token refresh failed") from err
    except (TimeoutError, ClientError) as err:
        raise BeatbotConnectionError("OAuth token refresh failed") from err
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as err:
        raise BeatbotConnectionError(
            "OAuth token refresh returned invalid data"
        ) from err

    try:
        token = session.token
    except (AttributeError, KeyError, TypeError) as err:
        raise BeatbotAuthenticationError("Missing OAuth access token") from err
    if not isinstance(token, dict):
        raise BeatbotAuthenticationError("Missing OAuth access token")
    access_token = token.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise BeatbotAuthenticationError("Missing OAuth access token")
    return access_token
