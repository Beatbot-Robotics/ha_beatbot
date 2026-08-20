Beatbot Home Assistant Integration
==================================

Beatbot integration connects Home Assistant to supported Beatbot cloud accounts and exposes supported pool-cleaning devices as Home Assistant entities.

This integration uses Beatbot OAuth authorization and Beatbot cloud APIs. WebSocket push events are used for real-time updates, with a low-frequency coordinator refresh for discovery and reconciliation.

Supported Devices
-----------------

The integration currently supports Beatbot devices whose product IDs are included in `custom_components/beatbot/iot/const.py`. Unsupported devices are ignored during discovery so they do not create incomplete entities.

Supported Regions
-----------------

The Beatbot OAuth access token must include one of these region claims:

- `cn`: Mainland China
- `na`: North America
- `eu`: Europe

If the account does not return a supported region, setup aborts with `unknown_region`. The integration does not fall back to another region because that could route traffic to the wrong Beatbot backend.

Installation
------------

For a custom-component installation:

1. Copy `custom_components/beatbot` into the Home Assistant `custom_components` directory.
2. Restart Home Assistant.
3. Go to Settings > Devices & services.
4. Select Add integration.
5. Search for Beatbot.
6. Follow the OAuth authorization flow.

For Home Assistant Core submission, the integration files belong under `homeassistant/components/beatbot`, and documentation and brand assets must be submitted to the Home Assistant documentation and Brands repositories.

OAuth Setup
-----------

The integration uses Home Assistant's OAuth2 config flow with PKCE. During setup, Home Assistant opens the Beatbot authorization page and receives the OAuth callback through Home Assistant's external auth callback.

Requirements:

- Home Assistant 2026.7.0 or newer is required.
- Home Assistant must be able to generate a valid external callback URL.
- My Home Assistant can be used for the callback redirect.
- The Beatbot account must authorize Home Assistant access.
- The returned access token must include `sub` and a supported `region` claim.

The `sub` claim is used as the unique ID for the config entry. This prevents the same Beatbot account from being configured more than once.

The integration does not implement a separate reauthentication flow. If the
Beatbot authorization becomes invalid, remove the integration entry and add it
again to authorize the account with fresh credentials.

Removal
-------

To remove the integration from Home Assistant:

1. Go to Settings > Devices & services.
2. Open the Beatbot integration entry.
3. Select Delete.
4. Confirm removal.

Home Assistant unloads Beatbot platforms, stops the WebSocket event client, and cancels pending refresh tasks during entry unload.

Development
-----------

Run tests from the repository root with the project virtual environment:

```bash
.venv/bin/python -m pip install --upgrade "beatbot-cloud==0.4.1"
.venv/bin/pytest
```

The test suite covers config flow setup, duplicate-account prevention, OAuth error handling, API response handling, coordinator behavior, and entity setup.
