"""Coordinador: mantiene una sesion de nube y un estado compartido."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    HomeAssistantError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HaierCloudApi, HaierCloudError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class HaierCoordinator(DataUpdateCoordinator):
    """Una sola conexion de nube para todos los aparatos de la cuenta."""

    def __init__(self, hass: HomeAssistant, api: HaierCloudApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_method=self._async_update,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.available = False
        # el API vive en el hilo de paho: le colgamos un puente al bucle de HA
        self.api.on_state_updated = self._on_push
        self.api.on_auth_lost = lambda: self.hass.loop.call_soon_threadsafe(
            self._mark_unavailable
        )

    # ---------------------------------------------------------------- push

    def _on_push(self) -> None:
        """Llamado desde el hilo de MQTT cuando el aparato empuja estado."""
        try:
            self.hass.loop.call_soon_threadsafe(self._apply_push)
        except RuntimeError:
            pass  # hass cerrando

    def _apply_push(self) -> None:
        self.data = dict(self.api.state)
        self.available = True
        self.async_set_updated_data(dict(self.data))

    def _mark_unavailable(self) -> None:
        self.available = False
        self.async_set_updated_data(self.data)

    # --------------------------------------------------------------- update

    async def _async_update(self) -> dict:
        try:
            state = await self.hass.async_add_executor_job(self.api.read_all)
        except HaierCloudError as err:
            self.available = False
            if "login" in str(err).lower():
                # las credenciales guardadas ya no valen: HA pide reautenticar
                raise ConfigEntryAuthFailed(str(err)) from err
            raise UpdateFailed(str(err)) from err
        except Exception as err:  # noqa: BLE001 - paho/ssl pueden tirar de todo
            self.available = False
            raise UpdateFailed(f"error de nube: {err}") from err
        if not state:
            raise UpdateFailed("la nube devolvio un estado vacio")
        self.available = True
        return dict(state)

    # --------------------------------------------------------------- escritura

    async def async_write(self, changes: dict) -> None:
        """Envia cambios al aparato y refresca enseguida."""
        if not changes:
            return
        try:
            await self.hass.async_add_executor_job(self.api.write_group, changes)
        except HaierCloudError as err:
            raise HomeAssistantError(str(err)) from err
        # el aparato empuja el estado nuevo en ~2 s; aun asi pedimos uno
        await asyncio.sleep(0.8)
        await self.async_request_refresh()
