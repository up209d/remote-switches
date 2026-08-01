#!/usr/bin/env bash
#
# List all potentially-connected serial / USB devices, to help find the Pico.
#
#   ./scan.sh          or          pipenv run scan
#
# The Pico shows up two ways:
#   - Normal mode:   a serial port with USB VID:PID 2e8a:xxxx (Raspberry Pi)
#   - BOOTSEL mode:  a mass-storage volume named RPI-RP2 / RP2350 (no serial)

set -uo pipefail
cd "$(dirname "$0")"

if command -v mpremote >/dev/null 2>&1; then
    MP="mpremote"
else
    MP="pipenv run mpremote"
fi

echo "==================== device scan ===================="

echo
echo "-- mpremote devs (serial ports + USB VID:PID) --"
$MP devs 2>/dev/null || echo "  (mpremote unavailable)"

echo
echo "-- Raspberry Pi boards (USB VID 2e8a) --"
if $MP devs 2>/dev/null | grep -i "2e8a"; then
    :
else
    echo "  (none in normal/serial mode)"
fi

echo
echo "-- /dev serial ports --"
if ls /dev/cu.* /dev/tty.* 2>/dev/null | grep -iE "usbmodem|usbserial|ACM|USB"; then
    :
else
    echo "  (no USB serial ports)"
fi

if [ "$(uname)" = "Darwin" ]; then
    echo
    echo "-- BOOTSEL mass-storage volume (macOS) --"
    if ls -d /Volumes/RP* /Volumes/RPI* 2>/dev/null; then
        :
    else
        echo "  (none — board is not in BOOTSEL mode)"
    fi
fi

echo
echo "====================================================="
