"""Integracion Haier SmartAir2 (API de atributos) para Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import HaierCloudApi, HaierCloudError, HaierDeviceOffline
from .const import CONF_DEVICE_ID, CONF_DEVICE_NAME, CONF_REGION, DOMAIN, PLATFORMS
from .coordinator import HaierCoordinator

_LOGGER = logging.getLogger(__name__)

type HaierConfigEntry = ConfigEntry[HaierCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HaierConfigEntry) -> bool:
    """Arranca la sesion de nube y monta las plataformas."""
    api = HaierCloudApi(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
        region=entry.data.get(CONF_REGION, "eu"),
        logger=_LOGGER,
    )
    # el config flow ya eligio que aparato de la cuenta controlamos
    api.device_id = entry.data.get(CONF_DEVICE_ID)
    api.device_name = entry.data.get(CONF_DEVICE_NAME)
    coordinator = HaierCoordinator(hass, api)

    try:
        # login + master-gw + MQTT (el aparato aun no hace falta)
        await hass.async_add_executor_job(api.start)
    except HaierCloudError as err:
        api.stop()
        text = str(err).lower()
        if "login" in text or "token" in text:
            raise ConfigEntryAuthFailed(str(err)) from err
        raise ConfigEntryNotReady(str(err)) from err
    except Exception as err:  # noqa: BLE001 - paho/ssl/urllib lanzan de todo
        api.stop()
        raise ConfigEntryNotReady(f"no se pudo hablar con la nube de Haier: {err}") from err

    try:
        await hass.async_add_executor_job(api.read_all)
    except HaierDeviceOffline as err:
        # La sesion de nube es buena, solo falta el split.  Montamos igualmente
        # para que el usuario vea el aparato y el sensor de conectividad: si
        # abortasemos aqui, Home Assistant no crearia entidades y la
        # integracion pareceria muerta aunque funcione.
        _LOGGER.warning("Haier: el aparato esta sin red al arrancar (%s); las "
                        "entidades se llenaran cuando vuelva", err)
    except HaierCloudError as err:
        api.stop()
        raise ConfigEntryNotReady(str(err)) from err

    coordinator.data = dict(api.state)
    coordinator.available = True
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HaierConfigEntry) -> bool:
    """Cierra la sesion de nube al quitar la entrada."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        bundle = hass.data[DOMAIN].pop(entry.entry_id, None)
        if bundle:
            await hass.async_add_executor_job(bundle["api"].stop)
    return unloaded
