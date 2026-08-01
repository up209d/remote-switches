import time
from machine import Pin

from server.led.patterns import FixedPattern, TickPattern, MorsePattern


class LedController:
    """
    Owns the on-board LED and drives it from a swappable "pattern".
    The event loop calls tick() frequently; the active pattern decides the
    LED level based on how long it has been running.
    """

    def __init__(self, pin_id="LED"):
        self._pin = Pin(pin_id, Pin.OUT)
        self._level = -1
        self._pattern = FixedPattern(False)
        self._start_ms = time.ticks_ms()
        self._apply(0)

    # ---- internal -------------------------------------------------------
    def _apply(self, level):
        if level != self._level:
            self._level = level
            self._pin.value(level)

    def _set_pattern(self, pattern):
        self._pattern = pattern
        self._start_ms = time.ticks_ms()
        self._apply(pattern.level(0))

    # ---- public API -----------------------------------------------------
    def set_fixed(self, on):
        self._set_pattern(FixedPattern(on))

    def set_tick(self, on_ms=500, off_ms=500):
        self._set_pattern(TickPattern(on_ms, off_ms))

    def set_morse(self, message="SOS", wpm=10):
        self._set_pattern(MorsePattern(message, wpm))

    def set(self, on):
        """Convenience alias for a fixed on/off (used on shutdown)."""
        self.set_fixed(on)

    def apply_command(self, msg, cfg):
        """
        Apply a {"mode": ...} command dict. Returns True if recognised.

        Shared by the /api/blink handler and the boot-time state restore, so a
        persisted LED state and an incoming command take the exact same path.
        """
        mode = msg.get("mode")
        if mode == "fixed":
            self.set_fixed(bool(msg.get("on", False)))
        elif mode == "tick":
            self.set_tick(
                msg.get("on_ms", cfg.DEFAULT_TICK_ON_MS),
                msg.get("off_ms", cfg.DEFAULT_TICK_OFF_MS),
            )
        elif mode == "morse":
            self.set_morse(
                msg.get("message", cfg.DEFAULT_MORSE_MESSAGE),
                msg.get("wpm", cfg.DEFAULT_MORSE_WPM),
            )
        else:
            return False
        return True

    def tick(self, now_ms):
        elapsed = time.ticks_diff(now_ms, self._start_ms)
        self._apply(self._pattern.level(elapsed))

    def state(self):
        s = self._pattern.state()
        s["on"] = bool(self._level)
        return s

    def persist_state(self):
        """
        State for state.json: the pattern only, in apply_command() shape.

        Unlike state(), this leaves out the instantaneous LED level — for tick
        and morse that is just where the pattern happened to be, not something
        to restore.
        """
        return self._pattern.state()
