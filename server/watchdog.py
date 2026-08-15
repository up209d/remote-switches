# ==========================================
# Last-resort reboot (machine.WDT + a stall detector)
# ==========================================
#
# Two failures need catching and they are not the same shape:
#
#   * A hard hang — the loop stops executing. Only hardware can see this, and
#     the RP2 watchdog counter tops out at 8388ms (verified on RPI_PICO2_W,
#     MicroPython 1.28: WDT(timeout=8389) raises "timeout exceeds 8388"). So the
#     hardware timer runs at its ceiling and reboots within ~8s.
#
#   * A livelock — the loop keeps running and would keep feeding the watchdog
#     happily, while every pass throws before doing any work. The hardware timer
#     is blind to this by construction. So feeding is conditional: a pass that
#     completed cleanly refreshes `_last_good_ms`, and once that goes stale by
#     `stall_timeout_ms` we simply stop feeding and let the timer fire.
#
# That is why the configurable threshold (default 60s) can exceed the hardware
# ceiling: it is enforced by withholding the feed, not by the counter.
#
# Module-level rather than an object because there is exactly one loop and one
# watchdog per boot, and the connect path in server/tunnel.py has to reach it
# without threading a handle through three call sites — same shape as
# server/tunnel_log.py.

import time

from server.tunnel_log import log

# The RP2 hardware maximum. Not a tuning knob.
HW_TIMEOUT_MS = 8388

_wdt = None
_stall_ms = 0
_last_good_ms = 0
_tripped = False


def start(cfg, now_ms=None):
    """Arm the watchdog from the config's `watchdog` block. Never raises."""
    global _wdt, _stall_ms, _last_good_ms, _tripped
    _last_good_ms = time.ticks_ms() if now_ms is None else now_ms
    _tripped = False
    _stall_ms = int(cfg.get("stall_timeout_ms", 60000))
    if not cfg.get("enabled"):
        return
    try:
        import machine
        _wdt = machine.WDT(timeout=HW_TIMEOUT_MS)
    except Exception as e:
        # A board without a usable WDT still has to run; it just loses the
        # last-resort reboot.
        log("watchdog: unavailable (%s) — running without it" % e)
        return
    log("watchdog: armed (hw %dms, stall %dms)" % (HW_TIMEOUT_MS, _stall_ms))


def pet():
    """
    Feed the hardware timer without claiming the loop is healthy.

    For work that legitimately blocks longer than the hardware ceiling — the
    connect/TLS/WebSocket handshake in server/tunnel.py, which is allowed
    connect_timeout_ms and whose DNS lookup is not bounded at all. The stall
    detector still applies, so this cannot mask a livelock indefinitely.
    """
    if _wdt is not None and not _tripped:
        _wdt.feed()


def feed(now_ms, healthy=True):
    """
    Called once per event-loop pass. `healthy` is False when that pass raised.

    Once the stall threshold is crossed this deliberately stops feeding, so the
    reboot comes from the hardware timer a fraction of a second later.
    """
    global _last_good_ms, _tripped
    if healthy:
        _last_good_ms = now_ms
    if _wdt is None or _tripped:
        return
    if time.ticks_diff(now_ms, _last_good_ms) >= _stall_ms:
        _tripped = True
        log("watchdog: %dms with no healthy loop pass — rebooting" % _stall_ms)
        return
    _wdt.feed()
