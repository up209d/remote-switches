# ==========================================
# WebSocket client (RFC 6455) — the device dialling out
# ==========================================
#
# server/ws_protocol.py is the *server* half of RFC 6455: it answers browsers
# that connect to us. This module is the mirror image — we open a connection to
# somebody else's server, which means sending the opening handshake instead of
# replying to one, and masking every frame we send.
#
# Only what server/tunnel.py needs is here. Inbound frames are parsed by
# ws_protocol.parse_frame(), which is direction-agnostic.

import binascii
import hashlib
import os

from server import ws_protocol as ws

# RFC 6455 makes client frames masked and calls for an unpredictable key. That
# rule protects *browsers*: it stops a hostile script steering exact bytes onto
# the wire to poison an intermediary's cache. Nothing we send is attacker-
# chosen and the hop is TLS to a server we run, so we use an all-zero key —
# masking then needs no per-byte Python loop and no second copy of the payload,
# which on a 150MHz MCU is the difference between a brisk page load and a slow
# one. Set this to a random 4 bytes per frame if that reasoning ever stops
# holding; encode() needs the XOR loop back at the same time.
_MASK = b"\x00\x00\x00\x00"


def encode(payload, opcode=ws.OP_BINARY):
    """Build one masked client->server frame (FIN set, never fragmented)."""
    n = len(payload)
    frame = bytearray()
    frame.append(0x80 | opcode)
    if n < 126:
        frame.append(0x80 | n)
    elif n < 65536:
        frame.append(0x80 | 126)
        frame.append((n >> 8) & 0xFF)
        frame.append(n & 0xFF)
    else:
        frame.append(0x80 | 127)
        for i in range(7, -1, -1):
            frame.append((n >> (8 * i)) & 0xFF)
    frame.extend(_MASK)
    frame.extend(payload)      # XOR against an all-zero key is the identity
    return bytes(frame)


def open_handshake(sock, host, path):
    """
    Send the opening handshake and verify the 101 reply. Raises OSError if the
    server refuses or answers with something that isn't a WebSocket — the
    reason travels in the exception and Tunnel._connect writes it to
    tunnel.log, so nothing is logged twice here.

    Runs on a *blocking* socket: this is part of connect, before the tunnel
    switches the socket to non-blocking for the event loop.
    """
    key = binascii.b2a_base64(os.urandom(16)).decode().strip()
    sock.write((
        "GET %s HTTP/1.1\r\n"
        "Host: %s\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: %s\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n" % (path, host, key)
    ).encode())

    status = sock.readline()
    if not status or b" 101" not in status:
        raise OSError("upgrade refused: %s" % (status or b"<no reply>"))

    accept = ""
    while True:
        line = sock.readline()
        if not line or line == b"\r\n" or line == b"\n":
            break
        name, _, value = line.decode().partition(":")
        if name.strip().lower() == "sec-websocket-accept":
            accept = value.strip()

    expected = binascii.b2a_base64(
        hashlib.sha1((key + ws.WS_MAGIC).encode()).digest()
    ).decode().strip()
    if accept != expected:
        raise OSError("bad Sec-WebSocket-Accept — not a WebSocket server?")
