import network
import time

from server import watchdog


def static_config(config):
    """
    Build the (ip, mask, gateway, dns) tuple from config, or None for DHCP.

    Lives here so boot and the reconnect path in server/webserver.py derive it
    the same way — a reconnect that silently fell back to DHCP would move the
    device out from under whoever was talking to it.
    """
    if not config.STATIC_IP:
        return None
    # Auto-derive gateway (x.x.x.1) and DNS (=gateway) when not specified.
    gateway = config.GATEWAY or (config.STATIC_IP.rsplit(".", 1)[0] + ".1")
    dns = config.DNS or gateway
    return (config.STATIC_IP, config.SUBNET_MASK, gateway, dns)


def connect(ssid, password, timeout_s=15, static=None):
    """
    Connect to Wi-Fi in station mode. Returns (wlan, ip).

    static: optional (ip, subnet_mask, gateway, dns) tuple. When given, the
    interface is reconfigured to that fixed address after connecting, instead
    of keeping the DHCP-assigned one.
    """
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if not wlan.isconnected():
        print("Connecting to Wi-Fi...")
        wlan.connect(ssid, password)
        remaining = timeout_s
        while not wlan.isconnected() and remaining > 0:
            time.sleep(1)
            remaining -= 1
            # This wait outlasts the hardware watchdog's 8.4s ceiling, and it is
            # also reached from the reconnect path with the timer already armed.
            watchdog.pet()

    if not wlan.isconnected():
        raise RuntimeError("Failed to connect to Wi-Fi")

    if static:
        try:
            wlan.ifconfig(static)
            print("Static IP configured:", static[0])
        except Exception as e:
            print("Static IP config failed (%s); staying on DHCP" % e)

    ip = wlan.ifconfig()[0]
    print("Connected! IP:", ip)
    return wlan, ip
