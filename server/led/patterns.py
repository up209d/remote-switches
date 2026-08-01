from server.led.morse import build_timeline, units_per_wpm

# Each pattern is a pure function of "elapsed time since it started":
#   level(elapsed_ms) -> 1 (LED on) or 0 (off)
#   state()           -> JSON-serialisable description (always includes "mode")


class FixedPattern:
    """Steady on or steady off."""

    def __init__(self, on):
        self.on = bool(on)

    def level(self, elapsed_ms):
        return 1 if self.on else 0

    def state(self):
        return {"mode": "fixed", "on": self.on}


class TickPattern:
    """Asymmetric square wave: on for on_ms, off for off_ms, repeating."""

    def __init__(self, on_ms=500, off_ms=500):
        self.on_ms = _clamp_ms(on_ms)
        self.off_ms = _clamp_ms(off_ms)
        self.cycle = self.on_ms + self.off_ms

    def level(self, elapsed_ms):
        return 1 if (elapsed_ms % self.cycle) < self.on_ms else 0

    def state(self):
        return {"mode": "tick", "on_ms": self.on_ms, "off_ms": self.off_ms}


class MorsePattern:
    """Blink a message in Morse code, repeating."""

    def __init__(self, message="SOS", wpm=10):
        self.message = str(message)
        self.wpm = max(1, min(60, int(wpm)))
        self.unit_ms = units_per_wpm(self.wpm)
        self.segments, self.total = build_timeline(self.message, self.unit_ms)

    def level(self, elapsed_ms):
        if self.total <= 0:
            return 0
        t = elapsed_ms % self.total
        for lvl, end in self.segments:
            if t < end:
                return lvl
        return 0

    def state(self):
        return {
            "mode": "morse",
            "message": self.message,
            "wpm": self.wpm,
            "unit_ms": self.unit_ms,
        }


def _clamp_ms(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 500
    return max(20, min(60000, value))
