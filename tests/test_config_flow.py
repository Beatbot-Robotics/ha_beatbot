"""Tests for the Beatbot OAuth2 config flow."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from aiohttp import ClientError
import pytest
from beatbot_cloud import BeatbotAuthenticationError, BeatbotConnectionError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.config_entry_oauth2_flow import (
    AbstractOAuth2Implementation,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.beatbot import config_flow as config_flow_module
from custom_components.beatbot.config_flow import (
    BeatbotConfigFlow,
    BeatbotOAuth2Implementation,
)
from custom_components.beatbot.iot.const import DOMAIN

REDIRECT_URI = "http://example.com/auth/external/callback"


@pytest.fixture(autouse=True)
def mock_resource_api(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Avoid network access while validating the regional resource API."""
    get_devices = AsyncMock(return_value=[])
    monkeypatch.setattr(
        config_flow_module,
        "BeatbotClient",
        Mock(return_value=SimpleNamespace(get_devices=get_devices)),
    )
    return get_devices


def test_oauth_implementation_metadata(hass: HomeAssistant) -> None:
    """The built-in OAuth implementation exposes Beatbot metadata and scope."""
    implementation = BeatbotOAuth2Implementation(hass)

    assert implementation.name == "Beatbot"
    assert implementation.extra_authorize_data["scope"] == "device:info"


def test_flow_does_not_define_reauth_step() -> None:
    """Keep the custom flow aligned with the reviewed Core integration."""
    assert "async_step_reauth" not in BeatbotConfigFlow.__dict__


