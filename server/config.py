# ==========================================
# Configuration for the Pico 2 W server
# ==========================================
#
# Don't edit this file. Edit settings.json at the project root instead — it is
# uploaded to the device and loaded here. Any key you omit falls back to the
# default below, and if settings.json is missing/invalid the defaults are used.

import json

_DEFAULTS = {
    "wifi_ssid": "ssid",
    "wifi_pass": "password",
    "http_port": 80,
    "stats_interval_ms": 1000,   # how often stats are pushed to WS clients
    "poll_timeout_ms": 50,       # event-loop poll granularity
    "wifi_timeout_s": 15,        # Wi-Fi connect timeout
    # Static IP. Leave static_ip empty ("") to use DHCP. When set, the Pico
    # claims this fixed address instead of a DHCP-assigned one. gateway/dns
    # may be left empty to auto-derive (x.x.x.1 / gateway).
    "static_ip": "",
    "subnet_mask": "255.255.255.0",
    "gateway": "",
    "dns": "",
    "default_tick_on_ms": 500,
    "default_tick_off_ms": 500,
    "default_morse_message": "SOS",
    "default_morse_wpm": 10,
    # ---- reverse tunnel to a remote relay -------------------------------
    # The device dials OUT to a relay you run on a server with a fixed IP / DNS
    # name, so the internet can reach it through NAT. Everything (web app,
    # static files, WebSocket) keeps being served by this device — the relay is
    # only a pipe. See docs/TUNNEL_PROTOCOL.md.
    #
    # Override individual keys in settings.json; any you omit keep the default
    # below (this sub-object is merged key-by-key, not replaced wholesale).
    "tunnel": {
        # Master switch. False = behave exactly as before, no outbound socket.
        "enabled": False,
        # Relay address. `host` is the fixed IP or DNS name of YOUR server.
        # This is the port the relay listens on for DEVICES, which is not the
        # public port browsers use.
        "host": "",
        "port": 7443,
        # Wrap the device->relay hop in TLS. Note MicroPython's ssl defaults to
        # CERT_NONE: this buys confidentiality, not proof you reached the right
        # server. `token` is what actually authenticates. Set `server_name` if
        # SNI must differ from `host` (e.g. connecting by bare IP).
        "use_tls": True,
        "server_name": "",
        # Shared secret sent in the HELLO frame. The relay MUST reject any
        # device that does not present the expected token.
        "token": "",
        # Identity the relay routes by — it becomes the public subdomain. Leave
        # empty to derive it from machine.unique_id(), so one identical
        # settings.json can be deployed across a whole fleet and every board
        # still gets a distinct, stable name.
        "device_id": "",
        # One shot per boot. The connect is blocking, so every attempt freezes
        # the event loop for up to connect_timeout_ms — which also delays the
        # momentary-hold deadman in server/pins.py. With startup_only the device
        # pays that once at boot and then switches the tunnel off for good,
        # behaving exactly like a normal LAN device.
        #
        # TRADEOFF: nothing reconnects by itself. Restarting the relay, or a
        # brief network blip, leaves every device unreachable from the internet
        # until it is power-cycled. Set this to false to get backoff-retry
        # (reconnect_min_ms/reconnect_max_ms below) at the cost of a recurring
        # stall whenever the relay is unreachable.
        "startup_only": True,
        # How long a blocking connect + TLS handshake may stall the event loop.
        # Note: DNS resolution is not covered by this, so a literal IP in `host`
        # is the only way to bound the stall strictly.
        "connect_timeout_ms": 8000,
        # Reconnect backoff, doubling from min to max on repeated failure.
        # Only consulted when startup_only is false.
        "reconnect_min_ms": 2000,
        "reconnect_max_ms": 60000,
        # Send a PING this often; drop and reconnect after this long with no
        # traffic at all from the relay.
        "keepalive_ms": 20000,
        "idle_timeout_ms": 60000,
        # Concurrent tunnelled client streams. Each costs RAM for its buffers,
        # so this is the knob that stops a busy page load exhausting the heap.
        "max_streams": 6,
    },
}

# Checked in order; first readable one wins. "settings.json" resolves relative
# to the device root (the current working directory at boot).
_SETTINGS_FILES = ("settings.json", "/settings.json")


def _load():
    values = dict(_DEFAULTS)
    for path in _SETTINGS_FILES:
        try:
            with open(path) as f:
                user = json.load(f)
        except OSError:
            continue  # file not found here; try the next path
        except ValueError:
            print("config: settings.json is not valid JSON; using defaults")
            break
        if isinstance(user, dict):
            # "tunnel" is a nested object, so merge it key-by-key — a plain
            # update() would drop every default the user didn't restate.
            user_tunnel = user.pop("tunnel", None)
            values.update(user)
            if isinstance(user_tunnel, dict):
                values["tunnel"] = dict(_DEFAULTS["tunnel"])
                values["tunnel"].update(user_tunnel)
        else:
            print("config: settings.json must be a JSON object; using defaults")
        break
    return values


def _device_id(configured):
    """
    Stable per-board identity, used by the relay as the public subdomain.

    An explicit device_id in settings.json always wins. Otherwise it is derived
    from the chip's unique id, so a fleet can share one settings.json.
    """
    if configured:
        return configured
    try:
        import binascii
        import machine
        return "pico-" + binascii.hexlify(machine.unique_id()).decode()
    except Exception:
        return "pico-unknown"


_cfg = _load()

# Exposed as module-level constants so the rest of the app keeps using
# config.WIFI_SSID, config.HTTP_PORT, etc.
WIFI_SSID = _cfg["wifi_ssid"]
WIFI_PASS = _cfg["wifi_pass"]
HTTP_PORT = _cfg["http_port"]
STATS_INTERVAL_MS = _cfg["stats_interval_ms"]
POLL_TIMEOUT_MS = _cfg["poll_timeout_ms"]
WIFI_TIMEOUT_S = _cfg["wifi_timeout_s"]
STATIC_IP = _cfg["static_ip"]
SUBNET_MASK = _cfg["subnet_mask"]
GATEWAY = _cfg["gateway"]
DNS = _cfg["dns"]
DEFAULT_TICK_ON_MS = _cfg["default_tick_on_ms"]
DEFAULT_TICK_OFF_MS = _cfg["default_tick_off_ms"]
DEFAULT_MORSE_MESSAGE = _cfg["default_morse_message"]
DEFAULT_MORSE_WPM = _cfg["default_morse_wpm"]

# Whole tunnel block, passed to server.tunnel.Tunnel(). device_id is resolved
# here so every consumer sees the concrete value, never the empty placeholder.
TUNNEL = _cfg["tunnel"]
TUNNEL["device_id"] = _device_id(TUNNEL.get("device_id"))
