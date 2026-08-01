# ==========================================
# Pico 2 W entry point (runs on boot)
# ==========================================
from server import config
from server import state
from server import wifi_conn
from server.led import LedController
from server.webserver import PicoServer


def _static_config():
    """Build the (ip, mask, gateway, dns) tuple from config, or None for DHCP."""
    if not config.STATIC_IP:
        return None
    # Auto-derive gateway (x.x.x.1) and DNS (=gateway) when not specified.
    gateway = config.GATEWAY or (config.STATIC_IP.rsplit(".", 1)[0] + ".1")
    dns = config.DNS or gateway
    return (config.STATIC_IP, config.SUBNET_MASK, gateway, dns)


def main():
    led = LedController("LED")
    # Resume whatever the device was last doing, before the network comes up —
    # a standalone boot re-asserts its outputs without waiting for Wi-Fi.
    if state.restore(led, config):
        print("Restored saved state from %s" % state.STATE_FILE)

    wlan, ip = wifi_conn.connect(
        config.WIFI_SSID, config.WIFI_PASS, config.WIFI_TIMEOUT_S, _static_config()
    )
    print("Dashboard:     http://%s/" % ip)
    print("Live stats WS: ws://%s/api/ws/health" % ip)
    print("GET  health:   http://%s/api/health" % ip)
    print("POST blink:    http://%s/api/blink" % ip)

    server = PicoServer(wlan, ip, led, config)
    server.run()


if __name__ == "__main__":
    main()