async def test_registers_local_implementation_when_missing(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A flow registers its local PKCE implementation when none exists."""
    flow = BeatbotConfigFlow()
    flow.hass = hass
    register = Mock()
    monkeypatch.setattr(
        config_entry_oauth2_flow,
        "async_get_implementations",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        config_entry_oauth2_flow,
        "async_register_implementation",
        register,
    )

    await flow._async_register_implementation()

    register.assert_called_once()
    assert register.call_args.args[:2] == (hass, DOMAIN)
    assert isinstance(register.call_args.args[2], BeatbotOAuth2Implementation)


def _make_token(sub: object, *, nonce: str = "v1", region: str | None = None) -> dict:
    """Build a fake OAuth2 token whose access_token is a JWT with `sub`.

    `nonce` differentiates tokens for the same account (simulating a refresh)
    without affecting the decoded `sub` used as unique id. `region` adds the
    custom region claim used to pick the resource API base URL.
    """
    claims: dict = {"sub": sub, "nonce": nonce}
    if region is not None:
        claims["region"] = region
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode()
    payload = payload.rstrip("=")
    return {
        "access_token": f"header.{payload}.signature",
        "refresh_token": f"refresh-{sub}-{nonce}",
        "token_type": "bearer",
        "expires_in": 3600,
        "scope": "device:info",
    }


class _MockOAuth2Implementation(AbstractOAuth2Implementation):
    """OAuth2 implementation that hands out a canned token (no HTTP)."""

    def __init__(
        self,
        token: dict | None = None,
        *,
        authorize_error: Exception | None = None,
        resolve_error: Exception | None = None,
    ) -> None:
        self._token = token
        self._authorize_error = authorize_error
        self._resolve_error = resolve_error

    @property
    def name(self) -> str:
        return "Mock Beatbot"

    @property
    def domain(self) -> str:
        return DOMAIN

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        if self._authorize_error is not None:
            raise self._authorize_error
        return "https://oauth.beatbot.com/oauth2/authorize"

    async def async_resolve_external_data(self, external_data) -> dict:
        if self._resolve_error is not None:
            raise self._resolve_error
        assert self._token is not None
        return self._token

    async def _async_refresh_token(self, token: dict) -> dict:
        assert self._token is not None
        return self._token


def _register_mock_impl(
    hass: HomeAssistant,
    token: dict | None = None,
    *,
    authorize_error: Exception | None = None,
    resolve_error: Exception | None = None,
) -> _MockOAuth2Implementation:
    """Register a canned-token OAuth2 implementation for the domain."""
    impl = _MockOAuth2Implementation(
        token,
        authorize_error=authorize_error,
        resolve_error=resolve_error,
    )
    config_entry_oauth2_flow.async_register_implementation(hass, DOMAIN, impl)
    return impl


async def _complete_external_auth(hass: HomeAssistant, flow_id: str) -> dict:
    """Drive the flow from the `auth` external step through to entry creation/abort."""
    result = await hass.config_entries.flow.async_configure(
        flow_id,
        {
            "code": "mock-code",
            "state": {"flow_id": flow_id, "redirect_uri": REDIRECT_URI},
        },
    )
    # external_step_done -> need one more configure to run `creation`
    if result["type"] is FlowResultType.EXTERNAL_STEP_DONE:
        result = await hass.config_entries.flow.async_configure(flow_id)
    return result


async def _start_user_flow(hass: HomeAssistant) -> dict:
    """Drive the user flow to the OAuth external step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"implementation": DOMAIN}
    )


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_creates_entry_with_jwt_sub_unique_id(
    hass: HomeAssistant,
) -> None:
    """Initial user flow creates one entry with unique_id = JWT `sub`."""
    _register_mock_impl(hass, _make_token("account-1", region="cn"))

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
    assert entries[0].title == "Beatbot"


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


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (BeatbotAuthenticationError(), "oauth_error"),
        (BeatbotConnectionError(), "cannot_connect"),
    ],
)
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_validates_resource_api(
    hass: HomeAssistant,
    mock_resource_api: AsyncMock,
    error: Exception,
    reason: str,
) -> None:
    """Abort when the regional device API rejects the new configuration."""
    mock_resource_api.side_effect = error
    _register_mock_impl(hass, _make_token("account-1", region="cn"))

    result = await _start_user_flow(hass)
    result = await _complete_external_auth(hass, result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_resource_api_client_receives_region_session_and_token(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Construct the library client directly from validated OAuth data."""
    client_session = SimpleNamespace()
    get_devices = AsyncMock(return_value=[])
    client = Mock(return_value=SimpleNamespace(get_devices=get_devices))
    monkeypatch.setattr(config_flow_module, "BeatbotClient", client)
    monkeypatch.setattr(
        config_flow_module,
        "async_get_clientsession",
        Mock(return_value=client_session),
    )
    flow = BeatbotConfigFlow()
    flow.hass = hass

    result = await flow._async_validate_resource_api(
        {"region": "cn", "token": {"access_token": "access-token"}}
    )

    assert result is None
    client.assert_called_once_with("cn", client_session, "access-token")
    get_devices.assert_awaited_once()


@pytest.mark.parametrize("sub", ["", 123, None])
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_rejects_invalid_subject(
    hass: HomeAssistant, sub: object
) -> None:
    """Require a non-empty string account subject before creating an entry."""
    _register_mock_impl(hass, _make_token(sub, region="cn"))

    result = await _start_user_flow(hass)
    result = await _complete_external_auth(hass, result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "oauth_error"
    assert not hass.config_entries.async_entries(DOMAIN)


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_rejects_malformed_access_token(
    hass: HomeAssistant,
) -> None:
    """Reject a token that cannot provide trusted account routing claims."""
    _register_mock_impl(
        hass,
        {
            "access_token": "not-a-jwt",
            "refresh_token": "refresh-account-1",
            "token_type": "bearer",
            "expires_in": 3600,
            "scope": "device:info",
        },
    )

    result = await _start_user_flow(hass)
    result = await _complete_external_auth(hass, result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "oauth_error"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_aborts_authorize_url_timeout(
    hass: HomeAssistant,
) -> None:
    """Timeout while building the authorize URL aborts clearly."""
    _register_mock_impl(hass, authorize_error=TimeoutError)

    result = await _start_user_flow(hass)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "authorize_url_timeout"


@pytest.mark.parametrize(
    ("resolve_error", "reason"),
    [
        (TimeoutError(), "oauth_timeout"),
        (ClientError(), "oauth_failed"),
    ],
)
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_aborts_oauth_resolve_errors(
    hass: HomeAssistant,
    resolve_error: Exception,
    reason: str,
) -> None:
    """Token exchange timeout and HTTP failures abort with HA OAuth reasons."""
    _register_mock_impl(hass, resolve_error=resolve_error)

    result = await _start_user_flow(hass)
    result = await _complete_external_auth(hass, result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    assert len(hass.config_entries.async_entries(DOMAIN)) == 0


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_aborts_invalid_oauth_token(hass: HomeAssistant) -> None:
    """A token response without expires_in is rejected as an OAuth error."""
    _register_mock_impl(
        hass,
        {
            "access_token": _make_token("account-1", region="cn")["access_token"],
            "refresh_token": "refresh-account-1",
            "token_type": "bearer",
            "scope": "device:info",
        },
    )

    result = await _start_user_flow(hass)
    result = await _complete_external_auth(hass, result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "oauth_error"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_aborts_when_user_rejects_authorization(
    hass: HomeAssistant,
) -> None:
    """A rejected OAuth authorization is surfaced as user_rejected_authorize."""
    _register_mock_impl(hass, _make_token("account-1", region="cn"))

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"error": "access_denied", "state": {"flow_id": result["flow_id"]}},
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP_DONE

    result = await hass.config_entries.flow.async_configure(result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "user_rejected_authorize"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_aborts_unknown_region(hass: HomeAssistant) -> None:
    """A token whose region is not in the known map aborts with unknown_region."""
    _register_mock_impl(hass, _make_token("account-1", region="zz"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"implementation": DOMAIN}
    )
    result = await _complete_external_auth(hass, result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unknown_region"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 0


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_aborts_missing_region(hass: HomeAssistant) -> None:
    """A token with no region claim aborts with unknown_region (no fallback)."""
    _register_mock_impl(hass, _make_token("account-1"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"implementation": DOMAIN}
    )
    result = await _complete_external_auth(hass, result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "unknown_region"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 0


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_user_flow_aborts_duplicate_account(hass: HomeAssistant) -> None:
    """The same Beatbot account cannot be configured twice."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="account-1",
        title="Beatbot",
        source=SOURCE_USER,
        data={
            "auth_implementation": DOMAIN,
            "region": "cn",
            "token": _make_token("account-1", region="cn"),
        },
    )
    entry.add_to_hass(hass)
    _register_mock_impl(hass, _make_token("account-1", nonce="new", region="cn"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"implementation": DOMAIN}
    )
    result = await _complete_external_auth(hass, result["flow_id"])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
