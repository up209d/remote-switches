# ==========================================
# Runtime state that survives a reboot
# ==========================================
#
# settings.json is *deploy-time* configuration: it ships with the firmware and
# is overwritten on every deploy. This module owns state.json, which is written
# by the running device: whatever the server was last commanded to do (LED
# pattern, GPIO outputs). On a standalone boot it is re-applied, so the Pico
# carries on where it left off with no browser attached.
#
# deploy.sh removes state.json (unless DIRTY=1), so a new version starts from
# the settings.json defaults again.

import json
import os

from server import pins

STATE_FILE = "state.json"
_TMP_FILE = "state.json.tmp"

# Last blob we wrote to flash. Commands that don't actually change the persisted
# state (e.g. the repeated "hold" keep-alives the UI sends while a button is
# pressed) then cost no flash write at all.
_last_written = None


def snapshot(led):
    """The full persistable state of the device."""
    return {"led": led.persist_state(), "pins": pins.snapshot()}


def save(led):
    """Write the current state to flash, unless it is already there."""
    global _last_written
    blob = json.dumps(snapshot(led))
    if blob == _last_written:
        return
    # Write-then-rename, so a power cut mid-write leaves the previous good
    # state.json intact rather than a half-written one.
    try:
        with open(_TMP_FILE, "w") as f:
            f.write(blob)
        try:
            os.remove(STATE_FILE)
        except OSError:
            pass                       # nothing to replace yet
        os.rename(_TMP_FILE, STATE_FILE)
    except OSError as e:
        print("state: could not save:", e)
        return
    _last_written = blob


def restore(led, cfg):
    """
    Re-apply the saved state at boot. Returns True if a state file was applied.

    A missing or corrupt state.json is not an error — the device just starts
    from its defaults. `_last_written` is deliberately left unset so the first
    save() after boot always writes once, re-syncing flash with reality even if
    part of this restore was rejected.
    """
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except OSError:
        return False                   # never saved anything yet
    except ValueError:
        print("state: state.json is not valid JSON; ignoring")
        return False
    if not isinstance(data, dict):
        print("state: state.json must be a JSON object; ignoring")
        return False

    led_state = data.get("led")
    if isinstance(led_state, dict):
        led.apply_command(led_state, cfg)
    pins.restore(data.get("pins"))
    return True
