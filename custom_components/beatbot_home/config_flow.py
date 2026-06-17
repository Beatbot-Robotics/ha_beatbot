import voluptuous as vol
from homeassistant import config_entries
from iot.const import DOMAIN


class BeatbotConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="Beatbot Home", data={})

        return self.async_show_form(step_id="user")


class BeatbotOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        return self.async_show_form(step_id="init")
