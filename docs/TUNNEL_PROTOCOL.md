# Reverse tunnel protocol (v1)

The device sits behind NAT, so it dials **out** to a relay you run on a server
with a fixed IP / DNS name and holds that connection open. The relay fronts a
public listener and forwards everything it receives down that socket.

**The relay is a dumb pipe.** It serves no UI, holds no state about the device,
and knows nothing about `/api`. The device keeps serving its own web app, its
own static files and its own WebSocket — a tunnelled request is handed to the
exact same handlers a LAN client hits (`webserver._serve`), through a
socket-lookalike (`tunnel.TunnelStream`).

Device side: `server/tunnel.py`. Config: the `tunnel` block in `settings.json`
(documented key-by-key in `server/config.py`).

---

## 1. Transport

One TCP connection per device, optionally wrapped in TLS, device → relay. Not
WebSocket: both ends are your own code, so the handshake, client-side masking
and fragmentation rules would be pure overhead.

Every frame:

```
 0        1                   3                   5
 +--------+-------------------+-------------------+-----------------+
 |   op   |     stream_id     |      length       |     payload     |
 | uint8  |  uint16 (BE)      |   uint16 (BE)     |  length bytes   |
 +--------+-------------------+-------------------+-----------------+
```

- `length` **must not exceed 1024** (`tunnel.MAX_PAYLOAD`). The device drops the
  connection on an oversized frame rather than allocating unbounded RAM.
- `stream_id` is `0` for connection-level frames (HELLO, READY, PING, PONG).
- The **relay allocates** stream ids, one per public client connection. Reusing
  an id before its CLOSE is a protocol violation.

## 2. Opcodes

| op | Name | Direction | Meaning |
|----|------|-----------|---------|
| `0x10` | HELLO | device → relay | Authenticate + identify. First frame, always. |
| `0x11` | READY | relay → device | Auth accepted. Device carries no traffic until this arrives. |
| `0x01` | OPEN | relay → device | A new public client connection begins on `stream_id`. |
| `0x02` | DATA | both | Raw bytes belonging to `stream_id`. |
| `0x06` | FLUSH | relay → device | The bytes sent so far form a complete, dispatchable unit. |
| `0x03` | CLOSE | both | This stream is finished. |
| `0x04` | PING | both | Keepalive probe. Reply with PONG, echoing the payload. |
| `0x05` | PONG | both | Keepalive reply. |

## 3. Handshake

Device sends `HELLO` with a JSON payload:

```json
{"token": "<shared secret>", "device_id": "pico-e6614c311b8e9a2f", "lan_ip": "192.168.1.50", "proto": 1}
```

The relay **must** reject any device whose token is not the expected one, by
closing the TCP connection (optionally sending a non-READY frame with a reason
first — the device logs the payload). On success it replies `READY` with an
empty payload.

`device_id` defaults to `pico-<machine.unique_id() hex>`, so one identical
`settings.json` can be deployed across a whole fleet and each board still gets a
distinct, stable identity. It is the routing key — see §6.

## 4. Why FLUSH exists

This is the load-bearing rule, and the relay must get it right.

The device is single-threaded and the tunnel is one socket. If a handler could
block waiting for more bytes, it would have to pump the tunnel socket from
inside itself — re-entrancy this design does not support.

So: **the relay buffers a complete unit before it can be dispatched, then sends
FLUSH.** The device buffers DATA and only runs a handler on FLUSH, at which
point everything the handler needs to read is already in memory and `recv()`
never blocks.

A "complete unit" means:

- **Before the WebSocket upgrade** — a whole HTTP request: request line, all
  headers, `\r\n\r\n`, and exactly `Content-Length` bytes of body. Send
  `OPEN` → `DATA`… → `FLUSH`.
- **After the upgrade** — exactly one WebSocket frame, forwarded **verbatim,
  still masked**. The device's `ws_protocol.decode()` unmasks it, byte-identical
  to the LAN path. One `FLUSH` per frame. Do not coalesce two frames into one
  FLUSH, and do not split one frame across two.

