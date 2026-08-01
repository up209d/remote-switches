import time

from machine import Pin

# GPIOs broken out on the Pico 2 W header. GP23/24/25 and GP29 are used by the
# CYW43 wireless chip, so we deliberately skip them — creating Pin objects on
# those can disrupt Wi-Fi.
SAFE_GPIOS = list(range(0, 23)) + [26, 27, 28]

# ADC-capable pins (for labelling only).
ADC_GPIOS = (26, 27, 28)

# Momentary "hold" safety net: if the browser stops refreshing a held-HIGH pin
# (tab closed, Wi-Fi drop, lost pointer-up) the deadman fires and forces it LOW.
# The client keep-alives well inside this window while the button is pressed.
DEADMAN_MS = 1500

# Cache Pin objects so we don't reallocate 26 of them every poll. Constructed
# with no mode argument, so the pin's existing direction is left untouched.
_pins = {}

# Pins we've armed as outputs: gpio -> {"value": 0/1, "off_at": ticks_ms|None}.
# A pin absent from this map is in the default "monitor" (input) mode and is
# only ever read, never driven. `off_at` is an absolute deadline for automatic
# revert-to-LOW (used by both momentary hold and pulse); None means "persist".
_out = {}


def _pin(n):
    p = _pins.get(n)
    if p is None:
        p = Pin(n)          # no mode -> does not reconfigure the pin
        _pins[n] = p
    return p


def _configure(n, mode):
    """(Re)create a Pin with an explicit direction and cache it."""
    p = Pin(n, mode)
    _pins[n] = p
    return p


def _arm(n):
    if n not in _out:
        p = _configure(n, Pin.OUT)
        p.value(0)
        _out[n] = {"value": 0, "off_at": None}


def _release(n):
    if n in _out:
        del _out[n]
        _configure(n, Pin.IN)   # stop driving; back to monitor


def _drive(n, value):
    value = 1 if value else 0
    _pin(n).value(value)
    _out[n]["value"] = value


def apply_pin_command(msg):
    """
    Apply a single pin command. Returns True if recognised.

    Commands (all carry an integer ``gpio`` in SAFE_GPIOS):
      {"gpio": N, "op": "arm"}                  -> claim as output, driven LOW
      {"gpio": N, "op": "release"}              -> back to monitor (input)
      {"gpio": N, "op": "write", "value": 0|1}  -> latch/toggle, persists
      {"gpio": N, "op": "hold",  "value": 0|1}  -> momentary; 1 arms the deadman
      {"gpio": N, "op": "pulse", "ms": T}       -> HIGH for T ms, then auto-LOW
    """
    try:
        n = int(msg.get("gpio"))
    except (TypeError, ValueError):
        return False
    if n not in SAFE_GPIOS:
        return False

    op = msg.get("op")

    if op == "arm":
        _arm(n)
        return True
    if op == "release":
        _release(n)
        return True

    # All remaining ops drive the pin, so it must be armed first. Arm lazily so
    # a "write"/"hold"/"pulse" on a fresh pin just works.
    if n not in _out:
        _arm(n)

    if op == "write":
        _drive(n, msg.get("value", 0))
        _out[n]["off_at"] = None
        return True
    if op == "hold":
        on = bool(msg.get("value", 0))
        _drive(n, 1 if on else 0)
        _out[n]["off_at"] = time.ticks_add(time.ticks_ms(), DEADMAN_MS) if on else None
        return True
    if op == "pulse":
        try:
            ms = int(msg.get("ms", 250))
        except (TypeError, ValueError):
            ms = 250
        ms = max(20, min(5000, ms))
        _drive(n, 1)
        _out[n]["off_at"] = time.ticks_add(time.ticks_ms(), ms)
        return True

    return False


def tick_pins(now_ms=None):
    """Expire momentary holds / pulses. Returns True if any pin changed."""
    if now_ms is None:
        now_ms = time.ticks_ms()
    changed = False
    for n, st in _out.items():
        off_at = st["off_at"]
        if off_at is not None and st["value"] and time.ticks_diff(now_ms, off_at) >= 0:
            _pin(n).value(0)
            st["value"] = 0
            st["off_at"] = None
            changed = True
    return changed


def snapshot():
    """
    The output state worth persisting: which pins are armed and their level.

    Momentary holds and pulses carry a deadline (``off_at``), so they are
    recorded as armed-LOW — they are time-limited by design and must never come
    back HIGH after a reboot. Sorted so an unchanged state serialises
    identically every time.
    """
    return [
        {"gpio": n, "value": _out[n]["value"] if _out[n]["off_at"] is None else 0}
        for n in sorted(_out)
    ]


def restore(saved):
    """Re-arm the pins from a snapshot() and re-assert their latched levels."""
    if not saved:
        return
    for item in saved:
        try:
            n = int(item["gpio"])
        except (TypeError, ValueError, KeyError):
            continue
        if n not in SAFE_GPIOS:
            continue
        _arm(n)
        if item.get("value"):
            _drive(n, 1)


def read_pins():
    """Return the current level + mode of each header GPIO."""
    out = []
    for n in SAFE_GPIOS:
        armed = n in _out
        if armed:
            value = _out[n]["value"]
        else:
            try:
                value = _pin(n).value()
            except Exception:
                value = None
        out.append({
            "gpio": n,
            "value": value,
            "adc": n in ADC_GPIOS,
            "mode": "out" if armed else "in",
        })
    return out
