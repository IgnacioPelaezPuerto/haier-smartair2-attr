"""Cliente de la nube de Haier (SmartAir2 / overseas) por API de atributos.

Codigo sincrono: Home Assistant lo llama dentro de un executor
(`hass.async_add_executor_job`) para no bloquear el bucle principal.

Flujo completo, verificado contra un split real observando la app SmartAir2
con `adb logcat` (el SDK de Haier registra cada publicacion MQTT con topico y
payload literal):

  1. POST /uhome/acbiz/login                -> accessToken
  2. POST /uhome/acbiz/device/v25/...        -> lista de aparatos
  3. TLS a gw-gea-*.haieriot.net:56815       -> {"port": 56790, "host": ...}
  4. MQTT 3.1 CONNECT a host:port, usuario "01<nonce>" y password AES(sal)
  5. Publicar boundDevs en Client/<clientId>/Business/Up  (autoriza el aparato)
  6. Leer   User/<token>/Req/Op/<devId>   {"sn":"..","op":"getAllProperty","args":[]}
     Escribir User/<token>/Req/Op/<devId>  {"sn":"..","op":"grSetDAC","args":[grupo]}
     Respuesta User/<token>/Resp/Op/<devId> {"sn":"..","errNo":0,"args":[...]}
     Empuje   User/<token>/Push/Dev/Attr/<devId> {"attrs":[...]}

Nota importante: escribir un atributo suelto con `Req/Attr/W/<devId>` solo
funciona para booleanos (onOffStatus).  Para temperatura o velocidad el aparato
exige `grSetDAC` con el grupo completo de atributos escribibles.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import socket
import ssl
import struct
import threading
import time
import urllib.error
import urllib.request

from .const import (
    APP_ID,
    APP_KEY,
    APP_VERSION,
    AUTH_SALT,
    LOGIN_HOST,
    LOGIN_PORT,
    MASTER_GW_PORT,
    OP_READ,
    OP_WRITE,
    PATH_DEVLIST,
    PATH_LOGIN,
    REGIONS,
    RESPONSE_TIMEOUT,
    REST_CLIENT_ID,
    TOPIC_BUSINESS_DOWN,
    TOPIC_BUSINESS_UP,
    TOPIC_PUSH_ATTR,
    TOPIC_REQ_OP,
    TOPIC_RESP_OP,
    WRITABLE_ATTRS,
    NUMERIC_ATTRS,
)


class HaierCloudError(Exception):
    """Fallo de comunicacion con la nube de Haier."""


def _insecure_ctx() -> ssl.SSLContext:
    # El certificado de Haier no valida contra su nombre en algunos bordes; la
    # app tampoco valida (el SDK trae su propio bundle).  Se mantiene igual.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _flatten(args: list) -> dict:
    """[{'onOffStatus':'true'}, ...] -> {'onOffStatus': 'true', ...}"""
    out: dict[str, str] = {}
    for item in args or []:
        if isinstance(item, dict):
            for key, value in item.items():
                out[key.strip("'")] = value
    return out


def _fmt(name: str, value) -> str:
    """Haier manda todo como texto; los numericos sin ceros sobrantes."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if name in NUMERIC_ATTRS:
        try:
            num = float(value)
            return str(int(num)) if num == int(num) else f"{num:g}"
        except (TypeError, ValueError):
            return str(value)
    return str(value)


