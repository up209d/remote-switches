# ==========================================
# Outbound reverse tunnel to an uptunnel server
# ==========================================
#
# Problem: the Pico sits behind NAT on a home LAN, so nothing on the internet
# can dial in to it. Solution: the Pico dials *out* to an uptunnel server you
# run on a host with a fixed DNS name, and holds that connection open. The
# server fronts a public listener at https://<subdomain>.<its domain> and
# forwards everything it receives down that already-open socket.
#
# Nothing about the Pico's own serving changes. A request arriving through the
# tunnel is handed to exactly the same handlers that serve LAN clients, via a
# socket-lookalike object (TunnelStream), so the device keeps serving its own
# web app, its own static files and its own WebSocket. The server stays a dumb
# pipe — it holds no UI and knows nothing about /api.
#
# Transport: ONE WebSocket to wss://<host>/control carrying binary frames
#
#     type:uint8 | stream_id:uint32 big-endian (types >= 0x20 only) | payload
#
# WebSocket already delimits messages, so frames carry no length of their own.
# This is the fourth implementation of uptunnel wire protocol v1, after the Node
# server and the Node and Python agents; docs/TUNNEL_PROTOCOL.md is the contract
# it is written against, not this file.

import json
import socket
import time

from server import watchdog
from server import ws_client
from server import ws_protocol as ws
from server.tunnel_log import log

PROTOCOL_VERSION = 1
CLIENT_ID = "uptunnel-pico/1"

# ---- frame types (keep in sync with docs/TUNNEL_PROTOCOL.md) ---------------
HELLO = 0x01        # device -> server: authenticate
HELLO_OK = 0x02     # server -> device: authenticated
ERROR = 0x03        # both: something was refused
OPEN_TUNNEL = 0x10  # device -> server: claim a public subdomain
TUNNEL_OK = 0x11    # server -> device: subdomain is live
CLOSE_TUNNEL = 0x12 # device -> server: release a subdomain
STREAM_OPEN = 0x20  # server -> device: a public client connected
STREAM_DATA = 0x21  # both: payload bytes for a stream
STREAM_EOF = 0x22   # both: no more data in this direction
STREAM_ACK = 0x23   # both: n bytes consumed, credit them back
STREAM_RESET = 0x24 # both: abort this stream

_STREAM_FLOOR = 0x20        # types below this are connection-level, with no id

_OUT_CHUNK = 1024           # coalesce small writes into fuller frames
_READ_CHUNK = 1024
_TX_HIGH_WATER = 4096       # queued bytes past which a writer has to wait
_TX_STALL_MS = 5000         # ...and how long it waits before we give up

# errnos meaning "not now, try again": EAGAIN, plus mbedtls' WANT_READ and
# WANT_WRITE, which a non-blocking TLS socket raises mid-record.
_RETRY = (11, -26880, -26752)

# Connection lifecycle
_IDLE = 0                   # not connected, waiting out the reconnect backoff
_AUTH = 1                   # socket up, HELLO sent, waiting for HELLO_OK
_UP = 2                     # authenticated and carrying streams


def _control(frame_type, body):
    return bytes((frame_type,)) + json.dumps(body).encode()


def _stream(frame_type, sid, payload=b""):
    return bytes((frame_type, (sid >> 24) & 0xFF, (sid >> 16) & 0xFF,
                  (sid >> 8) & 0xFF, sid & 0xFF)) + payload


def _u32(buf, i=0):
    return (buf[i] << 24) | (buf[i + 1] << 16) | (buf[i + 2] << 8) | buf[i + 3]


def _u32b(n):
    return bytes(((n >> 24) & 0xFF, (n >> 16) & 0xFF, (n >> 8) & 0xFF, n & 0xFF))


