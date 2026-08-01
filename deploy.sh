#!/usr/bin/env bash
#
# Build the web app, upload the firmware + web to the Pico, and run it.
#
#   pipenv run deploy                          # auto-detect the Pico
#   DEVICE=/dev/tty.usbmodem1101 pipenv run deploy   # pick a specific port
#   DIRTY=1 pipenv run deploy                  # keep existing files (incremental)
#   NORUN=1 pipenv run deploy                  # upload only, don't run
#
# By default this wipes server/ and www/ on the device first, so files you
# deleted locally never linger on the Pico.
#
# (You can also run it directly: ./deploy.sh)

set -euo pipefail
cd "$(dirname "$0")"

# mpremote lives in the pipenv venv; use it directly if already inside `pipenv
# run`/`pipenv shell`, otherwise shell out via pipenv.
if command -v mpremote >/dev/null 2>&1; then
    MP="mpremote"
else
    MP="pipenv run mpremote"
fi

# Optional explicit device (otherwise mpremote auto-detects the first board).
CONNECT=""
if [ -n "${DEVICE:-}" ]; then
    CONNECT="connect ${DEVICE}"
fi

echo "==> [1/3] Building web app (web/ -> www/)"
( cd web && npm run build )

# Wi-Fi credentials live in .env (gitignored), not in the committed
# settings.json — merge them into a temp copy and upload that.
BUILD_SETTINGS="$(mktemp)"
trap 'rm -f "$BUILD_SETTINGS"' EXIT
python3 tools/build_settings.py "$BUILD_SETTINGS"

if [ "${DIRTY:-0}" != "1" ]; then
    echo "==> Cleaning old files on the device (server/, www/, state.json)"
    $MP $CONNECT fs rm -r :server >/dev/null 2>&1 || true
    $MP $CONNECT fs rm -r :www    >/dev/null 2>&1 || true
    # Runtime state (LED pattern, GPIO outputs) is deliberately reset by a new
    # version; DIRTY=1 keeps it so the device resumes across an incremental push.
    $MP $CONNECT fs rm :state.json >/dev/null 2>&1 || true
fi

echo "==> [2/3] Uploading to the Pico (unchanged files are skipped)"
$MP $CONNECT \
    fs cp main.py : + \
    fs cp "$BUILD_SETTINGS" :settings.json + \
    fs cp -r server : + \
    fs cp -r www :

if [ "${NORUN:-0}" = "1" ]; then
    echo "==> Uploaded. Reset the Pico to run main.py on boot."
    exit 0
fi

echo "==> [3/3] Running main.py on the Pico (Ctrl-C to stop)"
exec $MP $CONNECT run main.py
