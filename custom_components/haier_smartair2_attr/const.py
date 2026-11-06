"""Constantes compartidas del componente Haier SmartAir2 (API de atributos)."""
from __future__ import annotations

DOMAIN = "haier_smartair2_attr"
PLATFORMS = ["binary_sensor", "climate", "sensor"]

CONF_REGION = "region"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"

# --- endpoints de la nube de Haier (los mismos que usa la app SmartAir2) ---
LOGIN_HOST = "uhome.haieriot.net"
LOGIN_PORT = 7263
MASTER_GW_PORT = 56815
PATH_LOGIN = "/uhome/acbiz/login"
PATH_DEVLIST = "/uhome/acbiz/device/v25/get_userDevlist"

APP_KEY = "c403cbfc780dd8a0ab68784bb6d3023b"
APP_ID = "MB-HKQHWBB-0001"
APP_VERSION = "3.2.1"
REST_CLIENT_ID = "4BC6E2ADBF06AD33FA18AC1190F3DED9"
AUTH_SALT = b"haier_sdk"

REGIONS = {
    "eu": "gw-gea-euro.haieriot.net",
    "us": "gw-gea-us.haieriot.net",
    "sg": "gw-gea-sg.haieriot.net",
}

# --- topicos MQTT observados en el log de la app (etiqueta NetworkLog/CAE) ---
#   Req/Op   -> peticion de operacion (getAllProperty, grSetDAC)
#   Resp/Op  -> respuesta a esa operacion, con errNo y el estado resultante
#   Push/Dev/Attr -> el aparato empuja su estado cuando algo cambia
TOPIC_REQ_OP = "Req/Op/{devid}"
TOPIC_RESP_OP = "Resp/Op/#"
TOPIC_PUSH_ATTR = "Push/Dev/Attr/#"
TOPIC_BUSINESS_UP = "Client/{client}/Business/Up"
TOPIC_BUSINESS_DOWN = "Client/{client}/Business/Down"

OP_READ = "getAllProperty"
OP_WRITE = "grSetDAC"

# --- atributos ---
ATTR_ON_OFF = "onOffStatus"
ATTR_MODE = "operationMode"
ATTR_TARGET_TEMP = "targetTemperature"
ATTR_FAN_SPEED = "windSpeed"
ATTR_ROOM_TEMP = "indoorTemperature"
ATTR_OUTDOOR_TEMP = "outdoorTemperature"
ATTR_ROOM_HUMIDITY = "indoorHumidity"
ATTR_VERT_SWING = "windDirectionVertical"
ATTR_HORIZ_SWING = "windDirectionHorizontal"
ATTR_RAPID = "rapidMode"
ATTR_SILENT = "silentSleepStatus"
ATTR_HEALTH = "healthMode"
ATTR_ELEC_HEAT = "electricHeatingStatus"
ATTR_ERR = "errCode"

# Orden observado en el payload grSetDAC de la app.  Es importante respetar la
# lista COMPLETA: si se manda solo el atributo que cambia, el aparato pone el
# resto a sus valores por defecto.
WRITABLE_ATTRS: tuple[str, ...] = (
    ATTR_TARGET_TEMP, ATTR_VERT_SWING, ATTR_MODE, "specialMode", ATTR_FAN_SPEED,
    "energySavePeriod", "tempUnit", "pmvStatus", "intelligenceStatus",
    "halfDegreeSettingStatus", "screenDisplayStatus", "10degreeHeatingStatus",
    "echoStatus", "lockStatus", ATTR_SILENT, "muteStatus", ATTR_RAPID,
    ATTR_ELEC_HEAT, ATTR_HEALTH, ATTR_ON_OFF, "targetHumidity",
    "humanSensingStatus", ATTR_HORIZ_SWING, "cloudFilterChangeFlag",
    "cleaningTimeStatus", "energySavingStatus", "lightStatus", "selfCleaningStatus",
    "ch2oCleaningStatus", "pm2p5CleaningStatus", "humidificationStatus",
    "freshAirStatus",
)

# Atributos que la app manda como numero entero ("24", no "24.00")
NUMERIC_ATTRS: frozenset[str] = frozenset(
    {ATTR_TARGET_TEMP, "targetHumidity", "energySavePeriod", ATTR_FAN_SPEED,
     ATTR_MODE, "specialMode", "tempUnit", ATTR_VERT_SWING, ATTR_HORIZ_SWING,
     "humanSensingStatus"}
)

# --- temporizacion ---
DEFAULT_SCAN_INTERVAL = 60          # refresco periodico de estado
TOKEN_REFRESH = 12 * 3600           # el token de Haier aguanta mucho; re-negar solo si falla
RESPONSE_TIMEOUT = 15.0             # espera maxima por Resp/Op

# --- codigos errNo observados en la nube de Haier ---
# Los traducimos porque son lo unico que ve el usuario cuando algo va mal, y
# "errNo=16" no dice nada.  Solo traduco los que hemos visto confirmados por la
# propia lista de aparatos (16 coincide con online=False); el resto se pasa tal
# cual para no inventar significados.
ERRNO_DEVICE_OFFLINE = 16
ERRNO_LABELS: dict[int, str] = {
    ERRNO_DEVICE_OFFLINE: "el split esta desconectado de la nube de Haier "
                          "(revisa alimentacion y WiFi del aparato)",
}


def errno_message(op: str, err_no) -> str:
    """Frase legible para un errNo de la nube."""
    try:
        code = int(err_no)
    except (TypeError, ValueError):
        code = -1
    label = ERRNO_LABELS.get(code, f"la nube de Haier rechazo la orden (errNo={err_no})")
    return f"{op}: {label}"

