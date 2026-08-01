---
name: mpremote-live-session
description: Use this skill when maintaining a persistent interactive connection to a MicroPython device for sending commands and capturing output. This is the PREFERRED method for device interaction when multiple commands need to be sent, when monitoring device output over time, or when the device runs an asyncio event loop with aiorepl. Triggers on "send commands to device", "monitor device output", "interactive session", "persistent connection", "stress test device", "capture serial output".
---

# Persistent mpremote Session

## CRITICAL: Never use repeated `mpremote resume exec` calls

Each `mpremote resume exec` invocation sends Ctrl+C to enter raw REPL mode. On devices running an asyncio event loop, this raises `KeyboardInterrupt` which is a `BaseException` - not caught by asyncio's `except (CancelledError, Exception)` handler. This kills the event loop, leaving the device in a zombie state where C-level tasks (SPI, GC, timers) continue but no Python asyncio task runs.

**Always use a persistent session instead.**

## The PTY approach

mpremote's REPL mode requires a real terminal (it calls `termios.tcgetattr` on stdin). When driving it from a script, create a PTY pair:

```python
import os, pty, select, signal, sys, time

# Use mpy-dev to resolve device label to stable path:
#   DEVICE = subprocess.check_output(["mpy-dev", "tty", "my-board"]).decode().strip()
# Or hardcode the by-id path:
DEVICE = "/dev/serial/by-id/<device-id>"

# Create PTY pair and fork mpremote
master_fd, slave_fd = pty.openpty()
pid = os.fork()
if pid == 0:
    # Child: mpremote gets the slave PTY as its terminal
    os.close(master_fd)
    os.setsid()
    os.dup2(slave_fd, 0)
    os.dup2(slave_fd, 1)
    os.dup2(slave_fd, 2)
    if slave_fd > 2:
        os.close(slave_fd)
    os.execvp("mpremote", ["mpremote", "connect", DEVICE, "resume"])
    sys.exit(1)

# Parent: communicate via master_fd
os.close(slave_fd)
```

## Sending commands

Write Python code as text lines to the master fd. The aiorepl prompt accepts raw text input:

```python
def send_cmd(cmd):
    """Send a Python command to the aiorepl prompt."""
    os.write(master_fd, (cmd + "\r\n").encode())
    time.sleep(0.3)  # Let aiorepl process
    return read_output(timeout=1.0)
```

## Reading output

Use `select.select()` on the master fd to read device output without blocking:

```python
def read_output(timeout=0.1):
    """Read available output from the device."""
    text = ""
    while True:
        ready, _, _ = select.select([master_fd], [], [], timeout)
        if not ready:
            break
        try:
            chunk = os.read(master_fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        text += chunk.decode("utf-8", errors="replace")
        timeout = 0.01  # Drain quickly once data flows
    return text
```

## Logging output

Tee all device output to both stdout and a log file:

```python
def read_and_log(log_fh, timeout=0.1):
    text = read_output(timeout)
    if text:
        sys.stdout.write(text)
        sys.stdout.flush()
        log_fh.write(text)
        log_fh.flush()
    return text
```

## Cleanup

Always terminate mpremote on exit:

```python
import signal

def cleanup():
    try:
        os.kill(pid, signal.SIGTERM)
        os.waitpid(pid, 0)
    except Exception:
        pass
    os.close(master_fd)
```

## When to use this vs mpremote exec

| Scenario | Approach |
|---|---|
| Single quick query | `mpremote <device> resume exec "print(...)"` |
| Multiple commands over time | Persistent PTY session |
| Monitoring device output | Persistent PTY session |
| Device runs asyncio/aiorepl | Persistent PTY session (REQUIRED) |
| Stress testing | Persistent PTY session |
| File copy operations | Direct `mpremote <device> resume fs cp` |

## The `resume` subcommand

Always use `resume` when connecting to a running device. Without it, mpremote performs a soft reset which restarts the application:

```
mpremote connect <device> resume        # Correct: connects without interrupting
mpremote connect <device>               # WRONG: soft-resets the device
```

## Device path

Always use `/dev/serial/by-id/<name>` paths, never `/dev/ttyUSB0` or similar. The by-id path is stable across reboots and USB re-enumeration:

```
/dev/serial/by-id/usb-FTDI_TTL232RG-VREG1V8_FT55TKQB-if00-port0
```

## aiorepl vs raw_repl

MicroPython devices with asyncio typically run aiorepl, which provides an interactive REPL integrated with the asyncio event loop. Two modes of operation:

- **aiorepl prompt** (typing text): Commands execute within the running event loop. No Ctrl+C sent. Safe for asyncio devices. The persistent PTY session uses this mode.
- **raw_repl** (Ctrl+A protocol): Used by `mpremote exec`. Sends Ctrl+C first, which can kill the event loop. The `full_cpu_speed` wrapper in some firmware boosts CPU to 64MHz for raw_repl execution.

## Detecting stalls

Monitor `last_output_time` to detect when the device stops producing output:

```python
STALL_TIMEOUT = 45  # seconds

last_output_time = time.time()

# In read_output, update last_output_time when data arrives
def is_stalled():
    return time.time() - last_output_time > STALL_TIMEOUT
```
