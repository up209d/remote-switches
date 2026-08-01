# ==========================================
# Outbound reverse tunnel to a remote relay
# ==========================================
#
# Problem: the Pico sits behind NAT on a home LAN, so nothing on the internet
# can dial in to it. Solution: the Pico dials *out* to a relay you run on a
# server that has a fixed IP / DNS name, and holds that connection open. The
# relay fronts a public listener and forwards everything it receives down that
# already-open socket.
#
# Nothing about the Pico's own serving changes. A request arriving through the
# tunnel is handed to exactly the same handlers that serve LAN clients, via a
# socket-lookalike object (TunnelStream), so the device keeps serving its own
# web app, its own static files and its own WebSocket. The relay stays a dumb
# pipe — it holds no UI and knows nothing about /api.
#
# Transport: ONE plain-TCP (optionally TLS) connection, framed as
#
#     op:uint8 | stream_id:uint16 big-endian | length:uint16 | payload[length]
#
# This is deliberately not WebSocket: both ends are our own code, so the
# handshake, client-side masking and fragmentation rules would be pure
# overhead. See docs/TUNNEL_PROTOCOL.md for the full wire contract — the relay
# is written against that document, not against this file.

import socket
import time

# ---- frame opcodes (keep in sync with docs/TUNNEL_PROTOCOL.md) -------------
OP_OPEN = 0x01      # relay -> device: a new client stream begins
OP_DATA = 0x02      # both ways: payload bytes belonging to a stream
OP_CLOSE = 0x03     # both ways: this stream is finished
OP_PING = 0x04      # both ways: keepalive probe
OP_PONG = 0x05      # both ways: keepalive reply
OP_FLUSH = 0x06     # relay -> device: buffered bytes now form a complete unit
OP_HELLO = 0x10     # device -> relay: authenticate + identify
OP_READY = 0x11     # relay -> device: authentication accepted

HEADER_LEN = 5
MAX_PAYLOAD = 1024          # bounds a single frame, and so bounds our RAM use
_OUT_FLUSH_AT = 1024        # coalesce small writes into fuller frames

# Connection lifecycle
_IDLE = 0                   # not connected, waiting out the reconnect backoff
_UP = 1                     # authenticated and carrying streams


def _pack(op, sid, payload=b""):
    return bytes((op, (sid >> 8) & 0xFF, sid & 0xFF,
                  (len(payload) >> 8) & 0xFF, len(payload) & 0xFF)) + payload


class TunnelStream:
    """
    A socket-lookalike for one tunnelled client connection.

    This exists so `webserver._serve()`, `static_files.serve()` and
    `ws_protocol` can drive a tunnelled client with the *same* code that drives
    a LAN socket — only the methods those modules actually call are needed:
    recv/send/write/setblocking/settimeout/close.

    Reads never block. The relay buffers a whole request (or a whole WebSocket
    frame) and then sends OP_FLUSH, so by the time a handler runs, everything it
    needs to read is already in `_in`. That is what keeps this single-threaded
    design free of re-entrancy: a handler never has to pump the tunnel socket
    from inside itself.
    """

    pollable = False        # tells _register_ws not to put this in select.poll

    def __init__(self, tunnel, sid):
        self._tunnel = tunnel
        self.sid = sid
        self._in = bytearray()
        self._out = bytearray()
        self.closed = False
        self.upgraded = False       # became a WebSocket via the 101 handshake

    # ---- inbound (relay -> handler) -------------------------------------
    def _feed(self, data):
        self._in.extend(data)

    def recv(self, n):
        if not self._in:
            return b""              # reads as EOF, which is what we want
        take = min(n, len(self._in))
        chunk = bytes(self._in[:take])
        del self._in[:take]
        return chunk

    # ---- outbound (handler -> relay) ------------------------------------
    def send(self, data):
        """
        Buffer bytes for the relay. Returns the count "sent", as
        static_files.write_all() expects — we always accept everything, so no
        short-write loop is needed here.
        """
        if self.closed:
            return len(data)
        self._out.extend(data)
        while len(self._out) >= _OUT_FLUSH_AT:
            self._emit(_OUT_FLUSH_AT)
        return len(data)

    write = send                    # some callers use write() instead

    def _emit(self, count):
        chunk = bytes(self._out[:count])
        del self._out[:count]
        self._tunnel._send_frame(OP_DATA, self.sid, chunk)

    def flush(self):
        while self._out:
            self._emit(min(MAX_PAYLOAD, len(self._out)))

    # ---- socket API the handlers call but we don't need ------------------
    def setblocking(self, flag):
        pass

    def settimeout(self, t):
        pass

    def close(self):
        if self.closed:
            return
        self.flush()
        self.closed = True
        self._tunnel._stream_closed(self.sid, notify=True)