FLUSH's payload may carry a short client address hint for logging, or be empty.

## 5. Response direction

Device → relay is plain `DATA` on the stream, ending in `CLOSE`. There is no
FLUSH in this direction: the relay writes bytes straight through to the public
client socket as they arrive.

The device writes real HTTP — status line, headers, body — and real WebSocket
frames (unmasked, as a server must). So the relay never parses a response; it
copies bytes. Consequences worth knowing:

- Responses are `Connection: close`, so the relay closes the public socket when
  it sees `CLOSE`.
- Static files stream in 512-byte reads (`static_files.CHUNK`), coalesced into
  ~1KB tunnel frames. A page load is several hundred KB through a 150 MHz MCU —
  expect it to be slow. Caching at the relay is the obvious future win, and it
  is invisible to the device.

## 6. Fleet routing

`device_id` is the routing key, and the public surface should be
**subdomain-per-device**:

```
kitchen.tunnel.example.com  ->  device_id "kitchen"
```

Do **not** use a path prefix (`/d/kitchen/…`). The web app references assets as
root-absolute (`/assets/…`) and derives its WebSocket URL from
`window.location.host` (`web/src/lib/api.js`), so a subdomain needs **zero**
web-app changes while a path prefix breaks every asset URL and the WS.

This costs wildcard DNS (`*.tunnel.example.com`) and a wildcard certificate
(Let's Encrypt DNS-01).

## 7. Security

- **The public leg needs its own auth.** The HELLO token protects device→relay
  only. The device's `/api` has no authentication and sends
  `Access-Control-Allow-Origin: *` — defensible on a LAN, wide open once
  published. HTTP Basic over TLS, terminated at the relay, is the chosen
  approach here; with a fleet it needs per-device credentials, not one shared
  password.
- **MicroPython's `ssl` defaults to `CERT_NONE`.** `use_tls` gives
  confidentiality, not proof the device reached *your* relay. Pinning a CA cert
  on the device is worth doing before a fleet goes out.
- **Per-device tokens.** One shared fleet token means a single extracted device
  compromises every device. Flash is readable by anyone holding the board.

## 8. Device reconnect behaviour — read this before restarting the relay

The connect and handshake are **blocking** on the device, so every attempt
freezes its event loop for up to `connect_timeout_ms` (and delays the
momentary-hold deadman in `server/pins.py` by the same amount).

Because of that, `tunnel.startup_only` defaults to **true**: the device makes
**exactly one attempt per boot**. If that attempt fails — or if an established
tunnel later drops — the device switches the tunnel off for the rest of the boot
and carries on as a normal LAN device. It pays the stall once, at startup, and
never again.

**The operational consequence, stated plainly: nothing reconnects by itself.**
Restarting the relay, redeploying it, or a brief network blip will leave every
connected device unreachable from the internet until it is power-cycled. Plan
relay maintenance accordingly, or set `startup_only` to false on the fleet to
get backoff-retry instead (`reconnect_min_ms` → `reconnect_max_ms`), accepting a
recurring stall whenever the relay is unreachable.

A relay that wants devices back after a restart has to trigger a device restart
some other way — there is no in-band "please reconnect" message, because a
disabled tunnel is not listening for one.

## 9. Relay obligations, in short

1. Reject any HELLO with a bad token.
2. Allocate unique `stream_id`s; never reuse before CLOSE.
3. Never exceed 1024 bytes of payload per frame.
4. Buffer a complete HTTP request (or exactly one WS frame) before FLUSH.
5. Forward client WS frames verbatim, masked, one FLUSH each.
6. Copy device→relay DATA straight to the public socket; close it on CLOSE.
7. Answer PING with PONG; send PING so the device's `idle_timeout_ms` doesn't
   trip.
8. Respect `max_streams` (default 6) — the device refuses excess streams by
   replying CLOSE immediately, and the relay must handle that as a 503 rather
   than hanging the browser.
