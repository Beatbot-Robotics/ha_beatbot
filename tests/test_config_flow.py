"""Tests for the Beatbot Home OAuth2 config flow (incl. reauth)."""

from __future__ import annotations

import jwt
import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.config_entry_oauth2_flow import (
    AbstractOAuth2Implementation,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.beatbot_home.iot.const import DOMAIN

REDIRECT_URI = "http://localhost:8123/auth/external/callback"


def _make_token(sub: str, *, nonce: str = "v1", region: str | None = None) -> dict:
    """Build a fake OAuth2 token whose access_token is a JWT with `sub`.

    `nonce` differentiates tokens for the same account (simulating a refresh)
    without affecting the decoded `sub` used as unique id. `region` adds the
    custom region claim used to pick the resource API base URL.
    """
    claims: dict = {"sub": sub, "nonce": nonce}
    if region is not None:
        claims["region"] = region
    return {
        "access_token": jwt.encode(claims, "not-verified", algorithm="HS256"),
        "refresh_token": f"refresh-{sub}-{nonce}",
        "token_type": "bearer",
        "expires_in": 3600,
        "scope": "device:info",
    }


class _MockOAuth2Implementation(AbstractOAuth2Implementation):
    """OAuth2 implementation that hands out a canned token (no HTTP)."""

    def __init__(self, token: dict) -> None:
        self._token = token

    @property
    def name(self) -> str:
        return "Mock Beatbot"

    @property
    def domain(self) -> str:
        return DOMAIN

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        return "http://example.com/oauth2/authorize"

    async def async_resolve_external_data(self, external_data) -> dict:
        return self._token

    async def _async_refresh_token(self, token: dict) -> dict:
        return self._token


def _register_mock_impl(hass: HomeAssistant, token: dict) -> _MockOAuth2Implementation:
    """Register a canned-token OAuth2 implementation for the domain."""
    impl = _MockOAuth2Implementation(token)
    config_entry_oauth2_flow.async_register_implementation(hass, DOMAIN, impl)
    return impl


async def _complete_external_auth(hass: HomeAssistant, flow_id: str) -> dict:
    """Drive the flow from the `auth` external step through to entry creation/abort."""
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {"code": "mock-code", "state": {"flow_id": flow_id, "redirect_uri": REDIRECT_URI}},
    )
    # external_step_done -> need one more configure to run `creation`
    if result["type"] is FlowResultType.EXTERNAL_STEP_DONE:
        result = await hass.config_entries.flow.async_configure(flow_id)
    return result


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_creates_entry_with_jwt_sub_unique_id(hass: HomeAssistant) -> None:
    """Initial user flow creates one entry with unique_id = JWT `sub`."""
    _register_mock_impl(hass, _make_token("account-1"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pick_implementation"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"implementation": DOMAIN}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["step_id"] == "auth"

    result = await _complete_external_auth(hass, result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].unique_id == "account-1"
    assert entries[0].title == "Beatbot Home"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_stores_region_from_token(hass: HomeAssistant) -> None:
    """The custom `region` claim is stored on the entry for the API client."""
    _register_mock_impl(hass, _make_token("account-1", region="cn"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"implementation": DOMAIN}
    )
    result = await _complete_external_auth(hass, result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.data["region"] == "cn"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_reauth_updates_existing_entry_not_duplicate(hass: HomeAssistant) -> None:
    """Reauth with the same account updates the existing entry (no new entry)."""
    original_token = _make_token("account-1", nonce="old")
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account-1",
        title="Beatbot Home",
        source=SOURCE_USER,
        data={"auth_implementation": DOMAIN, "token": original_token},
    )
    entry.add_to_hass(hass)

    # New token for the SAME account (different nonce -> different access_token),
    # now also carrying a region claim (simulating the backend adding region).
    _register_mock_impl(hass, _make_token("account-1", nonce="new", region="cn"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "title_placeholders": {"name": entry.title},
            "unique_id": entry.unique_id,
        },
        data=entry.data,
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "pick_implementation"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"implementation": DOMAIN}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP

    result = await _complete_external_auth(hass, result["flow_id"])
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].entry_id == entry.entry_id
    assert entries[0].unique_id == "account-1"
    new_access_token = entries[0].data["token"]["access_token"]
    assert new_access_token != original_token["access_token"]
    # Region from the refreshed token is persisted on the entry.
    assert entries[0].data["region"] == "cn"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_reauth_different_account_aborts_unique_id_mismatch(
    hass: HomeAssistant,
) -> None:
    """Reauth with a different account aborts with unique_id_mismatch."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account-1",
        title="Beatbot Home",
        source=SOURCE_USER,
        data={"auth_implementation": DOMAIN, "token": _make_token("account-1")},
    )
    entry.add_to_hass(hass)

    # Re-authenticate as a DIFFERENT account.
    _register_mock_impl(hass, _make_token("account-2"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": SOURCE_REAUTH,
            "entry_id": entry.entry_id,
            "title_placeholders": {"name": entry.title},
            "unique_id": entry.unique_id,
        },
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"implementation": DOMAIN}
    )
    result = await _complete_external_auth(hass, result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unique_id_mismatch"

    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    assert entries[0].entry_id == entry.entry_id
    assert entries[0].unique_id == "account-1"