class Tunnel:
    """
    Owns the single outbound connection and demultiplexes streams on it.

    The webserver drives this: it registers `sock` with its poller, calls
    service() once per loop pass, and handle_readable() when the socket has
    data. All callbacks land back on the webserver, so routing lives in exactly
    one place.
    """

    def __init__(self, cfg_tunnel, device_ip=""):
        self.cfg = cfg_tunnel
        self.device_ip = device_ip
        self.sock = None
        self.state = _IDLE
        self.streams = {}
        self._rx = bytearray()
        self._next_attempt_ms = 0
        self._backoff_ms = cfg_tunnel["reconnect_min_ms"]
        self._last_rx_ms = 0
        self._last_ping_ms = 0
        # Set once the tunnel has given up for this boot (see _after_failure).
        # Nothing clears it but a restart, so the event loop stops paying the
        # blocking-connect cost entirely.
        self.disabled = False

    # ---- status ---------------------------------------------------------
    @property
    def connected(self):
        return self.state == _UP

    def owns(self, sock):
        return self.sock is not None and sock is self.sock

    # ---- connect / disconnect -------------------------------------------
    def service(self, server, now_ms):
        """
        Called once per event-loop pass: connect if due, keepalive, flush.
        Returns True if `sock` changed, so the caller can re-register its poller.
        """
        if self.disabled:
            return False
        if self.sock is None:
            if time.ticks_diff(now_ms, self._next_attempt_ms) < 0:
                return False
            return self._connect(now_ms)

        # Keepalive: probe periodically, and give up if the relay goes quiet.
        if time.ticks_diff(now_ms, self._last_ping_ms) >= self.cfg["keepalive_ms"]:
            self._last_ping_ms = now_ms
            self._send_frame(OP_PING, 0)
        if time.ticks_diff(now_ms, self._last_rx_ms) >= self.cfg["idle_timeout_ms"]:
            self._disconnect(now_ms, "relay went silent")
            return True

        for st in list(self.streams.values()):
            st.flush()
        return False

    def _connect(self, now_ms):
        host = self.cfg["host"]
        port = self.cfg["port"]
        # NOTE: this connect (and the TLS handshake below) is BLOCKING. It can
        # stall the event loop for up to connect_timeout_ms, during which the
        # LED pattern freezes. That is the accepted tradeoff for MicroPython —
        # a non-blocking TLS handshake is not reliably supported. Backoff keeps
        # the stall rare when the relay is down.
        print("tunnel: connecting to %s:%d" % (host, port))
        s = None
        try:
            # NOTE: getaddrinfo() is NOT covered by settimeout below, so a DNS
            # name that fails to resolve can stall longer than
            # connect_timeout_ms. Use a literal IP in `host` to bound it.
            addr = socket.getaddrinfo(host, port)[0][-1]
            s = socket.socket()
            s.settimeout(self.cfg["connect_timeout_ms"] / 1000)
            s.connect(addr)
            if self.cfg["use_tls"]:
                s = self._wrap_tls(s, host)
            self._handshake(s)
            s.setblocking(False)
        except Exception as e:
            if s is not None:
                try:
                    s.close()
                except Exception:
                    pass
            self._after_failure(now_ms, "connect failed: %s" % e)
            return False

        self.sock = s
        self.state = _UP
        self._rx = bytearray()
        self._last_rx_ms = now_ms
        self._last_ping_ms = now_ms
        self._backoff_ms = self.cfg["reconnect_min_ms"]
        print("tunnel: up")
        return True

    def _wrap_tls(self, s, host):
        import ssl
        # MicroPython's ssl defaults to CERT_NONE: this gives confidentiality,
        # NOT proof you reached the right server. The HELLO token is what
        # actually authenticates the device. See docs/TUNNEL_PROTOCOL.md.
        name = self.cfg["server_name"] or host
        try:
            return ssl.wrap_socket(s, server_hostname=name)
        except TypeError:
            return ssl.wrap_socket(s)      # older builds lack server_hostname

    def _handshake(self, s):
        """Send OP_HELLO and require OP_READY before carrying any traffic."""
        import json
        hello = json.dumps({
            "token": self.cfg["token"],
            "device_id": self.cfg["device_id"],
            "lan_ip": self.device_ip,
            "proto": 1,
        }).encode()
        s.write(_pack(OP_HELLO, 0, hello))
        # Blocking read of exactly one frame; settimeout() still applies here.
        hdr = self._read_exact(s, HEADER_LEN)
        op = hdr[0]
        length = (hdr[3] << 8) | hdr[4]
        body = self._read_exact(s, length) if length else b""
        if op != OP_READY:
            raise OSError("relay rejected HELLO (op=0x%02x %s)" % (op, body))

    @staticmethod
    def _read_exact(s, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = s.read(n - len(buf))
            if not chunk:
                raise OSError("relay closed during handshake")
            buf.extend(chunk)
        return bytes(buf)

    def _after_failure(self, now_ms, why):
        """
        Decide whether to try again, honouring the startup_only setting.

        With startup_only (the default) the tunnel gets exactly one chance per
        boot: on failure it switches off for good, so a misconfigured or absent
        relay costs the event loop one stall at startup instead of a recurring
        one forever. The device carries on as a normal LAN device.

        The tradeoff is operational: nothing reconnects on its own, so
        restarting the relay leaves every device dark until it is power-cycled.
        Set startup_only to false to get backoff-retry instead.
        """
        if self.cfg.get("startup_only", True):
            self.disabled = True
            print("tunnel: %s — startup_only is set, so the tunnel stays off "
                  "until this device restarts" % why)
            return
        self._next_attempt_ms = time.ticks_add(now_ms, self._backoff_ms)
        print("tunnel: %s — retrying in %dms" % (why, self._backoff_ms))
        self._backoff_ms = min(self._backoff_ms * 2, self.cfg["reconnect_max_ms"])

    def _disconnect(self, now_ms, why="connection lost", retry=True):
        for st in list(self.streams.values()):
            st.closed = True
        self.streams.clear()
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self.state = _IDLE
        self._rx = bytearray()
        if retry:
            self._after_failure(now_ms, why)
        else:
            self.disabled = True        # deliberate shutdown, not a failure

    # ---- frame I/O ------------------------------------------------------
    def _send_frame(self, op, sid, payload=b""):
        if self.sock is None:
            return
        try:
            data = _pack(op, sid, payload)
            mv = memoryview(data)
            total = 0
            while total < len(data):
                sent = self.sock.write(mv[total:])
                if sent:
                    total += sent
        except Exception as e:
            self._disconnect(time.ticks_ms(), "write failed: %s" % e)

    def handle_readable(self, server):
        """Drain the socket and dispatch every complete frame it yielded."""
        if self.sock is None:
            return
        now = time.ticks_ms()
        try:
            chunk = self.sock.read(2048)
        except OSError:
            return                      # EAGAIN on a non-blocking socket
        if chunk is None:
            return
        if not chunk:
            self._disconnect(now, "relay closed the connection")
            return

        self._last_rx_ms = now
        self._rx.extend(chunk)
        while len(self._rx) >= HEADER_LEN:
            length = (self._rx[3] << 8) | self._rx[4]
            if length > MAX_PAYLOAD:
                self._disconnect(now, "oversized frame (%d)" % length)
                return
            if len(self._rx) < HEADER_LEN + length:
                break                   # rest of this frame hasn't arrived yet
            op = self._rx[0]
            sid = (self._rx[1] << 8) | self._rx[2]
            payload = bytes(self._rx[HEADER_LEN:HEADER_LEN + length])
            del self._rx[:HEADER_LEN + length]
            self._dispatch(server, op, sid, payload)
            if self.sock is None:
                return                  # _dispatch tore the connection down

    def _dispatch(self, server, op, sid, payload):
        if op == OP_DATA:
            st = self.streams.get(sid)
            if st is not None:
                st._feed(payload)
            return

        if op == OP_OPEN:
            if len(self.streams) >= self.cfg["max_streams"]:
                # Shed load rather than run out of RAM mid-response.
                print("tunnel: stream limit reached; refusing %d" % sid)
                self._send_frame(OP_CLOSE, sid)
                return
            self.streams[sid] = TunnelStream(self, sid)
            return

        if op == OP_FLUSH:
            st = self.streams.get(sid)
            if st is not None:
                self._serve_stream(server, st, payload)
            return

        if op == OP_CLOSE:
            self._stream_closed(sid, notify=False)
            return

        if op == OP_PING:
            self._send_frame(OP_PONG, 0, payload)
            return

        if op == OP_PONG:
            return

        print("tunnel: unknown op 0x%02x" % op)

    def _serve_stream(self, server, st, addr_hint):
        """
        A complete unit arrived: either a whole HTTP request, or one WebSocket
        frame on an already-upgraded stream. Either way it goes to the same
        webserver handler a LAN client would hit.
        """
        try:
            if st.upgraded:
                server._handle_ws(st)
            else:
                server._serve(st, addr_hint or b"tunnel")
        except Exception as e:
            print("tunnel: stream %d failed: %s" % (st.sid, e))
            try:
                st.close()
            except Exception:
                pass
            return
        st.flush()

    def _stream_closed(self, sid, notify):
        st = self.streams.pop(sid, None)
        if st is None:
            return
        st.closed = True
        if notify:
            self._send_frame(OP_CLOSE, sid)

    def shutdown(self):
        if self.sock is not None:
            self._disconnect(time.ticks_ms(), "shutting down", retry=False)
