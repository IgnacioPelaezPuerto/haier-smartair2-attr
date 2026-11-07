"""Entidad climate nativa para un split Haier controlado por la nube."""
from __future__ import annotations

import logging

from homeassistant.components.climate import (
    PRESET_BOOST,
    PRESET_SLEEP,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_ELEC_HEAT,
    ATTR_FAN_SPEED,
    ATTR_HEALTH,
    ATTR_MODE,
    ATTR_ON_OFF,
    ATTR_RAPID,
    ATTR_ROOM_TEMP,
    ATTR_SILENT,
    ATTR_TARGET_TEMP,
    ATTR_VERT_SWING,
    DOMAIN,
)
from .coordinator import HaierCoordinator

_LOGGER = logging.getLogger(__name__)

# operationMode -> HVACMode  (tabla confirmada con el log del SDK y HaierACBridge)
MODE_TO_HVAC = {
    "0": HVACMode.AUTO,
    "1": HVACMode.COOL,
    "2": HVACMode.DRY,
    "4": HVACMode.HEAT,
    "6": HVACMode.FAN_ONLY,
}
HVAC_TO_MODE = {value: key for key, value in MODE_TO_HVAC.items()}

# windSpeed -> modo de ventilador
SPEED_TO_FAN = {"0": "quiet", "1": "high", "2": "medium", "3": "low", "5": "auto"}
FAN_TO_SPEED = {value: key for key, value in SPEED_TO_FAN.items()}

PRESETS = {PRESET_BOOST: ATTR_RAPID, PRESET_SLEEP: ATTR_SILENT}


def _truthy(value) -> bool:
    return str(value).strip().lower() == "true"


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def async_setup_entry(
    hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback
) -> None:
    coord: HaierCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([HaierCloudClimate(coord, entry)], True)


class HaierCloudClimate(CoordinatorEntity, ClimateEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = 16.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 1.0
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.AUTO, HVACMode.COOL,
                        HVACMode.DRY, HVACMode.HEAT, HVACMode.FAN_ONLY]
    _attr_fan_modes = list(FAN_TO_SPEED)
    _attr_preset_modes = list(PRESETS)
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )

    def __init__(self, coord: HaierCoordinator, entry) -> None:
        super().__init__(coord)
        self._entry = entry
        self._attr_unique_id = f"{DOMAIN}-{coord.api.device_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coord.api.device_id)},
            "name": coord.api.device_name or "Aire Acondicionado",
            "manufacturer": "Haier",
            "model": f"SmartAir2 (nube, EPP {coord.api.device_protocol or '?'})",
            "serial_number": coord.api.device_id,
        }

    # ------------------------------------------------------------------ estado

    @property
    def available(self) -> bool:
        return self.coordinator.available and bool(self.coordinator.data)

    @property
    def hvac_mode(self) -> HVACMode:
        data = self.coordinator.data or {}
        if not _truthy(data.get(ATTR_ON_OFF)):
            return HVACMode.OFF
        return MODE_TO_HVAC.get(str(data.get(ATTR_MODE)), HVACMode.AUTO)

    @property
    def native_target_temperature(self) -> float | None:
        return _num((self.coordinator.data or {}).get(ATTR_TARGET_TEMP))

    @property
    def native_current_temperature(self) -> float | None:
        return _num((self.coordinator.data or {}).get(ATTR_ROOM_TEMP))

    @property
    def fan_mode(self) -> str | None:
        raw = str((self.coordinator.data or {}).get(ATTR_FAN_SPEED))
        return SPEED_TO_FAN.get(raw)

    @property
    def preset_mode(self) -> str | None:
        data = self.coordinator.data or {}
        for preset, attr in PRESETS.items():
            if _truthy(data.get(attr)):
                return preset
        return None

    # ------------------------------------------------------------------- acciones

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        changes: dict = {}
        if hvac_mode == HVACMode.OFF:
            changes[ATTR_ON_OFF] = "false"
        else:
            changes[ATTR_ON_OFF] = "true"
            changes[ATTR_MODE] = HVAC_TO_MODE.get(hvac_mode, "0")
        await self.coordinator.async_write(changes)

    async def async_set_temperature(self, **kwargs) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        await self.coordinator.async_write({ATTR_TARGET_TEMP: temp})

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in FAN_TO_SPEED:
            _LOGGER.warning("modo de ventilador desconocido: %s", fan_mode)
            return
        await self.coordinator.async_write({ATTR_FAN_SPEED: FAN_TO_SPEED[fan_mode]})

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        attr = PRESETS.get(preset_mode)
        if not attr:
            return
        changes = {other: "false" for other in PRESETS.values() if other != attr}
        changes[attr] = "true"
        await self.coordinator.async_write(changes)

    # utilidades que la tarjeta de HA usa para mostrar extras
    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "health_mode": _truthy(data.get(ATTR_HEALTH)),
            "electric_heating": _truthy(data.get(ATTR_ELEC_HEAT)),
            "vertical_swing": data.get(ATTR_VERT_SWING),
            "haier_err_code": data.get("errCode") or None,
        }
