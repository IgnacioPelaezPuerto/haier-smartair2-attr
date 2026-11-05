"""Sensores del aparato: temperatura de sala, exterior y humedad."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTR_OUTDOOR_TEMP, ATTR_ROOM_HUMIDITY, ATTR_ROOM_TEMP, DOMAIN
from .coordinator import HaierCoordinator


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: HaierCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([
        HaierTemperatureSensor(coord, ATTR_ROOM_TEMP, "current_temperature",
                               "Temp. interior", SensorDeviceClass.TEMPERATURE),
        HaierTemperatureSensor(coord, ATTR_OUTDOOR_TEMP, "outdoor_temperature",
                               "Temp. exterior", SensorDeviceClass.TEMPERATURE),
        HaierTemperatureSensor(coord, ATTR_ROOM_HUMIDITY, "humidity",
                               "Humedad interior", SensorDeviceClass.HUMIDITY),
    ], True)


class HaierSensor(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coord: HaierCoordinator, attr: str, key: str, name: str) -> None:
        super().__init__(coord)
        self._attr = attr
        self._attr_unique_id = f"{DOMAIN}-{coord.api.device_id}-{key}"
        self._attr_name = name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coord.api.device_id)},
        }

    @property
    def available(self) -> bool:
        return self.coordinator.available and bool(self.coordinator.data)

    @property
    def native_value(self):
        return _num((self.coordinator.data or {}).get(self._attr))


class HaierTemperatureSensor(HaierSensor, SensorEntity):
    def __init__(self, coord, attr, key, name, device_class) -> None:
        super().__init__(coord, attr, key, name)
        self._attr_device_class = device_class
        self._attr_state_class = SensorStateClass.MEASUREMENT
        if device_class == SensorDeviceClass.HUMIDITY:
            self._attr_native_unit_of_measurement = PERCENTAGE
        else:
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
