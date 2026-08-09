import hashlib
import binascii

WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# Opcodes
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA


def handshake_response(key):
    """Build the HTTP 101 upgrade response for a given Sec-WebSocket-Key."""
    accept = binascii.b2a_base64(
        hashlib.sha1((key + WS_MAGIC).encode()).digest()
    ).decode().strip()
    return (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Accept: %s\r\n\r\n" % accept
    )


def encode(data, opcode=OP_TEXT):
    """Encode a server->client frame (unmasked, single frame)."""
    payload = data.encode() if isinstance(data, str) else data
    length = len(payload)
    frame = bytearray()
    frame.append(0x80 | opcode)  # FIN + opcode
    if length < 126:
        frame.append(length)
    elif length < 65536:
        frame.append(126)
        frame.append((length >> 8) & 0xFF)
        frame.append(length & 0xFF)
    else:
        frame.append(127)
        for i in range(7, -1, -1):
            frame.append((length >> (8 * i)) & 0xFF)
    frame.extend(payload)
    return bytes(frame)


def _header(buf):
    """
    (payload_offset, payload_len, mask_offset) for the frame at buf[0], or None
    if the header isn't all there yet. mask_offset is -1 on an unmasked frame.
    """
    n = len(buf)
    if n < 2:
        return None
    length = buf[1] & 0x7F
    offset = 2
    if length == 126:
        if n < 4:
            return None
        length = (buf[2] << 8) | buf[3]
        offset = 4
    elif length == 127:
        if n < 10:
            return None
        length = 0
        for i in range(2, 10):
            length = (length << 8) | buf[i]
        offset = 10
    mask = -1
    if buf[1] & 0x80:
        mask = offset
        offset += 4
    return offset, length, mask


def frame_len(buf):
    """
    Total byte length of the frame at the start of `buf`, or -1 if `buf` doesn't
    hold all of it yet. Framing arithmetic only — nothing is unmasked or copied.

    server/tunnel.py uses this to tell whether a whole client frame has arrived
    before handing the stream to decode(), which would otherwise block.
    """
    h = _header(buf)
    if h is None:
        return -1
    total = h[0] + h[1]
    return total if len(buf) >= total else -1


def parse_frame(buf):
    """
    Decode the frame at the start of `buf`: (fin, opcode, payload, total_len),
    or None if it isn't complete. The buffer-based twin of decode(), for callers
    that already hold the bytes instead of a socket to read them from.
    """
    h = _header(buf)
    if h is None:
        return None
    offset, length, mask = h
    total = offset + length
    if len(buf) < total:
        return None
    payload = bytes(buf[offset:total])
    if mask >= 0 and length:
        key = buf[mask:mask + 4]
        payload = bytes(payload[i] ^ key[i % 4] for i in range(length))
    return bool(buf[0] & 0x80), buf[0] & 0x0F, payload, total


def _recv_exact(sock, n):
    """Read exactly n bytes. Returns None on a closed/broken connection."""
    if n == 0:
        return b""
    buf = bytearray()
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except OSError:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def decode(sock):
    """
    Read one client->server frame.
    Returns (opcode, payload_bytes), or (None, None) if the connection closed.
    """
    hdr = _recv_exact(sock, 2)
    if hdr is None:
        return None, None

    b1, b2 = hdr[0], hdr[1]
    opcode = b1 & 0x0F
    masked = b2 & 0x80
    length = b2 & 0x7F

    if length == 126:
        ext = _recv_exact(sock, 2)
        if ext is None:
            return None, None
        length = (ext[0] << 8) | ext[1]
    elif length == 127:
        ext = _recv_exact(sock, 8)
        if ext is None:
            return None, None
        length = 0
        for b in ext:
            length = (length << 8) | b

    mask = b""
    if masked:
        mask = _recv_exact(sock, 4)
        if mask is None:
            return None, None

    payload = _recv_exact(sock, length) if length else b""
    if payload is None:
        return None, None

    if masked and length:
        payload = bytes(payload[i] ^ mask[i % 4] for i in range(length))

    return opcode, payload
