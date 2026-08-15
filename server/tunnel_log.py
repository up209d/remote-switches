# ==========================================
# Tunnel connection log (tunnel.log)
# ==========================================
#
# The tunnel dials out on its own schedule, usually with nobody watching the
# serial console: a reconnect storm at 3am leaves no trace at all unless it is
# written down. Everything server/tunnel.py has to say about the connection —
# attempts, failures, retries, server refusals, stream errors — goes through
# log() and lands both on the console and in tunnel.log, so the last thousand
# events survive a power cut and can be read back off the device — over HTTP via
# server/logs.py (`/api/logs/tail`, which leaves the app running), or with
# `mpremote fs cat :tunnel.log` if you don't mind killing the run.
#
# Flash is the constraint, so the file is bounded twice over: at most MAX_LINES
# lines, each at most MAX_LINE characters of message. Worst case is ~175KB and
# it never grows past that. A trim keeps the newest _KEEP lines, so the whole
# file is rewritten once per (MAX_LINES - _KEEP) messages rather than on every
# message. Consecutive identical messages are written once, which is what stops
# a repeating failure from hammering flash.
#
# Timestamps come from the device clock, which server/timesync.py sets from NTP
# once Wi-Fi is up. That is best-effort: if it never lands, the clock stays on
# the board's power-on epoch and a stamp reads as uptime rather than wall time.
# The year makes the difference visible — a line stamped 2000-01-02 is uptime.
# Either way it orders events and shows the gaps, which is the main job.
#
# deploy.sh removes tunnel.log (unless DIRTY=1), so a new version starts clean.

import os
import time

LOG_FILE = "tunnel.log"
_TMP_FILE = "tunnel.log.tmp"

MAX_LINES = 1000        # hard ceiling — the file never holds more than this
_KEEP = 800             # ...and a trim leaves this many of the newest
MAX_LINE = 160          # longest message we keep; the rest is cut

_lines = None           # None until we have counted what is already on flash
_last = None            # last message written, for the dedupe above


def configure(max_lines):
    """Raise or lower the ceiling from settings.json (tunnel.log_max_lines)."""
    global MAX_LINES, _KEEP
    max_lines = int(max_lines)
    if max_lines < 10:
        return              # too small to be useful; keep the default
    MAX_LINES = max_lines
    _KEEP = max_lines * 4 // 5


def _count_lines():
    n = 0
    try:
        with open(LOG_FILE) as f:
            for _ in f:
                n += 1
    except OSError:
        pass                        # no log yet, which counts as empty
    return n


def _stamp():
    # Full date on purpose. server/timesync.py sets the clock from NTP shortly
    # after boot, but it is best-effort — and a line still stamped in year 2000
    # (the RP2 power-on epoch) is then self-evidently uptime rather than wall
    # time, instead of silently looking like a real date.
    t = time.localtime()
    return "%04d-%02d-%02d %02d:%02d:%02d" % (t[0], t[1], t[2], t[3], t[4], t[5])


def _trim():
    """Rewrite the file with only its newest _KEEP lines."""
    global _lines
    drop = _lines - _KEEP
    try:
        with open(LOG_FILE) as src:
            for _ in range(drop):
                if not src.readline():
                    break
            # Copied a line at a time: holding 800 lines in RAM to rewrite them
            # would be a fair slice of the heap, and this runs on a device that
            # is mid-reconnect.
            with open(_TMP_FILE, "w") as dst:
                while True:
                    line = src.readline()
                    if not line:
                        break
                    dst.write(line)
        try:
            os.remove(LOG_FILE)
        except OSError:
            pass
        os.rename(_TMP_FILE, LOG_FILE)
    except OSError as e:
        print("tunnel-log: could not trim:", e)
        _lines = _count_lines()     # whatever survived is what we now have
        return
    _lines = _KEEP


def log(msg):
    """Print `msg` and append it to tunnel.log. Never raises."""
    global _lines, _last
    print(msg)
    if msg == _last:
        return                      # nothing new to record; skip the write
    if len(msg) > MAX_LINE:
        msg = msg[:MAX_LINE - 1] + "~"
    if _lines is None:
        _lines = _count_lines()
    try:
        with open(LOG_FILE, "a") as f:
            f.write("%s %s\n" % (_stamp(), msg))
    except OSError as e:
        print("tunnel-log: could not write:", e)
        return
    _last = msg
    _lines += 1
    if _lines >= MAX_LINES:
        _trim()
