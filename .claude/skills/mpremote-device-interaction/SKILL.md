---
name: mpremote-device-interaction
description: Use this skill for general MicroPython device interaction via mpremote, including connecting, running code, checking device state, and managing the device. Triggers on "connect to micropython", "run code on device", "check device state", "mpremote", "micropython device", "repl", "device version", "device reset".
---

# MicroPython Device Interaction with mpremote

## Connection basics

mpremote is the standard tool for interacting with MicroPython devices over USB serial.

### Device identification with mpy-dev

The preferred way to identify devices is via `mpy-dev`, a USB serial device registry. It assigns stable labels to devices and resolves them to `/dev/serial/by-id/` paths.

**Install:**
```bash
uv tool install mpy-dev          # preferred
# or: pip install mpy-dev
# or from source: uv tool install git+https://gitlab.com/alelec/mpy-dev.git
```

**Usage:**
```bash
# List all registered devices with connection status
mpy-dev list

# Get the serial path for a named device
mpy-dev tty pico-w
# Output: /dev/serial/by-id/usb-MicroPython_Board_in_FS_mode_e6614c311b7e6f35-if00

# Use with mpremote (compose via subshell)
mpremote connect $(mpy-dev tty pico-w) resume

# Register a new device
mpy-dev register my-board         # interactive: scans and lets you pick
mpy-dev register my-board --device <serial>  # by USB serial number

# See full device info including linked probes
mpy-dev info pico-w

# Record physical associations (e.g. which debug probe connects to which target)
mpy-dev link pico-w pico-probe --rel probe
```

`mpy-dev` tracks which devices are connected, shelved, or offline. The `tty` subcommand outputs a stable `/dev/serial/by-id/` path suitable for scripting. Always check `mpy-dev --help` for the full command reference.

### Manual device identification

If mpy-dev is not available, use `/dev/serial/by-id/` paths directly:
```bash
# List available serial devices
ls /dev/serial/by-id/

# Connect using stable path
mpremote connect /dev/serial/by-id/usb-FTDI_TTL232RG-VREG1V8_FT55TKQB-if00-port0 resume
```

Never use `/dev/ttyUSB0` etc. - these change on reconnection.

### The `resume` subcommand

`resume` connects to the device without interrupting the running application. This is critical for devices running asyncio event loops:

```bash
mpremote connect $(mpy-dev tty my-board) resume              # Interactive REPL
mpremote connect $(mpy-dev tty my-board) resume exec "..."   # Execute code
mpremote connect $(mpy-dev tty my-board) resume fs ls :      # Filesystem ops
mpremote connect $(mpy-dev tty my-board) resume run script.py # Run script
```

Without `resume`, mpremote sends a soft reset (Ctrl+D) which restarts the application.

### mpremote shorthand

If mpremote is configured with device shortcuts:
```bash
mpremote u0 resume                    # Connect to first USB device
mpremote u0 resume exec "print(1)"   # Execute on first USB device
```

## Running code on the device

### Single expression

```bash
mpremote <device> resume exec "import machine; print(machine.freq())"
```

### Multi-line code

```bash
mpremote <device> resume exec "
import os
for f in os.listdir('/'):
    print(f)
"
```

### Running a local script

```bash
mpremote <device> resume run my_script.py
```

The script runs on the device but is NOT saved to the filesystem.

## Checking device state

### Firmware version
```bash
mpremote <device> resume exec "import sys; print(sys.version)"
# Or for detailed build info:
mpremote <device> resume exec "import os; print(os.uname())"
```

### CPU frequency
```bash
mpremote <device> resume exec "import machine; print(machine.freq())"
```

### Reset cause
```bash
mpremote <device> resume exec "import machine; print(machine.reset_cause())"
```

### Free memory
```bash
mpremote <device> resume exec "import gc; gc.collect(); print(gc.mem_free())"
```

### Filesystem contents
```bash
mpremote <device> resume fs ls :
mpremote <device> resume fs ls :data/
mpremote <device> resume fs tree
```

### Available flash space
```bash
mpremote <device> resume exec "import os; s=os.statvfs('/'); print(f'{s[0]*s[3]} bytes free')"
```

## Device management

### Soft reset (restart application)
```bash
mpremote <device> soft-reset
```
Note: no `resume` here since we want the reset.

### Enter interactive REPL
```bash
mpremote <device> resume
```

Exit with Ctrl-] or Ctrl-x.

### Check for stale processes

If mpremote fails with "failed to access", check for processes holding the port:
```bash
fuser /dev/serial/by-id/<device-id>
# Kill stale process if needed
fuser -k /dev/serial/by-id/<device-id>
```

## Important caveats

### Ctrl+C and asyncio

`mpremote resume exec` sends Ctrl+C to enter raw REPL mode. On devices with a running application, this will raise `KeyboardInterrupt` and kill the application. For repeated command execution, use a persistent PTY session instead (see the live-session skill).

### Filesystem module shadows

Python files on the device filesystem override frozen modules of the same name. If the device behaves unexpectedly after flashing new firmware, check for stale `.py` files:

```bash
mpremote <device> resume fs ls :
# Look for .py files that might shadow frozen modules
# Remove them if they're development artifacts:
mpremote <device> resume fs rm :device_override.py
```

## Patterns for common tasks

### Query and display device info

```bash
mpremote <device> resume exec "
import machine, gc, os
gc.collect()
print('Freq:', machine.freq())
print('Free mem:', gc.mem_free())
s = os.statvfs('/')
print('Free flash:', s[0]*s[3], 'bytes')
print('Files:', len(os.listdir('/')))
"
```

### Monitor device output

For short monitoring, use mpremote directly:
```bash
mpremote <device> resume
# Device output streams to terminal
# Type Python expressions at the >>> prompt
# Ctrl-] to exit
```

For long-term monitoring with logging, use a persistent PTY session (see live-session skill).

### Batch operations

When running multiple mpremote commands in sequence, add a brief sleep between them to ensure the serial port is released:

```bash
mpremote <device> resume exec "print('step 1')"
sleep 1
mpremote <device> resume exec "print('step 2')"
```

Without the sleep, the second command may fail with "failed to access" because the first mpremote process hasn't fully released the port yet.
