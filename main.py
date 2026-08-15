# ==========================================
# Pico 2 W entry point (runs on boot)
# ==========================================
import time

from server import config
from server import state
from server import tunnel_log
from server import wifi_conn
from server.led import LedController
from server.webserver import PicoServer

# How long to wait before rebooting after a failed boot, so a board that cannot
# come up at all is still reachable over USB between attempts.
_RETRY_DELAY_S = 5


def main():
    tunnel_log.configure(config.TUNNEL.get("log_max_lines", 1000))
    # A boot marker, so a restart is unambiguous in the log even when the clock
    # has not been NTP-synced yet and the stamps jump backwards.
    tunnel_log.log("--- boot ---")

    led = LedController("LED")
    # Resume whatever the device was last doing, before the network comes up —
    # a standalone boot re-asserts its outputs without waiting for Wi-Fi.
    if state.restore(led, config):
        print("Restored saved state from %s" % state.STATE_FILE)

    wlan, ip = wifi_conn.connect(
        config.WIFI_SSID, config.WIFI_PASS, config.WIFI_TIMEOUT_S,
        wifi_conn.static_config(config),
    )
    print("Dashboard:     http://%s/" % ip)
    print("Live stats WS: ws://%s/api/ws/health" % ip)
    print("GET  health:   http://%s/api/health" % ip)
    print("POST blink:    http://%s/api/blink" % ip)

    server = PicoServer(wlan, ip, led, config)
    server.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise           # Ctrl-C at the REPL should drop out, not reboot
    except Exception as e:
        # Anything that escapes here used to leave the board sitting at the
        # REPL with no server, no tunnel and no LAN until someone unplugged it.
        # The common case is booting faster than the router after a shared power
        # cut, which wifi_conn.connect turns into a RuntimeError.
        try:
            tunnel_log.log("boot failed: %s: %s — rebooting" % (type(e).__name__, e))
        except Exception:
            pass
        time.sleep(_RETRY_DELAY_S)
        import machine
        machine.reset()
