# ==========================================
# Reading log files back over HTTP
# ==========================================
#
# server/tunnel_log.py writes tunnel.log so a 3am reconnect storm leaves a
# trace; this module is how you read it without a USB cable. That matters more
# than it sounds: every mpremote command interrupts main.py, so `fs cat
# :tunnel.log` ends the very run you were trying to diagnose. Over HTTP the
# device keeps running.
#
# The file is bounded at ~175KB, which is far too much to hold in RAM on the
# way out, so a tail is served in two passes: one walk to find the byte range
# of the last N lines (keeping only N integer offsets), then a straight
# file->socket copy of that range. Nothing bigger than a 512-byte chunk is ever
# resident.

import os

from server import static_files

DEFAULT_LINES = 200
MAX_LINES = 500
CHUNK = 512


def _is_file(name):
    try:
        st = os.stat(name)
    except OSError:
        return False
    return (st[0] & 0x8000) != 0      # st_mode: regular file


def _is_log(name):
    # Log names are plain filenames in the root directory. Rejecting anything
    # with a separator is what keeps ?name= from reaching the rest of the fs.
    return (name.endswith(".log")
            and "/" not in name
            and ".." not in name)


def listing():
    """Every *.log file in the root directory, as [{name, size}]."""
    out = []
    try:
        names = os.listdir()
    except OSError:
        return out
    for name in names:
        if not _is_log(name) or not _is_file(name):
            continue
        try:
            out.append({"name": name, "size": os.stat(name)[6]})
        except OSError:
            pass
    out.sort(key=lambda f: f["name"])
    return out


def tail_span(name, lines):
    """
    Byte range (start, length) covering the last `lines` lines of `name`, or
    None if that isn't a readable log file.

    Walks the whole file but keeps only a ring of `lines` offsets, so a 175KB
    log costs a few hundred bytes of heap to locate the tail of.
    """
    if not _is_log(name) or not _is_file(name):
        return None
    starts = [0] * lines
    n = 0
    pos = 0
    try:
        with open(name, "rb") as f:
            while True:
                line = f.readline()
                if not line:
                    break
                starts[n % lines] = pos
                pos += len(line)
                n += 1
    except OSError:
        return None
    if n <= lines:
        return 0, pos
    start = starts[n % lines]           # oldest entry still in the ring
    return start, pos - start


def stream(conn, name, start, length):
    """Copy `length` bytes of `name` from `start` straight to the socket."""
    sent = 0
    try:
        with open(name, "rb") as f:
            f.seek(start)
            while sent < length:
                chunk = f.read(min(CHUNK, length - sent))
                if not chunk:
                    break
                static_files.write_all(conn, chunk)
                sent += len(chunk)
    except OSError as e:
        print("logs: read error:", e)
    # A trim between the two passes shortens the file under us. Rare, but the
    # Content-Length is already sent, so pad rather than hang the client on a
    # body that never finishes.
    while sent < length:
        pad = min(CHUNK, length - sent)
        static_files.write_all(conn, b"\n" * pad)
        sent += pad