class HaierCloudApi:
    """Una sesion MQTT persistente contra la nube europea/us/sg de Haier."""

    def __init__(
        self,
        email: str,
        password: str,
        region: str = "eu",
        logger: logging.Logger | None = None,
    ) -> None:
        self._email = email
        self._password = password
        self._region = region if region in REGIONS else "eu"
        self._log = logger or logging.getLogger(__name__)

        self._token: str | None = None
        self._app_client_id = secrets.token_hex(16)
        self._client = None                 # paho.mqtt.client.Client
        self._stopping = False
        self._connected = threading.Event()
        self._lock = threading.Lock()
        self._pending: dict[str, threading.Event] = {}
        self._last_resp: dict | None = None

        self.device_id: str | None = None
        self.device_name: str | None = None
        self.state: dict[str, str] = {}
        # puesto por el coordinador para avisar de que llego estado nuevo
        self.on_state_updated = None        # callable() -> None
        self.on_auth_lost = None            # callable() -> None

    # --------------------------------------------------------------- REST

    def _post(self, path: str, body: dict, token: str | None = None) -> dict:
        headers = {
            "appKey": APP_KEY,
            "appId": APP_ID,
            "appVersion": APP_VERSION,
            "clientId": REST_CLIENT_ID,
            "Content-Type": "application/json;charset=utf-8",
            "Accept": "application/json",
        }
        if token:
            headers["accessToken"] = token
        req = urllib.request.Request(
            f"https://{LOGIN_HOST}:{LOGIN_PORT}{path}",
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=25, context=_insecure_ctx()) as resp:
            return json.loads(resp.read().decode())

    def login(self) -> str:
        data = self._post(PATH_LOGIN, {
            "loginId": self._email,
            "password": self._password,
            "accType": 0,
            "loginType": 2,
            "sequenceId": time.strftime("%Y%m%d%H%M%S") + "0000000",
        })
        token = data.get("accessToken")
        if not token:
            raise HaierCloudError(
                f"login rechazado (retCode={data.get('retCode')} {data.get('retInfo')})"
            )
        self._token = token
        return token

    def list_devices(self) -> list[dict]:
        if not self._token:
            self.login()
        data = self._post(PATH_DEVLIST, {
            "get_devlist_info": {"sctx": {"appId": APP_ID, "appVersion": APP_VERSION,
                                          "clientId": REST_CLIENT_ID}}
        }, self._token)
        devs: list[dict] = []
        for city in data.get("cityListResult") or []:
            for room in city.get("roomDeviceResultList") or []:
                devs.extend(room.get("deviceList") or [])
        return devs

    # ------------------------------------------------------------ master-gw

    def _mqtt_endpoint(self) -> tuple[str, int]:
        gateway = REGIONS[self._region]
        body = json.dumps({
            "protocolVers": "1.0.0",
            "clientId": self._app_client_id,
            "connType": "MqttUSdk",
            "svcVers": "0.0.0",
            "libVers": "0.0.0",
            "userAGpType": "UCP-MQTT-UACP",
            "userAGpVers": "1.2.0",
        }).encode()
        header = bytearray(8)
        header[1] = 1
        struct.pack_into(">H", header, 2, 1)
        struct.pack_into(">H", header, 6, len(body))
        with socket.create_connection((gateway, MASTER_GW_PORT), timeout=15) as sock:
            with _insecure_ctx().wrap_socket(sock, server_hostname=gateway) as tls:
                tls.sendall(bytes(header) + body)
                buf = b""
                while len(buf) < 8:
                    chunk = tls.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                if len(buf) < 8:
                    raise HaierCloudError("master-gw cerro la conexion")
                length = struct.unpack(">H", buf[6:8])[0]
                while len(buf) < 8 + length:
                    chunk = tls.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
        info = json.loads(buf[8:8 + length])
        if info.get("errNo"):
            raise HaierCloudError(f"master-gw errNo={info.get('errNo')}")
        return info.get("host") or gateway, int(info["port"])

    # ---------------------------------------------------------------- MQTT

    def _mqtt_credentials(self) -> tuple[str, str]:
        """usuario '01<nonce>' y password = AES-128-CBC(sal) con clave MD5(nonce)."""
        nonce = ""
        while len(nonce) < 8:
            nonce += str(os.urandom(1)[0])
        nonce = nonce[:8]
        key = hashlib.md5(nonce.encode()).digest()
        plain = bytearray(16)
        struct.pack_into(">H", plain, 0, len(AUTH_SALT))
        plain[2:2 + len(AUTH_SALT)] = AUTH_SALT
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        enc = Cipher(algorithms.AES(key), modes.CBC(b"\x00" * 16)).encryptor()
        cipher = enc.update(bytes(plain)) + enc.finalize()
        return "01" + nonce, cipher.hex()

    def _on_connect(self, client, _userdata, _flags, reason_code, _props=None) -> None:
        if getattr(reason_code, "value", reason_code) != 0:
            self._log.warning("Haier MQTT CONNACK=%s", reason_code)
            return
        topics = [
            TOPIC_BUSINESS_DOWN.format(client=self._app_client_id),
            f"User/{self._token}/{TOPIC_RESP_OP}",
            f"User/{self._token}/{TOPIC_PUSH_ATTR}",
        ]
        for topic in topics:
            client.subscribe([(topic, 0)])
        # autoriza la lista de aparatos de este usuario en esta conexion
        payload = base64.b64encode(json.dumps({"sn": "101"}).encode()).decode()
        client.publish(
            TOPIC_BUSINESS_UP.format(client=self._app_client_id),
            json.dumps({"type": "boundDevs", "data": payload, "tokens": [self._token]}),
        )
        self._connected.set()

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            packet = json.loads(message.payload)
        except (ValueError, TypeError):
            return
        if packet.get("event"):
            event = packet["event"]
            if event in ("invalidToken", "tokenExpired") and self.on_auth_lost:
                self._log.warning("Haier: sesion de usuario %s", event)
                self._token = None
                self.on_auth_lost()
            return

        sn = str(packet.get("sn") or "")
        if "attrs" in packet:                       # Push/Dev/Attr
            self.state.update(_flatten(packet["attrs"]))
            if self.on_state_updated:
                self.on_state_updated()
            return

        # Resp/Op: puede traer errNo y, en el caso de lectura, el estado
        if "args" in packet:
            self.state.update(_flatten(packet["args"]))
            if self.on_state_updated:
                self.on_state_updated()
        if "errNo" in packet:
            self._last_resp = packet
            waiter = self._pending.pop(sn, None)
            if waiter:
                waiter.set()

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _props=None) -> None:
        if not self._stopping:
            self._log.info("Haier MQTT desconectado (%s); paho reintenta", reason_code)

    # ------------------------------------------------------------ ciclo de vida

    def start(self) -> None:
        """Login + descubrimiento de aparato + conexion MQTT."""
        import paho.mqtt.client as mqtt  # import tardio: HA no lo carga si no hay config

        if not self._token:
            self.login()
        if not self.device_id:
            devs = self.list_devices()
            if not devs:
                raise HaierCloudError("la cuenta de Haier no tiene aparatos")
            self.device_id = str(devs[0]["id"]).upper()
            self.device_name = devs[0].get("name") or self.device_id

        host, port = self._mqtt_endpoint()
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="HA" + secrets.token_hex(8).upper(),
            protocol=mqtt.MQTTv31,
        )
        client.username_pw_set(*self._mqtt_credentials())
        client.tls_set_context(_insecure_ctx())
        client.on_connect = self._on_connect
        client.on_message = self._on_message
        client.on_disconnect = self._on_disconnect
        self._stopping = False
        self._connected.clear()
        client.connect(host, port, 30)
        client.loop_start()
        self._client = client
        # esperar CONNACK + suscripciones (el boundDevs va en el mismo callback)
        if not self._connected.wait(20):
            self.stop()
            raise HaierCloudError("la nube de Haier no acepto la conexion MQTT")

    def stop(self) -> None:
        self._stopping = True
        self._connected.clear()
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:  # noqa: BLE001 - apagar nunca debe explotar
                pass
            self._client = None

    # --------------------------------------------------------------- operaciones

    @property
    def session_lost(self) -> bool:
        """True cuando la nube nos robo la sesion (otro dispositivo entro)."""
        return self._token is None

    def _ensure_session(self) -> None:
        """Vuelve a hacer login si la nube invalido el token (otro dispositivo).

        Haier mantiene una sola sesion por usuario: si alguien inicia sesion
        desde el movil, nuestro token muere y deja de llegar estado.  Nos
        reconectamos solos, con lo que el movil queda fuera hasta que lo abras.
        """
        if self._token and self._client:
            return
        if not self._client:
            raise HaierCloudError("sin conexion MQTT (llama a start() primero)")
        self._log.info("Haier: renegando la sesion de usuario")
        self.login()
        self._connected.clear()
        self._on_connect(self._client, None, None, 0)
        if not self._connected.wait(10):
            raise HaierCloudError("no se pudo re-suscribir a los topicos de Haier")
        time.sleep(0.5)   # la nube necesita un momento para registrar la suscripcion

    def _request(self, op: str, args: list) -> dict:
        self._ensure_session()
        if not self._client:
            raise HaierCloudError("sin conexion MQTT")
        sn = str(int(time.time()) % 100000 + secrets.randbelow(1000))
        event = threading.Event()
        self._pending[sn] = event
        self._last_resp = None
        self._client.publish(
            f"User/{self._token}/{TOPIC_REQ_OP.format(devid=self.device_id)}",
            json.dumps({"sn": sn, "op": op, "args": args}),
        )
        if not event.wait(RESPONSE_TIMEOUT):
            self._pending.pop(sn, None)
            raise HaierCloudError(f"{op}: el aparato no respondio en {RESPONSE_TIMEOUT:.0f} s")
        resp = self._last_resp or {}
        if resp.get("errNo"):
            raise HaierCloudError(f"{op}: errNo={resp.get('errNo')}")
        return resp

    def read_all(self) -> dict:
        """Pide el estado completo (getAllProperty)."""
        self._request(OP_READ, [])
        return self.state

    def write_group(self, changes: dict) -> dict:
        """Escribe cambios con grSetDAC y el grupo completo de atributos.

        Se reenvian todos los atributos escribibles con su valor actual salvo los
        que `changes` modifique: es exactamente lo que hace la app.
        """
        if not self.state:
            self.read_all()
        if not self.state:
            raise HaierCloudError("no hay estado base para reconstruir el grupo")
        args = []
        for name in WRITABLE_ATTRS:
            value = changes.get(name, self.state.get(name))
            if value is None:
                continue
            args.append({name: _fmt(name, value)})
        for name, value in changes.items():          # extras no listados arriba
            if name not in WRITABLE_ATTRS and name in self.state:
                args.append({name: _fmt(name, value)})
        return self._request(OP_WRITE, args)
