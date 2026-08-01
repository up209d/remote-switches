import network
import time


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
