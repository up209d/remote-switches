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
    # ---- reverse tunnel to an uptunnel server ---------------------------
    # The device dials OUT to an uptunnel server you run on a host with a fixed
    # DNS name, so the internet can reach it through NAT. Everything (web app,
    # static files, WebSocket) keeps being served by this device — the server is
    # only a pipe. See docs/TUNNEL_PROTOCOL.md.
    #
    # server/token/subdomain come from .env at deploy time (UPTUNNEL_SERVER,
    # UPTUNNEL_TOKEN, UPTUNNEL_SUBDOMAIN); tools/build_settings.py merges them
    # in, so the committed settings.json never holds the token.
    #
    # Override individual keys in settings.json; any you omit keep the default
    # below (this sub-object is merged key-by-key, not replaced wholesale).
    "tunnel": {
        # Master switch. False = behave exactly as before, no outbound socket.
        "enabled": False,
        # Control URL of YOUR uptunnel server, e.g.
        # wss://tunnel.example.com/control. Note MicroPython's ssl defaults to
        # CERT_NONE, so wss buys confidentiality, not proof you reached the
        # right server; `token` is what actually authenticates.
        "server": "",
        # This device's secret, from the server's tokens.json. The server
        # rejects any agent that does not present a known token.
        "token": "",
        # The public name to claim: <subdomain>.<the server's HTTP domain>.
        # The server's token entry decides which subdomains this token may
        # take. Without one there is nothing to route, so the tunnel stays off.
        "subdomain": "",
        # Label shown in the server's logs and /status. Empty derives it from
        # machine.unique_id(), so one settings.json can go to a whole fleet and
        # each board is still tellable apart.
        "name": "",
        # One shot per boot. The connect is blocking, so every attempt freezes
        # the event loop for up to connect_timeout_ms — which also delays the
        # momentary-hold deadman in server/pins.py. With startup_only the device
        # pays that once at boot and then switches the tunnel off for good,
        # behaving exactly like a normal LAN device.
        #
        # Left false by default: uptunnel sessions are meant to be long-lived
        # and re-established, and a device that goes dark for good after a
        # server redeploy defeats the point of remote access. The cost is a
        # recurring stall whenever the server is unreachable, bounded by the
        # backoff below.
        "startup_only": False,
        # How long a blocking connect + TLS + WebSocket handshake may stall the
        # event loop. Note: DNS resolution is not covered by this.
        "connect_timeout_ms": 8000,
        # Reconnect backoff, doubling from min to max on repeated failure.
        # Only consulted when startup_only is false.
        "reconnect_min_ms": 2000,
        "reconnect_max_ms": 60000,
        # Send a WebSocket ping this often; drop and reconnect after this long
        # with no traffic at all from the server.
        "keepalive_ms": 20000,
        "idle_timeout_ms": 60000,
        # Concurrent tunnelled client streams. Each costs RAM for its buffers,
        # so this is the knob that stops a busy page load exhausting the heap.
        "max_streams": 6,
        # RAM ceiling for one inbound frame. Matches the server's own 32KB cap
        # on an HTTP request head, which is the largest unit it forwards in one
        # piece; anything bigger drops the connection instead of the heap.
        "max_frame_bytes": 32768,
    },
    "gemini_api_key": "api-key"
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


def _agent_name(configured):
    """
    Stable per-board label, shown in the tunnel server's logs.

    An explicit name in settings.json always wins. Otherwise it is derived from
    the chip's unique id, so a fleet can share one settings.json and still be
    tellable apart.
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

# Whole tunnel block, passed to server.tunnel.Tunnel(). `name` is resolved here
# so every consumer sees the concrete value, never the empty placeholder.
TUNNEL = _cfg["tunnel"]
TUNNEL["name"] = _agent_name(TUNNEL.get("name"))


GEMINI_API_KEY = _cfg["gemini_api_key"]