def _parse_url(url):
    """(host, port, path, tls) from ws://host[:port][/path] or wss://..."""
    scheme, _, rest = url.partition("://")
    if scheme not in ("ws", "wss"):
        raise ValueError("tunnel.server must start with ws:// or wss://")
    tls = scheme == "wss"
    hostport, _, path = rest.partition("/")
    host, _, port = hostport.partition(":")
    if not host:
        raise ValueError("tunnel.server has no host")
    return host, int(port) if port else (443 if tls else 80), "/" + path, tls


def _request_complete(buf):
    """
    Has a whole HTTP request landed in `buf` — head, blank line, and all of the
    body Content-Length promises?

    This is the load-bearing check. The device is single-threaded, so a handler
    that blocked waiting for more bytes would have to pump the tunnel socket
    from inside itself. Instead nothing is dispatched until everything the
    handler will read is already in memory, and recv() never blocks.

    Chunked request bodies are not recognised (browsers don't use them for the
    small JSON bodies /api takes); such a request simply waits for its EOF.
    """
    end = buf.find(b"\r\n\r\n")
    if end < 0:
        return False
    head = bytes(buf[:end]).lower()
    at = head.find(b"\ncontent-length:")
    if at < 0:
        return True
    value = head[at + 16:]
    nl = value.find(b"\r")
    try:
        length = int(value if nl < 0 else value[:nl])
    except ValueError:
        length = 0
    return len(buf) - (end + 4) >= length


class TunnelStream:
    """
    A socket-lookalike for one tunnelled client connection.

    This exists so `webserver._serve()`, `static_files.serve()` and
    `ws_protocol` can drive a tunnelled client with the *same* code that drives
    a LAN socket — only the methods those modules actually call are needed:
    recv/send/write/setblocking/settimeout/close.

    Reads never block: the tunnel buffers a whole request (or a whole WebSocket
    frame) before it runs a handler, so everything the handler wants to read is
    already in `_in`. That is what keeps this single-threaded design free of
    re-entrancy.
    """

    pollable = False        # tells _register_ws not to put this in select.poll

    def __init__(self, tunnel, sid, credit, peer=b"tunnel"):
        self._tunnel = tunnel
        self.sid = sid
        self.peer = peer
        self._in = bytearray()
        self._out = bytearray()
        # Bytes we may still send before the server acks. See "Flow control" in
        # docs/TUNNEL_PROTOCOL.md.
        self.credit = credit
        self.closed = False
        self.upgraded = False       # became a WebSocket via the 101 handshake

    # ---- inbound (server -> handler) -------------------------------------
    def _feed(self, data):
        self._in.extend(data)

    def recv(self, n):
        if not self._in:
            return b""              # reads as EOF, which is what we want
        take = min(n, len(self._in))
        chunk = bytes(self._in[:take])
        # Reslice rather than `del buf[:n]` — MicroPython's bytearray has no
        # item deletion at all. Same everywhere else a buffer is consumed.
        self._in = self._in[take:]
        return chunk

    # ---- outbound (handler -> server) ------------------------------------
    def send(self, data):
        """
        Buffer bytes for the server. Returns the count "sent", as
        static_files.write_all() expects — we always accept everything, so no
        short-write loop is needed here.
        """
        if self.closed:
            return len(data)
        self._out.extend(data)
        while len(self._out) >= _OUT_CHUNK and self.credit > 0:
            self._emit(_OUT_CHUNK)
        return len(data)

    write = send                    # some callers use write() instead

    def _emit(self, count):
        chunk = bytes(self._out[:count])
        self._out = self._out[count:]
        self.credit -= count
        self._tunnel._send(_stream(STREAM_DATA, self.sid, chunk))

    def flush(self):
        while self._out and self.credit > 0:
            self._emit(min(_OUT_CHUNK, len(self._out)))

    def add_credit(self, granted):
        self.credit += granted

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
        self._tunnel._stream_gone(self.sid, eof=True)


