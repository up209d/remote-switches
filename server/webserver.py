import socket
import select
import time
import json

from server import state
from server import static_files
from server import ws_protocol as ws
from server.metrics import get_pico_state
from server.pins import read_pins, apply_pin_command, tick_pins
from server.tunnel import Tunnel

WS_PATH = "/api/ws/health"

CORS_HEADERS = (
    "Access-Control-Allow-Origin: *\r\n"
    "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
    "Access-Control-Allow-Headers: Content-Type\r\n"
)


class PicoServer:
    """
    Hybrid server:
      - WebSocket  /ws/health -> live stats + LED state, pushed periodically
      - GET        /health    -> same snapshot as a one-shot JSON response
      - POST       /blink      -> LED / blink control (traditional request)
      - static web app files from www/

    Single-threaded, non-blocking accept loop; LED blinking keeps ticking
    between events.
    """

    def __init__(self, wlan, ip, led, config):
        self.wlan = wlan
        self.ip = ip
        self.led = led
        self.cfg = config

        self.clients = {}          # id(sock) -> sock (WebSocket clients)
        self._last_stats_ms = 0

        # Optional outbound reverse tunnel, so the device is reachable from the
        # internet through NAT. Off unless settings.json enables it.
        self.tunnel = None
        if config.TUNNEL.get("enabled") and config.TUNNEL.get("host"):
            self.tunnel = Tunnel(config.TUNNEL, ip)

        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(('0.0.0.0', config.HTTP_PORT))
        self.server.listen(4)
        self.server.setblocking(False)

        self.poller = select.poll()
        self.poller.register(self.server, select.POLLIN)

    # ---- payloads -------------------------------------------------------
    def _state(self):
        return {
            "stats": get_pico_state(self.wlan, self.ip),
            "led": self.led.state(),
            "pins": read_pins(),
        }

    def _ws_payload(self):
        state = self._state()
        state["type"] = "stats"
        return json.dumps(state)

    # ---- websocket client bookkeeping ----------------------------------
    def _register_ws(self, conn):
        self.clients[id(conn)] = conn
        # Tunnelled streams have no file descriptor, so they can't be polled —
        # the tunnel wakes them instead. Everything else is a real socket.
        if getattr(conn, "pollable", True):
            self.poller.register(conn, select.POLLIN)
        else:
            conn.upgraded = True
        try:
            static_files.write_all(conn, ws.encode(self._ws_payload()))  # initial snapshot
        except OSError:
            self._drop_ws(conn)

    def _drop_ws(self, conn):
        self.clients.pop(id(conn), None)
        try:
            self.poller.unregister(conn)
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass

    def _broadcast(self, payload):
        frame = ws.encode(payload)
        for conn in list(self.clients.values()):
            try:
                static_files.write_all(conn, frame)
            except OSError:
                self._drop_ws(conn)

    def _handle_ws(self, conn):
        opcode, payload = ws.decode(conn)
        if opcode is None or opcode == ws.OP_CLOSE:
            self._drop_ws(conn)
            print("WebSocket client disconnected")
            return
        if opcode == ws.OP_PING:
            try:
                static_files.write_all(conn, ws.encode(payload, opcode=ws.OP_PONG))
            except OSError:
                self._drop_ws(conn)
        # We don't expect data messages from the client on this channel.

    # ---- tunnel plumbing ------------------------------------------------
    def _service_tunnel(self, sock):
        """Drain the tunnel socket; drop it from the poller if it died."""
        self.tunnel.handle_readable(self)
        if self.tunnel.sock is not sock:
            self._repoll_tunnel(sock)

    def _repoll_tunnel(self, old_sock):
        if old_sock is not None:
            try:
                self.poller.unregister(old_sock)
            except Exception:
                pass
            # A dropped tunnel takes its WebSocket streams with it.
            for key, conn in list(self.clients.items()):
                if not getattr(conn, "pollable", True) and conn.closed:
                    self.clients.pop(key, None)
        if self.tunnel.sock is not None:
            self.poller.register(self.tunnel.sock, select.POLLIN)

    # ---- HTTP responses -------------------------------------------------
    def _send(self, conn, status, content_type, body, extra=""):
        if isinstance(body, str):
            body = body.encode()
        static_files.write_all(conn, (
            "HTTP/1.1 %s\r\n"
            "Content-Type: %s\r\n"
            "%s"
            "%s"
            "Connection: close\r\n"
            "Content-Length: %d\r\n\r\n" % (status, content_type, CORS_HEADERS, extra, len(body))
        ))
        if body:
            static_files.write_all(conn, body)

    def _send_json(self, conn, obj, status="200 OK"):
        self._send(conn, status, "application/json", json.dumps(obj))

    # ---- request parsing ------------------------------------------------
    def _read_request(self, conn):
        conn.setblocking(True)
        conn.settimeout(5)
        try:
            data = conn.recv(1024)
        except OSError:
            return None
        if not data:
            return None

        while b"\r\n\r\n" not in data and len(data) < 8192:
            try:
                chunk = conn.recv(1024)
            except OSError:
                break
            if not chunk:
                break
            data += chunk

        header_part, _, body = data.partition(b"\r\n\r\n")
        lines = header_part.decode('utf-8', 'ignore').split('\r\n')
        parts = lines[0].split(' ') if lines else []
        method = parts[0] if parts else "GET"
        path = parts[1] if len(parts) > 1 else "/"

        headers = {}
        for line in lines[1:]:
            if ':' in line:
                k, v = line.split(':', 1)
                headers[k.strip().lower()] = v.strip()

        try:
            clen = int(headers.get('content-length', '0'))
        except ValueError:
            clen = 0
        while len(body) < clen:
            try:
                chunk = conn.recv(min(1024, clen - len(body)))
            except OSError:
                break
            if not chunk:
                break
            body += chunk

        return method, path, headers, body

    # ---- connection handling -------------------------------------------
    def _accept(self):
        try:
            conn, addr = self.server.accept()
        except OSError:
            return
        self._serve(conn, addr)

    def _serve(self, conn, addr):
        """
        Handle one client connection start to finish.

        `conn` only has to look like a socket (recv/send/settimeout/close), so
        this same routing serves LAN sockets and tunnelled streams alike — see
        server/tunnel.py:TunnelStream.
        """
        parsed = self._read_request(conn)
        if not parsed:
            try:
                conn.close()
            except Exception:
                pass
            return
        method, path, headers, body = parsed
        route = path.split("?", 1)[0]

        # WebSocket upgrade -> keep the connection open, don't close it
        is_ws = (headers.get('upgrade', '').lower() == 'websocket'
                 and 'sec-websocket-key' in headers)
        if is_ws and route == WS_PATH:
            try:
                static_files.write_all(conn, ws.handshake_response(headers['sec-websocket-key']))
            except OSError:
                conn.close()
                return
            conn.settimeout(None)
            self._register_ws(conn)
            print("WebSocket client connected:", addr)
            return

        # Plain HTTP request -> respond and close
        try:
            if method == "OPTIONS":
                self._send(conn, "204 No Content", "text/plain", b"")
            elif route == "/api/health" and method == "GET":
                snap = self._state()
                snap["status"] = "ok"
                self._send_json(conn, snap)
            elif route == "/api/blink" and method == "POST":
                self._handle_blink(conn, body)
            elif route == "/api/pin" and method == "POST":
                self._handle_pin(conn, body)
            elif route.startswith("/api/"):
                # Unknown API route: don't fall through to the SPA.
                self._send_json(conn, {"error": "not found"}, status="404 Not Found")
            elif method == "GET":
                gzip_ok = 'gzip' in headers.get('accept-encoding', '')
                static_files.serve(conn, route, gzip_ok)
            else:
                self._send_json(conn, {"error": "not found"}, status="404 Not Found")
        except OSError as e:
            print("Request error:", e)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _handle_blink(self, conn, body):
        try:
            msg = json.loads(body.decode('utf-8', 'ignore')) if body else {}
        except Exception:
            self._send_json(conn, {"error": "invalid json"}, status="400 Bad Request")
            return
        if not self.led.apply_command(msg, self.cfg):
            self._send_json(conn, {"error": "unknown command"}, status="400 Bad Request")
            return
        # Respond to the requester...
        self._send_json(conn, {"status": "ok", "led": self.led.state()})
        # ...and push the new state to all live WebSocket clients right away.
        self._broadcast(self._ws_payload())
        state.save(self.led)

    def _handle_pin(self, conn, body):
        try:
            msg = json.loads(body.decode('utf-8', 'ignore')) if body else {}
        except Exception:
            self._send_json(conn, {"error": "invalid json"}, status="400 Bad Request")
            return
        # Accept one command or a batch (e.g. "release all").
        cmds = msg if isinstance(msg, list) else [msg]
        if not cmds or not all(apply_pin_command(c) for c in cmds):
            self._send_json(conn, {"error": "unknown command"}, status="400 Bad Request")
            return
        self._send_json(conn, {"status": "ok", "pins": read_pins()})
        self._broadcast(self._ws_payload())
        state.save(self.led)

    # ---- main loop ------------------------------------------------------
    def run(self):
        print("Web server ready. Open http://%s/" % self.ip)
        self._last_stats_ms = time.ticks_ms()
        while True:
            try:
                events = self.poller.poll(self.cfg.POLL_TIMEOUT_MS)
                for sock, _flag in events:
                    if sock is self.server:
                        self._accept()
                    elif self.tunnel is not None and self.tunnel.owns(sock):
                        self._service_tunnel(sock)
                    elif id(sock) in self.clients:
                        self._handle_ws(sock)

                now = time.ticks_ms()
                self.led.tick(now)

                # Expire momentary holds / pulses; push state immediately if a
                # pin auto-reverted so the UI reflects it without waiting for
                # the next periodic stats broadcast.
                if tick_pins(now) and self.clients:
                    self._broadcast(self._ws_payload())
                    self._last_stats_ms = now

                if self.clients and time.ticks_diff(now, self._last_stats_ms) >= self.cfg.STATS_INTERVAL_MS:
                    self._broadcast(self._ws_payload())
                    self._last_stats_ms = now

                # Connect / reconnect the tunnel, keep it alive, and flush any
                # bytes the broadcasts above buffered. This must come AFTER the
                # broadcasts: flushing first would leave a stats frame sitting
                # in a tunnel buffer until the next loop pass. The socket is
                # swapped out on every reconnect, so re-register the poller
                # whenever service() reports a change.
                if self.tunnel is not None:
                    was = self.tunnel.sock
                    if self.tunnel.service(self, now) or was is not self.tunnel.sock:
                        self._repoll_tunnel(was)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print("Loop error:", e)

        self.shutdown()

    def shutdown(self):
        for conn in list(self.clients.values()):
            self._drop_ws(conn)
        if self.tunnel is not None:
            self.tunnel.shutdown()
        try:
            self.server.close()
        except Exception:
            pass
        self.led.set(False)
        print("Server stopped.")
