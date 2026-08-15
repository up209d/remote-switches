# ==========================================
# Best-effort clock sync (SNTP)
# ==========================================
#
# The RP2 has no battery-backed RTC, so time.localtime() starts at the board's
# power-on epoch and every reboot resets it. That made tunnel.log stamps read as
# uptime and jump backwards at a restart, which is exactly the wrong property
# for a log you go back to after a failure.
#
# One SNTP call after Wi-Fi comes up fixes it. It is best-effort by design: the
# tunnel and the web server must come up whether or not an NTP packet gets
# through, so a failure here is a logged no-op, never an exception. Until it
# succeeds the stamps stay as they were, which is still ordered and still useful.

import time

from server.tunnel_log import log

# Re-sync this often. The RP2 clock drifts, and a device that has been up for
# weeks would otherwise slowly disagree with the server's own logs.
RESYNC_MS = 86400000            # 24h

_synced = False
_next_ms = 0


def synced():
    return _synced


def sync(now_ms=None, force=False):
    """
    Try to set the clock. Returns True if it is now synced.

    Cheap to call on every event-loop pass: it returns immediately unless a
    sync is actually due.
    """
    global _synced, _next_ms
    if now_ms is None:
        now_ms = time.ticks_ms()
    if not force and _synced and time.ticks_diff(now_ms, _next_ms) < 0:
        return True
    try:
        import ntptime
        ntptime.settime()
    except Exception as e:
        # Retry on the normal schedule rather than hammering a server that is
        # unreachable — the clock being wrong is a cosmetic problem.
        _next_ms = time.ticks_add(now_ms, RESYNC_MS if _synced else 60000)
        if not _synced:
            log("time: NTP sync failed (%s) — stamps stay as uptime" % e)
        return _synced
    _next_ms = time.ticks_add(now_ms, RESYNC_MS)
    if not _synced:
        _synced = True
        t = time.localtime()
        log("time: clock synced to %04d-%02d-%02d %02d:%02d:%02dZ"
            % (t[0], t[1], t[2], t[3], t[4], t[5]))
    return True
