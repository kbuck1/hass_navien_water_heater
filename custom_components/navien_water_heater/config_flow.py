"""Config flow for Navien Water Heater integration."""
from __future__ import annotations
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from .const import DOMAIN
from .navien_api import NavilinkAccountCoordinator

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,       
    }
)

STEP_SET_POLLING_INTERVAL = vol.Schema(
    {
        vol.Required("polling_interval", default=15): vol.All(vol.Coerce(int), vol.Range(min=10, max=120))
    }
)


class NavienConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NaviLink."""

    VERSION = 2

    def __init__(self):
        self.username = ''
        self.password = ''
        self.polling_interval = 15

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle user and password for NaviLink account."""
        if user_input is None:
            return self.async_show_form(
                step_id="user", data_schema=STEP_USER_DATA_SCHEMA
            )

        errors = {}

        try:
            # Use NavilinkAccountCoordinator for validation (accepts userId and passwd)
            coordinator = NavilinkAccountCoordinator(
                userId=user_input['username'],
                passwd=user_input['password'],
                polling_interval=0  # 0 means just login, don't start polling
            )
            device_list = await coordinator.login()
            if not device_list:
                errors["base"] = "no_devices"
        except Exception:  # pylint: disable=broad-except
            errors["base"] = "invalid_auth"
        else:
            if not errors:
                self.username = user_input['username']
                self.password = user_input['password']
                return await self.async_step_set_polling_interval()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_set_polling_interval(
        self, user_input=None
    ) -> FlowResult:
        """Handle polling interval for this account."""
        if user_input is None:
            return self.async_show_form(
                step_id="set_polling_interval", data_schema=STEP_SET_POLLING_INTERVAL
            )

        # Use username as unique identifier for the account
        unique_id = f'navien_{self.username}'
        await self.async_set_unique_id(unique_id)
        
        # Check if entry with this unique_id already exists
        existing_entry = self._async_current_entries()
        for entry in existing_entry:
            if entry.unique_id == unique_id:
                # Update existing entry
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        "username": self.username,
                        "password": self.password,
                        "polling_interval": user_input["polling_interval"]
                    }
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
        
        # Create new entry
        return self.async_create_entry(
            title=unique_id,
            data={
                "username": self.username,
                "password": self.password,
                "polling_interval": user_input["polling_interval"]
            }
        )
