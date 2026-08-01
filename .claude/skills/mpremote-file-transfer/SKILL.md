---
name: mpremote-file-transfer
description: Use this skill when copying files to or from a MicroPython device using mpremote. Covers file copy syntax, directory operations, and best practices for device filesystem management. Triggers on "copy file to device", "upload to device", "download from device", "mpremote fs", "device filesystem", "copy firmware files".
---

# File Transfer with mpremote

## Basic copy operations

Copy a local file to the device:
```bash
mpremote <device> resume fs cp local_file.py :remote_file.py
```

Copy from device to host:
```bash
mpremote <device> resume fs cp :remote_file.py local_file.py
```

The colon prefix `:` denotes a device path. Without it, the path is local.

## Device path syntax

- `:filename.py` - file in the device's current directory (root)
- `:/path/to/file` - absolute path on device
- `:data/1.data` - relative path on device

## Always use `resume`

```bash
mpremote <device> resume fs cp file.py :file.py     # Correct: no soft reset
mpremote <device> fs cp file.py :file.py             # WRONG: resets device first
```

Without `resume`, mpremote performs a soft reset before the filesystem operation, restarting the application and potentially losing state.

## Device identification

Use `mpy-dev` to resolve device labels to stable serial paths:

```bash
# Using mpy-dev (preferred)
mpremote connect $(mpy-dev tty my-board) resume fs cp file.py :file.py

# Or hardcode the by-id path
mpremote connect /dev/serial/by-id/usb-FTDI_TTL232RG-VREG1V8_FT55TKQB-if00-port0 resume fs cp ...

# Or use mpremote shorthand if configured
mpremote u0 resume fs cp ...
```

Install mpy-dev with `uv tool install git+https://gitlab.com/alelec/mpy-dev.git` if not available. See the device-interaction skill for full mpy-dev usage.

## Directory operations

List files:
```bash
mpremote <device> resume fs ls :
mpremote <device> resume fs ls :data/
```

Create directory:
```bash
mpremote <device> resume fs mkdir :data
```

Remove file:
```bash
mpremote <device> resume fs rm :device_override.py
```

Remove directory (must be empty):
```bash
mpremote <device> resume fs rmdir :old_dir
```

Recursive file tree:
```bash
mpremote <device> resume fs tree
```

## Copying multiple files

mpremote processes one operation per invocation. For multiple files, use a shell loop:

```bash
for f in *.py; do
    mpremote <device> resume fs cp "$f" ":$f"
    sleep 0.5  # Brief pause to release serial port
done
```

The `sleep` is important - mpremote holds the serial port during the copy, and the next invocation needs it released.

## Large file transfers

For files >50KB, the transfer takes several seconds. mpremote uses the raw REPL protocol for `fs cp`, which sends Ctrl+C on entry. On asyncio/aiorepl devices, this can crash the event loop.

For large transfers to asyncio devices, consider:
1. Transfer while the device is in a safe state (e.g. on dock, not collecting data)
2. Accept that the transfer may restart the application
3. Use the persistent PTY session approach for very large batch transfers

## Filesystem capacity

Check available space from the device:
```bash
mpremote <device> resume exec "import os; print(os.statvfs('/'))"
```

The result tuple fields: `(bsize, frsize, blocks, bfree, bavail, files, ffree, favail, flag, namemax)`. Available bytes = `bsize * bfree`.

## Common patterns

### Deploy a Python module override

```bash
# Copy to device filesystem (overrides frozen module)
mpremote <device> resume fs cp device_override.py :device_override.py

# Verify it's there
mpremote <device> resume fs ls :

# Reboot to pick up the change
mpremote <device> resume exec "import machine; machine.reset()"
```

### Back up device data

```bash
# List data files
mpremote <device> resume fs ls :data/

# Copy all data files to host
mkdir -p backup/data
for f in $(mpremote <device> resume fs ls :data/ | awk '{print $NF}'); do
    mpremote <device> resume fs cp ":data/$f" "backup/data/$f"
    sleep 0.5
done
```

### Clean device filesystem

```bash
# Remove a specific file
mpremote <device> resume fs rm :device_override.py

# Remove from device REPL (for bulk operations)
mpremote <device> resume exec "
import os
for f in os.listdir('data'):
    os.remove('data/' + f)
    print('removed', f)
"
```

## Troubleshooting

**"failed to access" errors**: Another process holds the serial port. Check with `fuser /dev/serial/by-id/<device-id>` and kill stale processes.

**Transfer seems to hang**: Large files take time. A 70KB file takes ~3 seconds. Don't interrupt - partial writes corrupt the filesystem.

**File appears but content is wrong**: The device may have a filesystem cache. After writing, either reboot or call `os.sync()` from the REPL.
