#!/usr/bin/env python3
"""
Merge the secrets from .env into settings.json and write the result out.

settings.json is committed with empty Wi-Fi credentials; the real ones live in
.env (gitignored). deploy.sh calls this and uploads the merged copy, so the
device gets working credentials that were never in git.

    python3 tools/build_settings.py <output-path>
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# .env variable -> settings.json key
SECRET_KEYS = {
    "WIFI_SSID": "wifi_ssid",
    "WIFI_PASS": "wifi_pass",
}


def read_env(path):
    """Parse KEY=VALUE lines. No shell expansion, so $ in a password is safe."""
    values = {}
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: build_settings.py <output-path>")

    with open(os.path.join(ROOT, "settings.json")) as f:
        settings = json.load(f)

    env = read_env(os.path.join(ROOT, ".env"))
    for var, key in SECRET_KEYS.items():
        if env.get(var):
            settings[key] = env[var]

    if not settings.get("wifi_ssid"):
        sys.exit("build_settings: WIFI_SSID is not set — copy .env.example to .env")

    with open(sys.argv[1], "w") as f:
        json.dump(settings, f)


main()
