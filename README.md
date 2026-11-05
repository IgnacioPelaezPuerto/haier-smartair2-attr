# Haier SmartAir2 (Attribute API)

Control de un aire acondicionado Haier desde Home Assistant usando **la misma API
de atributos que usa la app SmartAir2 / Smart Clima**, no el protocolo EPP que
usan otras integraciones.

Esto es lo que permite funcionar con splits (por ejemplo los de la familia
`AcDeviceV218SNew`, protocolo 2.18) que **no responden** nunca a la petición de
estado por túnel `User/<token>/Ext/Req/<devId>`, y que por tanto aparecen en
Home Assistant como una entidad muerta ("Auto", temperatura `None`).

## Cómo funciona

La integración abre **una sola sesión** contra la nube de Haier y la mantiene
viva:

1. `POST https://uhome.haieriot.net:7263/uhome/acbiz/login` → `accessToken`
2. `POST .../uhome/acbiz/device/v25/get_userDevlist` → aparatos de la cuenta
3. TLS a `gw-gea-euro.haieriot.net:56815` (`master-gw`) → host y puerto MQTT
4. MQTT 3.1 sobre TLS + autenticación AES → suscripción a los tópicos de usuario
5. Estado y control por tópicos de atributos:

| Acción | Tópico | Payload |
|---|---|---|
| Leer | `User/<token>/Req/Op/<devId>` | `{"sn":"144","op":"getAllProperty","args":[]}` |
| Escribir | `User/<token>/Req/Op/<devId>` | `{"sn":"221","op":"grSetDAC","args":[…grupo completo…]}` |
| Respuesta | `User/<token>/Resp/Op/<devId>` | `{"sn":"221","errNo":0,…}` |
| Cambio empujado | `User/<token>/Push/Dev/Attr/<devId>` | `{"attrs":[…]}` |

Dos cosas no obvias que son las que hacen que esto funcione:

- **Escribir un atributo suelto no vale.** `Req/Attr/W/<devId>` sólo responde
  para booleanos como `onOffStatus`; para temperatura o velocidad el aparato
  ignora el mensaje. Hay que mandar la operación `grSetDAC` con la **lista
  completa** de atributos escribibles (el valor nuevo dentro y el resto
  reenviado tal cual), que es literalmente lo que hace la app.
- **El estado llega por push.** Además del refresco cada 60 s, el aparato
  empuja sus atributos al cambiar algo, así que la entidad se actualiza en ~2 s
  cuando alguien usa la app o el mando.

## Qué instala

Un único dispositivo con:

- `climate` — encendido/apagado, modos (auto, frío, sequedad, calor, ventilador),
  temperatura objetivo 16–30 °C, ventilador (`quiet`/`low`/`medium`/`high`/`auto`)
  y presets **Boost** (`rapidMode`) y **Sleep** (`silentSleepStatus`).
- `sensor.temperatura_interior` — temperatura de sala medida por el split.
- `sensor.temperatura_exterior`
- `sensor.humedad_interior`

## Instalación (HACS)

1. En GitHub, crea un repositorio **público** y sube este proyecto tal cual
   (`hacs.json` y `custom_components/` en la raíz).
2. HACS → ⋮ → **Custom repositories** → añade la URL del repo con categoría
   **Integration**.
3. HACS → Integraciones → busca *Haier SmartAir2 (Attribute API)* → **Instalar**.
4. Reinicia Home Assistant.
5. Dispositivos y servicios → **Añadir integración** → *Haier SmartAir2
   (Attribute API)* → correo, contraseña y región de tu cuenta Haier.

<details>
<summary>Sin HACS (copiando a mano)</summary>

Copia `custom_components/haier_smartair2_attr` dentro de `/config/custom_components`
(Advanced SSH & Web Terminal, Samba, o el add-on *File Editor*) y reinicia.
Después instala las dependencias que faltaran: HA OS las pone solo al arrancar
porque están declaradas en `manifest.json`.

</details>

## Importante: la sesión de Haier es única

La nube de Haier mantiene **una sesión por usuario**: cada vez que se inicia
sesión se invalida el token que estaba en uso. Como esta integración inicia
sesión al arrancar Home Assistant, **la app del móvil quedará deslogueada** (y
al revés: si vuelves a entrar en la app, Home Assistant se reconecta solo en el
siguiente ciclo, pero la app vuelve a caer).

La solución limpia es crear una **segunda cuenta Haier** (otro correo) y
compartir el aparato desde la app principal (*Compartir dispositivo*). Así la
app y Home Assistant nunca se pisan. Configura la integración con el correo
secundario.

## Limitaciones conocidas

- Sigue siendo **control por nube**: hace falta Internet y la nube de Haier.
  Se comprobó que el split no abre ningún puerto TCP en la LAN (0 de 1055), así
  que no hay vía local posible sin hardware adicional.
- El split no informa de `swing` de forma separada: `windDirectionVertical` y
  `windDirectionHorizontal` se leen y se reenvían pero no se exponen como
  control hasta confirmar sus valores en tu modelo.
- Sólo se gestiona un aparato por entrada de configuración (añade la
  integración varias veces si tienes varios splits).

## Verificación en un Haier real

Probado contra un split Haier (`eProtocolVer 2.18`, cuenta de región Europa): lectura completa de estado, encendido/apagado, cambio de
temperatura objetivo 30 → 24 °C confirmado en el display del aparato, y cambio
de velocidad. Todos con `errNo: 0`.
