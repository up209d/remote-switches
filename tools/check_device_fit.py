#!/usr/bin/env python3
"""
Check whether this app fits a target MicroPython device.

    pipenv run check-device                 # check against the default target
    pipenv run check-device esp32-generic   # check a specific profile
    pipenv run check-device --all           # table of every known profile
    pipenv run check-device --list          # list known profiles
    pipenv run check-device --probe         # ask the CONNECTED board for its real free FS + heap

What it can and can't tell you:
  * STORAGE (flash filesystem): checked statically and reliably here - we sum
    the exact files deploy.sh uploads and compare to the device's free FS.
  * RAM: NOT knowable statically. A chip's SRAM spec is not MicroPython's usable
    heap. This script prints the profile's heap budget for rough sizing and, with
    --probe, reads the real gc.mem_free() off a connected board. The only true
    RAM verdict is: deploy the app and check gc.mem_free() on the device.
"""

import json
import math
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "device_profiles.json")

# The exact set deploy.sh copies to the device filesystem.
DEPLOY_SET = ["main.py", "settings.json", "server", "www"]

# littlefs (rp2/esp) rounds each file up to a block; 4096 is a realistic default.
FS_BLOCK = 4096
DEFAULT_TARGET = "rpi-pico2-w"
WARN_AT = 0.80  # warn when storage use crosses this fraction of free FS


def iter_files(path):
    if os.path.isfile(path):
        yield path
    elif os.path.isdir(path):
        for dirpath, _dirs, names in os.walk(path):
            for n in names:
                yield os.path.join(dirpath, n)


def footprint():
    """Return (raw_bytes, on_flash_bytes, file_count) for the deploy set."""
    raw = on_flash = count = 0
    for target in DEPLOY_SET:
        p = os.path.join(ROOT, target)
        if not os.path.exists(p):
            continue
        for f in iter_files(p):
            sz = os.path.getsize(f)
            raw += sz
            on_flash += max(FS_BLOCK, math.ceil(sz / FS_BLOCK) * FS_BLOCK)
            count += 1
    return raw, on_flash, count


def load_profiles():
    with open(PROFILES_PATH) as fh:
        data = json.load(fh)
    data.pop("_meta", None)
    return data


def kb(n):
    return "%.0f KB" % (n / 1024)


def check_storage(on_flash, prof):
    free = prof["fs_free_kb"] * 1024
    used = on_flash / free if free else 99
    if on_flash > free:
        verdict = "FAIL - app is larger than the device filesystem"
    elif used >= WARN_AT:
        verdict = "TIGHT - fits, but little headroom for logs/data/growth"
    else:
        verdict = "OK"
    return free, used, verdict


def report_one(key, prof, raw, on_flash):
    free, used, verdict = check_storage(on_flash, prof)
    print("==================================================")
    print("Target: %s  (%s, %s)" % (prof["name"], key, prof["mcu"]))
    print("--------------------------------------------------")
    if not prof.get("wifi", False):
        print("  !! No onboard WiFi - this app's networking needs a WiFi board.")
    print("  STORAGE (statically checked):")
    print("    app on-flash (~4KB blocks): %s   (raw %s)" % (kb(on_flash), kb(raw)))
    print("    device free filesystem:     ~%s" % kb(free))
    print("    usage:                      %.0f%%  ->  %s" % (used * 100, verdict))
    print("  RAM (rough budget - confirm on-device):")
    print("    device free heap (approx):  ~%d KB" % prof["heap_free_kb"])
    if prof["heap_free_kb"] < 64:
        print("    !! Under ~64KB free heap - a WiFi + asyncio web server is unlikely to fit.")
    print("    -> real check: after deploying, run")
    print("       pipenv run mpremote resume exec \"import gc; gc.collect(); print(gc.mem_free())\"")
    if prof.get("notes"):
        print("  Note: %s" % prof["notes"])


def probe():
    """Read the real free FS + free heap off a connected board via mpremote."""
    code = "import os,gc; gc.collect(); s=os.statvfs('/'); print(s[0]*s[3], gc.mem_free())"
    device = os.environ.get("DEVICE", "")
    cmd = ["pipenv", "run", "mpremote"]
    if device:
        cmd += ["connect", device]
    cmd += ["resume", "exec", code]
    print("==> Probing connected board: %s" % " ".join(cmd))
    try:
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print("    probe failed: %s" % e)
        return
    if out.returncode != 0:
        print("    no board responded (is the Pico plugged in?).")
        print("    stderr: %s" % (out.stderr.strip() or "(none)"))
        return
    try:
        fs_free, heap_free = (int(x) for x in out.stdout.split())
    except ValueError:
        print("    unexpected device output: %r" % out.stdout)
        return
    raw, on_flash, _ = footprint()
    print("    real free filesystem: %s   (app needs ~%s)" % (kb(fs_free), kb(on_flash)))
    print("    real free heap:       %s" % kb(heap_free))
    print("    STORAGE: %s" % ("OK" if on_flash <= fs_free else "FAIL - app too big"))
    print("    (free heap is BEFORE importing the app; deploy + re-check to see the app's real cost.)")


def main(argv):
    args = argv[1:]
    profiles = load_profiles()
    raw, on_flash, count = footprint()

    if "--list" in args:
        print("Known device profiles (edit tools/device_profiles.json to add):")
        for k, p in profiles.items():
            print("  %-16s %s" % (k, p["name"]))
        return 0

    print("App deploy footprint: %s across %d files (raw %s)" % (kb(on_flash), count, kb(raw)))
    print("(files: %s)" % ", ".join(DEPLOY_SET))
    print()

    if "--probe" in args:
        probe()
        return 0

    if "--all" in args:
        for k, p in profiles.items():
            report_one(k, p, raw, on_flash)
        return 0

    positional = [a for a in args if not a.startswith("-")]
    key = positional[0] if positional else DEFAULT_TARGET
    if key not in profiles:
        print("Unknown profile %r. Use --list to see options." % key)
        return 1
    report_one(key, profiles[key], raw, on_flash)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
