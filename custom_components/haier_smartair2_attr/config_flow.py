"""Flujo de configuracion: correo, contrasena y region de la cuenta Haier."""
from __future__ import annotations

import logging
import re

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)

from .api import HaierCloudApi, HaierCloudError
from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, CONF_REGION, DOMAIN

_LOGGER = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class HaierConfigFlow(ConfigFlow, domain=DOMAIN):
    """Alta de la cuenta Haier en Home Assistant."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}
        self._devices: list[dict] = []

    # ------------------------------------------------------------- paso 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Pide credenciales y comprueba que la cuenta existe."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            password = user_input[CONF_PASSWORD]
            region = user_input[CONF_REGION]

            api = HaierCloudApi(email, password, region, _LOGGER)
            try:
                devices = await self.hass.async_add_executor_job(self._connect, api)
            except HaierCloudError as err:
                _LOGGER.warning("Haier: %s", err)
                errors["base"] = "invalid_auth" if "login" in str(err) else "cannot_connect"
            except Exception:  # noqa: BLE001 - muestre el error, no reviente el flujo
                _LOGGER.exception("Haier: fallo inesperado al conectar")
                errors["base"] = "unknown"
            else:
                if not devices:
                    return self.abort(reason="no_devices", description_placeholders={})
                await self.async_set_unique_id(str(devices[0]["id"]).upper())
                self._abort_if_unique_id_configured()
                self._data = {
                    CONF_EMAIL: email,
                    CONF_PASSWORD: password,
                    CONF_REGION: region,
                }
                self._devices = devices
                if len(devices) == 1:
                    return self._create(devices[0])
                return await self.async_step_device()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL): TextSelector(
                    {"type": "email", "autocomplete": "off"}
                ),
                vol.Required(CONF_PASSWORD): TextSelector(
                    {"type": "password", "autocomplete": "off"}
                ),
                vol.Required(CONF_REGION, default="eu"): SelectSelector(
                    SelectSelectorConfig(options=[
                        SelectOptionDict(value="eu", label="Europa"),
                        SelectOptionDict(value="us", label="Estados Unidos"),
                        SelectOptionDict(value="sg", label="Asia / Pacifico"),
                    ])
                ),
            }),
            errors=errors,
        )

    # ------------------------------------------------------------- paso 2

    async def async_step_device(self, user_input=None) -> ConfigFlowResult:
        """Elige aparato cuando la cuenta tiene mas de uno."""
        errors: dict[str, str] = {}
        options = [
            SelectOptionDict(
                value=str(dev["id"]).upper(),
                label="{name}{sala}{apagado}".format(
                    name=str(dev.get("name") or dev["id"]),
                    sala=f"  ·  {dev['room']}" if dev.get("room") else "",
                    apagado="" if dev.get("online") else "  (apagado)",
                ),
            )
            for dev in self._devices
        ]

        if user_input is not None:
            dev_id = user_input[CONF_DEVICE_ID].upper()
            chosen = next((d for d in self._devices
                           if str(d["id"]).upper() == dev_id), None)
            if chosen is None:
                errors[CONF_DEVICE_ID] = "device_not_found"
            else:
                await self.async_set_unique_id(dev_id)
                self._abort_if_unique_id_configured()
                return self._create(chosen)

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema({
                vol.Required(CONF_DEVICE_ID): SelectSelector(
                    SelectSelectorConfig(options=options)
                ),
            }),
            errors=errors,
        )

    # -------------------------------------------------------------- helpers

    def _connect(self, api: HaierCloudApi) -> list[dict]:
        """Login y lista de aparatos (bloqueante, se ejecuta en executor)."""
        api.login()
        return api.list_devices()

    def _create(self, device: dict) -> ConfigFlowResult:
        dev_id = str(device["id"]).upper()
        return self.async_create_entry(
            title=str(device.get("name") or "Aire Acondicionado Haier"),
            data={
                **self._data,
                CONF_DEVICE_ID: dev_id,
                CONF_DEVICE_NAME: str(device.get("name") or dev_id),
            },
        )