class Tunnel:
    """
    Owns the single outbound WebSocket and demultiplexes streams on it.

    The webserver drives this: it registers `sock` with its poller, calls
    service() once per loop pass, and handle_readable() when the socket has
    data. All callbacks land back on the webserver, so routing lives in exactly
    one place.
    """

    def __init__(self, cfg_tunnel, device_ip="", local_port=80):
        self.cfg = cfg_tunnel
        self.device_ip = device_ip
        self.local_port = local_port
        self.sock = None
        self.state = _IDLE
        self.streams = {}
        self.tunnel_id = ""         # set by TUNNEL_OK; the routing key
        self.public_url = ""
        self.window = 65536         # until HELLO_OK tells us the real one
        self._rx = bytearray()      # socket bytes -> WebSocket frames
        self._msg = bytearray()     # WebSocket fragments -> one uptunnel frame
        self._tx = bytearray()      # frames waiting for the socket to take them
        self._pending = b""         # the exact bytes a blocked write must retry
        self._next_attempt_ms = 0
        self._backoff_ms = cfg_tunnel["reconnect_min_ms"]
        self._last_rx_ms = 0
        self._last_ping_ms = 0
        self._last_pong_ms = 0      # answers to *our* pings, not just any byte
        self._ping_seq = 0
        self._auth_since_ms = 0
        self._up_since_ms = 0       # set by TUNNEL_OK; drives the backoff reset
        self._last_hb_log_ms = 0
        # Set once the tunnel has given up for this boot (see _after_failure).
        # Nothing clears it but a restart, so the event loop stops paying the
        # blocking-connect cost entirely.
        self.disabled = False

        try:
            self.host, self.port, self.path, self.tls = _parse_url(cfg_tunnel["server"])
        except ValueError as e:
            log("tunnel: %s — tunnel disabled" % e)
            self.host = self.path = ""
            self.port = 0
            self.tls = False
            self.disabled = True
        if not cfg_tunnel.get("subdomain"):
            log("tunnel: no subdomain configured — tunnel disabled")
            self.disabled = True

    # ---- status ---------------------------------------------------------
    @property
    def connected(self):
        return self.state == _UP

    def owns(self, sock):
        return self.sock is not None and sock is self.sock

    def snapshot(self):
        """
        Tunnel health for /api/health and the stats WebSocket.

        Reported over the LAN on purpose: when the public URL 502s, this is what
        tells you whether the device thinks it is connected — which is the whole
        difference between "the relay dropped us" and "we never noticed".

        Not persisted. Every field here is per-session by design; see
        docs/TUNNEL_PROTOCOL.md §8.
        """
        now = time.ticks_ms()
        return {
            "connected": self.state == _UP and bool(self.tunnel_id),
            "public_url": self.public_url,
            "lan_ip": self.device_ip,
            "disabled": self.disabled,
            "backoff_ms": self._backoff_ms,
            "up_ms": time.ticks_diff(now, self._up_since_ms) if self._up_since_ms else 0,
            "since_pong_ms": time.ticks_diff(now, self._last_pong_ms) if self.sock else -1,
        }

    # ---- connect / disconnect -------------------------------------------
    def fail(self, now_ms, why):
        """
        Tear the connection down from outside, for a reason the tunnel itself
        did not detect. The webserver calls this when servicing us raised: the
        socket has to go, or the poller and this object disagree about what is
        live and the connection sits there forever.
        """
        if self.sock is None:
            return
        self._disconnect(now_ms, why)

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

        if self.state == _AUTH:
            if time.ticks_diff(now_ms, self._auth_since_ms) >= self.cfg["connect_timeout_ms"]:
                self._disconnect(now_ms, "no HELLO_OK from the server")
                return True
            self._drain()
            return self.sock is None

        # Liveness first, before anything that can raise or block. _drain() used
        # to run ahead of these checks, which meant a drain that threw on every
        # pass kept the connection nominally alive forever.
        if self._check_liveness(now_ms):
            return True

        self._drain()
        if self.sock is None:                   # _drain tore it down
            return True

        for st in list(self.streams.values()):
            st.flush()
        return False

    def _check_liveness(self, now_ms):
        """
        Decide whether this connection is still worth keeping. Returns True if
        it was torn down.

        Three separate tests, because each catches something the others miss:
        bytes arriving proves the socket works, a pong proves the *server* is
        still processing us, and a tunnel id proves the public side can still
        route to us. A session can pass the first and fail the other two — that
        is the 502-with-a-happy-device case.
        """
        # Keepalive: probe periodically, and give up if the server goes quiet.
        # Both ends ping; ours is what notices a black-holed link promptly,
        # where TCP alone would sit there for minutes.
        if time.ticks_diff(now_ms, self._last_ping_ms) >= self.cfg["keepalive_ms"]:
            self._last_ping_ms = now_ms
            self._ping_seq = (self._ping_seq + 1) & 0xFFFFFFFF
            # A sequenced payload comes back in the pong, so the round trip is
            # measurable and an old pong cannot vouch for a new ping.
            self._push(ws_client.encode(_u32b(self._ping_seq), ws.OP_PING))
            if self.sock is None:
                return True         # _push gave up on a socket that stopped reading

        if time.ticks_diff(now_ms, self._last_rx_ms) >= self.cfg["idle_timeout_ms"]:
            self._disconnect(now_ms, "server went silent")
            return True

        if time.ticks_diff(now_ms, self._last_pong_ms) >= self.cfg["idle_timeout_ms"]:
            self._disconnect(now_ms, "server stopped answering pings")
            return True

        # Authenticated but never routable: OPEN_TUNNEL went out when HELLO_OK
        # landed and TUNNEL_OK never came back. Nothing can reach us, so the
        # session is worthless however healthy the socket looks.
        if not self.tunnel_id:
            if time.ticks_diff(now_ms, self._auth_since_ms) >= self.cfg["connect_timeout_ms"]:
                self._disconnect(now_ms, "no TUNNEL_OK from the server")
                return True
            return False

        # Past here the session is genuinely up.
        if (self._backoff_ms != self.cfg["reconnect_min_ms"]
                and time.ticks_diff(now_ms, self._up_since_ms) >= self.cfg["healthy_ms"]):
            # Earned it: a session that has held for healthy_ms is evidence the
            # trouble has passed, so the next blip retries promptly instead of
            # inheriting a backoff that only ever grew.
            self._backoff_ms = self.cfg["reconnect_min_ms"]
            log("tunnel: session healthy — reconnect backoff reset to %dms"
                % self._backoff_ms)

        hb = self.cfg["log_heartbeat_ms"]
        if hb and time.ticks_diff(now_ms, self._last_hb_log_ms) >= hb:
            self._last_hb_log_ms = now_ms
            # Written down on an interval so a gap in tunnel.log is itself
            # evidence: silence now means the loop stopped, not that all was well.
            log("tunnel: ok up=%ds pong=%dms streams=%d"
                % (time.ticks_diff(now_ms, self._up_since_ms) // 1000,
                   time.ticks_diff(now_ms, self._last_pong_ms),
                   len(self.streams)))
        return False

    def _connect(self, now_ms):
        # NOTE: this connect, the TLS handshake and the WebSocket handshake are
        # all BLOCKING. They can stall the event loop for up to
        # connect_timeout_ms, during which the LED pattern freezes and the
        # momentary-hold deadman in server/pins.py is delayed by the same
        # amount. That is the accepted tradeoff for MicroPython — a non-blocking
        # TLS handshake is not reliably supported. Backoff keeps the stall rare
        # when the server is down.
        log("tunnel: connecting to %s" % self.cfg["server"])
        s = None
        try:
            # Each step here can outlast the hardware watchdog's 8.4s ceiling on
            # its own, so the timer is fed between them. A hang *inside* one
            # step still reboots the board, which for an unbounded DNS lookup is
            # the outcome we want.
            watchdog.pet()
            # NOTE: getaddrinfo() is NOT covered by settimeout below, so a DNS
            # name that fails to resolve can stall longer than
            # connect_timeout_ms.
            addr = socket.getaddrinfo(self.host, self.port)[0][-1]
            watchdog.pet()
            s = socket.socket()
            s.settimeout(self.cfg["connect_timeout_ms"] / 1000)
            s.connect(addr)
            watchdog.pet()
            if self.tls:
                s = self._wrap_tls(s)
                watchdog.pet()
            ws_client.open_handshake(s, self.host, self.path)
            watchdog.pet()
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
        self.state = _AUTH
        self.streams = {}
        self.tunnel_id = ""
        self.public_url = ""
        self._rx = bytearray()
        self._msg = bytearray()
        self._tx = bytearray()
        self._pending = b""
        self._last_rx_ms = now_ms
        self._last_ping_ms = now_ms
        self._last_pong_ms = now_ms
        self._auth_since_ms = now_ms
        self._last_hb_log_ms = now_ms
        self._send(_control(HELLO, {
            "version": PROTOCOL_VERSION,
            "token": self.cfg["token"],
            "name": self.cfg.get("name") or "pico",
            "client": CLIENT_ID,
            # The board is headless, so its DHCP address is otherwise
            # unknowable. The server logs these; it never routes on them.
            "lanIp": self.device_ip,
            "lanPort": self.local_port,
        }))
        return True

    def _wrap_tls(self, s):
        import ssl
        # MicroPython's ssl defaults to CERT_NONE: this gives confidentiality,
        # NOT proof you reached the right server. The HELLO token is what
        # actually authenticates the device. See docs/TUNNEL_PROTOCOL.md.
        try:
            return ssl.wrap_socket(s, server_hostname=self.host)
        except TypeError:
            return ssl.wrap_socket(s)      # older builds lack server_hostname

    def _after_failure(self, now_ms, why):
        """
        Decide whether to try again, honouring the startup_only setting.

        With startup_only the tunnel gets exactly one chance per boot: on
        failure it switches off for good, so a misconfigured or absent server
        costs the event loop one stall at startup instead of a recurring one
        forever. The device carries on as a normal LAN device — and stays
        unreachable from the internet until it is restarted.
        """
        if self.cfg.get("startup_only"):
            self.disabled = True
            log("tunnel: %s — startup_only is set, so the tunnel stays off "
                "until this device restarts" % why)
            return
        self._next_attempt_ms = time.ticks_add(now_ms, self._backoff_ms)
        log("tunnel: %s — retrying in %dms" % (why, self._backoff_ms))
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
        self.public_url = ""
        # Cleared here as well as in _connect: a stale id left behind would make
        # the next session look routable before TUNNEL_OK had arrived.
        self.tunnel_id = ""
        self._rx = bytearray()
        self._msg = bytearray()
        self._tx = bytearray()
        self._pending = b""
        if retry:
            self._after_failure(now_ms, why)
        else:
            self.disabled = True        # deliberate shutdown, not a failure
            log("tunnel: %s — off until this device restarts" % why)

    # ---- frame I/O ------------------------------------------------------
    def _send(self, frame):
        """Queue one uptunnel frame, wrapped in a binary WebSocket frame."""
        self._push(ws_client.encode(frame))

    def _queued(self):
        """Bytes owed to the socket, whether snapshotted for retry or not."""
        return len(self._pending) + len(self._tx)

    def _push(self, data):
        if self.sock is None:
            return
        self._tx.extend(data)
        self._drain()
        if self._queued() <= _TX_HIGH_WATER:
            return
        # The queue is deeper than we are willing to hold, so stall the caller
        # until the socket catches up — the same backpressure a blocking LAN
        # socket applies inside static_files.write_all().
        #
        # The deadline measures time with NO progress, not total time spent
        # here. A 78KB bundle through this device's TLS stack legitimately
        # takes seconds of continuous stalling; only a socket that accepts
        # nothing at all for _TX_STALL_MS is actually dead.
        deadline = time.ticks_add(time.ticks_ms(), _TX_STALL_MS)
        queued = self._queued()
        while self.sock is not None and queued > _TX_HIGH_WATER:
            if time.ticks_diff(time.ticks_ms(), deadline) > 0:
                self._disconnect(time.ticks_ms(), "server stopped reading")
                return
            time.sleep_ms(2)
            self._soak()
            self._drain()
            left = self._queued()
            if left < queued:
                deadline = time.ticks_add(time.ticks_ms(), _TX_STALL_MS)
                queued = left

    def _soak(self):
        """
        Take bytes off the socket without dispatching them.

        Only called while a write is stalled, and it is what stops that stall
        deadlocking. TLS is bidirectional: mbedtls has to consume an incoming
        record — a session ticket or a key update arrives mid-transfer without
        anyone asking — before it will accept another write, so a writer that
        never reads eventually wedges for good. Leaving the receive window shut
        also silences the server's acks.

        Frames land in `_rx` and stay there for the event loop to dispatch.
        Running a handler from inside another handler is exactly the
        re-entrancy this design exists to avoid.
        """
        while self.sock is not None and len(self._rx) <= self.cfg["max_frame_bytes"]:
            try:
                chunk = self.sock.read(_READ_CHUNK)
            except OSError:
                return
            if not chunk:
                return              # nothing pending, or the peer went away
            self._last_rx_ms = time.ticks_ms()
            self._rx.extend(chunk)
            if len(chunk) < _READ_CHUNK:
                return

    def _drain(self):
        """
        Push queued bytes at the socket, one snapshot at a time.

        `_pending` is that snapshot, and it exists for one reason: when mbedtls
        cannot take a write it reports WANT_WRITE, and the retry MUST offer the
        *identical* buffer. Handing it a longer one — which is what happens if
        you just re-offer a queue that other code has appended to since — leaves
        it refusing forever, so the tail of a response is silently never sent.
        Only a call that actually consumed bytes lets us move on.
        """
        while self.sock is not None:
            if not self._pending:
                if not self._tx:
                    return
                self._pending = bytes(self._tx)
                self._tx = bytearray()
            try:
                sent = self.sock.write(self._pending)
            except OSError as e:
                if e.args[0] in _RETRY:
                    return
                self._disconnect(time.ticks_ms(), "write failed: %s" % e)
                return
            if not sent:
                return                  # blocked: retry these same bytes later
            self._pending = self._pending[sent:] if sent < len(self._pending) else b""

    def handle_readable(self, server):
        """
        Drain the socket and dispatch every complete frame it yielded.

        Reads until the socket is empty rather than once per poll wakeup: over
        TLS, bytes can already be sitting decrypted inside the SSL layer with
        nothing left on the TCP socket for poll() to report.
        """
        while self.sock is not None:
            now = time.ticks_ms()
            try:
                chunk = self.sock.read(_READ_CHUNK)
            except OSError as e:
                if e.args[0] in _RETRY:
                    return
                self._disconnect(now, "read failed: %s" % e)
                return
            if chunk is None:
                return                  # nothing more for now
            if not chunk:
                self._disconnect(now, "server closed the connection")
                return

            self._last_rx_ms = now
            self._rx.extend(chunk)
            self._consume(server, now)
            if len(chunk) < _READ_CHUNK:
                return                  # short read: the socket is drained

    def _consume(self, server, now):
        """Dispatch every whole WebSocket frame now sitting in `_rx`."""
        while self.sock is not None:
            total = ws.frame_len(self._rx)
            if total < 0:
                # Nothing complete yet. Bound what we will hold for one frame,
                # so a huge inbound unit can't exhaust the heap.
                if len(self._rx) > self.cfg["max_frame_bytes"]:
                    self._disconnect(now, "inbound frame over max_frame_bytes")
                return
            frame = ws.parse_frame(self._rx)
            self._rx = self._rx[total:]
            self._on_ws_frame(server, frame, now)

    def _on_ws_frame(self, server, frame, now):
        fin, opcode, payload, _ = frame
        if opcode == ws.OP_CLOSE:
            self._disconnect(now, "server sent a WebSocket close")
            return
        if opcode == ws.OP_PING:
            self._push(ws_client.encode(payload, ws.OP_PONG))
            return
        if opcode == ws.OP_PONG:
            # Distinct from _last_rx_ms: this is the server proving it still
            # reads and answers us, not merely that bytes reached the socket.
            self._last_pong_ms = now
            return
        if opcode == ws.OP_TEXT:
            self._disconnect(now, "text frame (the protocol is binary-only)")
            return

        # OP_BINARY, or OP_CONT continuing one. Reassemble before dispatch.
        if fin and not self._msg:
            self._dispatch(server, payload)
            return
        self._msg.extend(payload)
        if len(self._msg) > self.cfg["max_frame_bytes"]:
            self._disconnect(now, "fragmented frame over max_frame_bytes")
            return
        if fin:
            message = bytes(self._msg)
            self._msg = bytearray()
            self._dispatch(server, message)

    # ---- uptunnel frames -------------------------------------------------
    def _dispatch(self, server, frame):
        if not frame:
            return
        frame_type = frame[0]
        if frame_type < _STREAM_FLOOR:
            try:
                body = json.loads(frame[1:]) if len(frame) > 1 else {}
            except ValueError:
                log("tunnel: malformed JSON in frame 0x%02x" % frame_type)
                return
            self._on_control(frame_type, body)
            return
        if len(frame) < 5:
            log("tunnel: stream frame 0x%02x is missing its id" % frame_type)
            return
        self._on_stream(server, frame_type, _u32(frame, 1), frame[5:])

    def _on_control(self, frame_type, body):
        if frame_type == HELLO_OK:
            self.state = _UP
            self.window = int(body.get("streamWindow", self.window))
            log("tunnel: authenticated as %s (window %dKiB)"
                % (body.get("agentId", "?"), self.window // 1024))
            self._send(_control(OPEN_TUNNEL, {
                "reqId": "1",
                "kind": "http",
                "subdomain": self.cfg["subdomain"],
                # Informational for the server — we are our own local target.
                "target": {"host": self.device_ip or "127.0.0.1",
                           "port": self.local_port},
            }))
            return

        if frame_type == TUNNEL_OK:
            self.tunnel_id = str(body.get("tunnelId", ""))
            self.public_url = body.get("publicUrl", "")
            self._up_since_ms = time.ticks_ms()
            self._last_hb_log_ms = self._up_since_ms
            log("tunnel: up at %s" % (self.public_url or self.tunnel_id))
            return

        if frame_type == ERROR:
            code = body.get("code", "error")
            now = time.ticks_ms()
            log("tunnel: server refused: %s (%s)" % (body.get("message", ""), code))
            if code == "bad_version":
                # A protocol mismatch is genuinely unfixable by retrying: the
                # binary on either side has to change first.
                self._disconnect(now, code, retry=False)
                return
            if code == "unauthorized":
                # Deliberately NOT permanent. A relay restarted before its token
                # file loaded, a rolled-back deploy, or another service briefly
                # answering on the hostname all produce this — and a device that
                # switches itself off for the boot then needs a physical power
                # cycle. Retry at the ceiling: slow enough to cost nothing, and
                # it self-heals when the server does.
                self._disconnect(now, code)
                self._backoff_ms = self.cfg["reconnect_max_ms"]
                self._next_attempt_ms = time.ticks_add(now, self._backoff_ms)
                return
            # Anything else: drop and come back on the backoff. This used to be
            # ignored once tunnel_id was set, which left the device sitting in a
            # session the public side could no longer route to.
            self._disconnect(now, code)
            return

        log("tunnel: ignoring control frame 0x%02x" % frame_type)

    def _on_stream(self, server, frame_type, sid, payload):
        if frame_type == STREAM_OPEN:
            self._open_stream(sid, payload)
            return

        st = self.streams.get(sid)
        if st is None:
            # The server may still be draining a stream we already tore down.
            if frame_type != STREAM_RESET:
                self._send(_stream(STREAM_RESET, sid,
                                   json.dumps({"code": "unknown_stream"}).encode()))
            return

        if frame_type == STREAM_DATA:
            st._feed(payload)
            # We have taken the bytes, so credit them back straight away; the
            # server pauses the public socket without this.
            self._send(_stream(STREAM_ACK, sid, _u32b(len(payload))))
            self._pump(server, st)
        elif frame_type == STREAM_ACK:
            if len(payload) >= 4:
                st.add_credit(_u32(payload))
                st.flush()
        elif frame_type == STREAM_EOF:
            # Half-close: the public client has said its piece. Anything still
            # unparsed was an incomplete request, so there is nothing to serve.
            if not st.upgraded:
                self._finish(server, sid)
        elif frame_type == STREAM_RESET:
            self._finish(server, sid, eof=False)
        else:
            log("tunnel: ignoring stream frame 0x%02x" % frame_type)

    def _open_stream(self, sid, payload):
        try:
            meta = json.loads(payload) if payload else {}
        except ValueError:
            meta = {}
        if self.tunnel_id and str(meta.get("tunnelId", "")) != self.tunnel_id:
            self._send(_stream(STREAM_RESET, sid,
                               json.dumps({"code": "unknown_tunnel"}).encode()))
            return
        if len(self.streams) >= self.cfg["max_streams"]:
            # Shed load rather than run out of RAM mid-response.
            log("tunnel: stream limit reached; refusing %d" % sid)
            self._send(_stream(STREAM_RESET, sid,
                               json.dumps({"code": "too_many_streams"}).encode()))
            return
        peer = meta.get("remoteAddr", "tunnel")
        self.streams[sid] = TunnelStream(self, sid, self.window, peer)

    def _pump(self, server, st):
        """
        Run every complete unit sitting in the stream's buffer.

        Before the WebSocket upgrade a unit is one whole HTTP request; after it,
        one whole client WebSocket frame. Either way it goes to the same
        webserver handler a LAN client would hit.
        """
        while not st.closed:
            if st.upgraded:
                if ws.frame_len(st._in) < 0:
                    return
                try:
                    server._handle_ws(st)
                except Exception as e:
                    log("tunnel: stream %d ws failed: %s" % (st.sid, e))
                    self._finish(server, st.sid)
                    return
            else:
                if not _request_complete(st._in):
                    return
                try:
                    server._serve(st, st.peer)
                except Exception as e:
                    log("tunnel: stream %d failed: %s" % (st.sid, e))
                    self._finish(server, st.sid)
                    return
                st.flush()

    def _finish(self, server, sid, eof=True):
        """Tear a stream down, telling the webserver if it had adopted it."""
        st = self.streams.get(sid)
        if st is None:
            return
        if st.upgraded and not st.closed:
            # Registered as a WebSocket client: the webserver has to forget it
            # too, or it keeps broadcasting into a dead stream forever.
            st.closed = True
            self.streams.pop(sid, None)
            server._drop_ws(st)
            if eof:
                self._send(_stream(STREAM_EOF, sid))
            return
        st.closed = True
        self._stream_gone(sid, eof)

    def _stream_gone(self, sid, eof):
        if self.streams.pop(sid, None) is None:
            return
        if eof and self.sock is not None:
            self._send(_stream(STREAM_EOF, sid))

    def shutdown(self):
        if self.sock is not None:
            try:
                self._push(ws_client.encode(b"\x03\xe9", ws.OP_CLOSE))   # 1001
            except Exception:
                pass
            self._disconnect(time.ticks_ms(), "shutting down", retry=False)
