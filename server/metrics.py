import gc
import os
import time
import machine


def get_pico_state(wlan, ip):
    """Gather internal metrics about the Pico 2 W."""
    gc.collect()

    free_ram = gc.mem_free()
    alloc_ram = gc.mem_alloc()
    total_ram = free_ram + alloc_ram

    try:
        statvfs = os.statvfs('/')
        free_flash = statvfs[0] * statvfs[3]
        total_flash = statvfs[0] * statvfs[2]
    except Exception:
        free_flash = 0
        total_flash = 0

    try:
        rssi = wlan.status('rssi')
    except Exception:
        rssi = None

    return {
        "status": "ok",
        "board": "Raspberry Pi Pico 2 W",
        "uptime_seconds": time.ticks_ms() // 1000,
        "cpu": {
            "freq_mhz": machine.freq() // 1000000,
        },
        "memory": {
            "free_kb": round(free_ram / 1024, 2),
            "used_kb": round(alloc_ram / 1024, 2),
            "total_kb": round(total_ram / 1024, 2),
            "usage_percent": round((alloc_ram / total_ram) * 100, 1),
        },
        "storage": {
            "free_kb": round(free_flash / 1024, 2),
            "total_kb": round(total_flash / 1024, 2),
        },
        "network": {
            "ip": ip,
            "rssi_dbm": rssi,
        },
    }
