"""The Beatbot integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_entry_oauth2_flow

from .api import BeatbotAPI
from .config_flow import BeatbotOAuth2Implementation
from .coordinator import BeatbotCoordinator
from .iot.const import DOMAIN
from .iot.const import SUPPORTED_PLATFORMS
from .iot.event_stream import BeatbotEventClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Beatbot from a config entry."""
    implementations = await config_entry_oauth2_flow.async_get_implementations(
        hass, DOMAIN
    )
    if DOMAIN not in implementations:
        config_entry_oauth2_flow.async_register_implementation(
            hass, DOMAIN, BeatbotOAuth2Implementation(hass)
        )

    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    )

    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    api = BeatbotAPI(hass, entry, session)
    coordinator = BeatbotCoordinator(hass, api)

    await coordinator.async_config_entry_first_refresh()

    event_client = BeatbotEventClient(hass, entry, session, api, coordinator)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
        "session": session,
        "event_client": event_client,
    }

    await hass.config_entries.async_forward_entry_setups(entry, SUPPORTED_PLATFORMS)
    event_client.async_start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Cancel any post-control refresh tasks still sleeping in their delay
    # window before tearing down the coordinator/api/session they close over.
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data and data.get("event_client") is not None:
        await data["event_client"].async_stop()
    if data and data.get("coordinator") is not None:
        data["coordinator"].async_cancel_pending_refreshes()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, SUPPORTED_PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
