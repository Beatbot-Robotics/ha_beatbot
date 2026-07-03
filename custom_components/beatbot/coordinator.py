import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.exceptions import ConfigEntryAuthFailed

from .api import BeatbotAPI, BeatbotAuthError, BeatbotConnectionError
from .iot.category import CATEGORY_MAP
from .iot.const import (
    DOMAIN,
    NETWORK_REFRESH_INTERVAL,
    POST_CONTROL_REFRESH_DELAY,
    SUPPORTED_PRODUCT_CATEGORIES,
    SUPPORTED_PRODUCT_IDS,
)
from .iot.mapping import apply_state
from .models import BeatbotDeviceData

_LOGGER = logging.getLogger(__name__)


class BeatbotCoordinator(DataUpdateCoordinator[dict[str, BeatbotDeviceData]]):
    def __init__(
        self,
        hass: HomeAssistant,
        api: BeatbotAPI,
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=NETWORK_REFRESH_INTERVAL),
        )
        self.api = api
        # Post-control refresh tasks spawned via async_schedule_device_state_refresh.
        # Tracked so async_unload_entry can cancel any still-pending refresh before
        # the coordinator/api/session are torn down (otherwise the detached task
        # leaks the whole object graph and fires through a closed session).
        self._refresh_tasks: set[asyncio.Task] = set()

    async def _async_update_data(self) -> dict[str, BeatbotDeviceData]:
        try:
            devices = await self.api.get_devices()
        except BeatbotAuthError as err:
            raise ConfigEntryAuthFailed from err
        except BeatbotConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err

        # Two-layer gating: category first (coarse — "do we support this
        # product line at all"), then productId (fine — "is this specific
        # model verified"). CATEGORY_MAP normalizes the backend's
        # productCategory string (incl. casing variants) to a ProductCategory
        # enum; an unmapped/unknown category yields None and is rejected here,
        # so half-implemented lines (e.g. lawn_mower with empty status/error
        # maps) and unknown categories never produce stub entities. Dropped
        # devices are logged at INFO so a user whose model is not yet on the
        # allow-list can see why it never appears in HA instead of vanishing
        # silently.
        result: dict[str, BeatbotDeviceData] = {}
        for d in devices:
            if CATEGORY_MAP.get(d.product_category) not in SUPPORTED_PRODUCT_CATEGORIES:
                _LOGGER.info(
                    "Skipping device %s (productId=%s): product category %r is "
                    "not supported by this integration",
                    d.device_id, d.product_id, d.product_category,
                )
                continue
            if d.product_id not in SUPPORTED_PRODUCT_IDS:
                _LOGGER.info(
                    "Skipping device %s: productId %r is not on the verified "
                    "allow-list (add it to SUPPORTED_PRODUCT_IDS to enable)",
                    d.device_id, d.product_id,
                )
                continue
            result[d.device_id] = d

        # Runtime state is best-effort: a connection failure must not wipe the
        # entities — keep discovery identity data and last-known values. An auth
        # failure still escalates to reauth, since the token is invalid for both
        # endpoints.
        try:
            states = await self.api.get_device_states()
        except BeatbotAuthError as err:
            raise ConfigEntryAuthFailed from err
        except BeatbotConnectionError as err:
            _LOGGER.warning(
                "Device state fetch failed, using discovery-only data: %s", err
            )
            states = {}

        for device_id, device in result.items():
            if (state := states.get(device_id)) is not None:
                apply_state(device, state.get("states"), state.get("is_online"))
        return result

    async def async_refresh_device_state(self, device_id: str) -> None:
        """Fetch state for one device and push it to entities immediately.

        Used after a control command (start/pause/return/work_mode) to confirm
        the new state quickly and cheaply: a single `GET /devices/{id}/state`
        instead of re-running the full discovery + batch-state refresh. The
        30s poll still runs as normal for everything else.

        Waits `POST_CONTROL_REFRESH_DELAY` before fetching: the device does
        not report the new state the instant the action is issued, so reading
        immediately can return the previous value.

        Best-effort like the batch path: a connection failure is logged and
        skipped (last-known values stay), while an auth failure escalates to
        reauth since the token is invalid.
        """
        await asyncio.sleep(POST_CONTROL_REFRESH_DELAY)
        try:
            state = await self.api.get_device_state(device_id)
        except BeatbotAuthError as err:
            raise ConfigEntryAuthFailed from err
        except BeatbotConnectionError as err:
            _LOGGER.warning(
                "Single-device state fetch failed for %s: %s", device_id, err
            )
            return

        device = self.data.get(device_id)
        if device is None:
            return
        apply_state(device, state.get("states"), state.get("is_online"))
        # Push the in-place update to listeners and reset the poll timer so
        # we don't double-fetch right after this manual update.
        self.async_set_updated_data(self.data)

    @callback
    def async_apply_device_event(
        self,
        device_id: str,
        states: dict | None,
        is_online: bool | None = None,
    ) -> None:
        """Overlay a pushed state delta without changing the poll cadence."""
        device = self.data.get(device_id)
        if device is None:
            _LOGGER.debug("Ignoring event for undiscovered device %s", device_id)
            return
        apply_state(device, states, is_online)
        # DataUpdateCoordinator.async_set_updated_data resets the next poll
        # deadline. Notify listeners directly so steady event traffic cannot
        # postpone the source-of-truth reconciliation poll indefinitely.
        self.async_update_listeners()

    @callback
    def async_schedule_device_state_refresh(self, device_id: str) -> None:
        """Schedule a delayed single-device state refresh without blocking.

        Spawns a tracked background task (stored in self._refresh_tasks) so
        the control service call returns immediately and the device's new
        state is picked up `POST_CONTROL_REFRESH_DELAY` later once the device
        has actually applied the command. Tracking lets async_unload_entry
        cancel a still-sleeping refresh instead of letting it fire through a
        torn-down session.
        """

        async def _refresh() -> None:
            await self.async_refresh_device_state(device_id)

        task = self.hass.async_create_task(_refresh())
        self._refresh_tasks.add(task)
        task.add_done_callback(self._refresh_tasks.discard)

    @callback
    def async_cancel_pending_refreshes(self) -> None:
        """Cancel any in-flight post-control refresh tasks.

        Call from async_unload_entry so a refresh sleeping inside its
        POST_CONTROL_REFRESH_DELAY window is cancelled rather than left to
        run against a coordinator/api/session that is being torn down.
        """
        for task in self._refresh_tasks:
            task.cancel()
        self._refresh_tasks.clear()
