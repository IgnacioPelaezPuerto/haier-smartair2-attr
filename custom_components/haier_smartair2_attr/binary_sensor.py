"""Sensor de conectividad: si el split esta vivo en la nube de Haier.

Sirve para separar de un vistazo un problema del aparato (no tiene WiFi o esta
bajado el magnetotermico) de un problema de Home Assistant.  Mientras este
sensor este en "On", la integracion puede mandar ordenes.
"""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HaierCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: HaierCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([HaierConnectivitySensor(coord)], True)


class HaierConnectivitySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coord: HaierCoordinator) -> None:
        super().__init__(coord)
        self._attr_unique_id = f"{DOMAIN}-{coord.api.device_id}-connectivity"
        self._attr_name = "En linea"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coord.api.device_id)},
        }

    @property
    def available(self) -> bool:
        # la conectividad se reporta siempre: si no hay datos, el valor malo es
        # precisamente el que interesa
        return True

    @property
    def is_on(self) -> bool:
        online = self.coordinator.api.device_online
        if online is None:
            return bool(self.coordinator.available)
        return bool(online)

    @property
    def extra_state_attributes(self) -> dict:
        return {"host": "nube Haier"}
