# Reverse tunnel (uptunnel wire protocol v1)

The device sits behind NAT, so it dials **out** to an uptunnel server you run on
a host with a fixed DNS name and holds that connection open. The server fronts a
public listener at `https://<subdomain>.<its domain>` and forwards everything it
receives down that socket.

**The server is a dumb pipe.** It serves no UI, holds no state about the device,
and knows nothing about `/api`. The device keeps serving its own web app, its
own static files and its own WebSocket — a tunnelled request is handed to the
exact same handlers a LAN client hits (`webserver._serve`), through a
socket-lookalike (`tunnel.TunnelStream`).

Device side: `server/tunnel.py` + `server/ws_client.py`. Config: the `tunnel`
block in `settings.json` (documented key-by-key in `server/config.py`), whose
secrets come from `.env` at deploy time.

**The authority for the wire format is the up-tunnel repo's `docs/PROTOCOL.md`,
not this file.** This document covers what the device implementation does with
it. `tests/protocol-vectors.json` in that repo holds golden byte vectors; the
device's framing is checked against them.

---

## 1. Transport

One WebSocket per device, device → server:

```
wss://tunnel.example.com/control
```

All messages are **binary**. WebSocket already delimits them, so frames carry no
length of their own:

```
byte 0        type (u8)

type < 0x20   control frame:  bytes 1..   = UTF-8 JSON object
type >= 0x20  stream frame:   bytes 1..5  = streamId (u32, big-endian)
                              bytes 5..   = type-specific payload
```

| Type | Name | Direction | Payload |
|------|------|-----------|---------|
| `0x01` | HELLO | device → server | JSON: version, token, name, client, lanIp?, lanPort? |
| `0x02` | HELLO_OK | server → device | JSON: agentId, heartbeatMs, streamWindow, httpDomain |
| `0x03` | ERROR | both | JSON: code, message, optional reqId |
| `0x10` | OPEN_TUNNEL | device → server | JSON: reqId, kind, subdomain, target |
| `0x11` | TUNNEL_OK | server → device | JSON: reqId, tunnelId, subdomain, publicUrl |
| `0x12` | CLOSE_TUNNEL | device → server | JSON: tunnelId |
| `0x20` | STREAM_OPEN | server → device | streamId + JSON: tunnelId, remoteAddr |
| `0x21` | STREAM_DATA | both | streamId + raw bytes |
| `0x22` | STREAM_EOF | both | streamId |
| `0x23` | STREAM_ACK | both | streamId + u32 bytes consumed |
| `0x24` | STREAM_RESET | both | streamId + JSON: code |

Streams are **always** opened by the server, because every tunnelled connection
originates on the public internet. The device never sends `STREAM_OPEN`.

### Masking

RFC 6455 requires client frames to be masked with an unpredictable key. That
rule exists to stop a hostile browser script steering exact bytes onto the wire
to poison an intermediary's cache. Nothing the device sends is attacker-chosen
and the hop is TLS to a server you run, so `ws_client._MASK` is **all zeroes** —
masking then costs no per-byte Python loop and no second copy of the payload,
which on a 150MHz MCU is the difference between a brisk page load and a slow
one. Change that constant and restore the XOR loop in `encode()` together.

## 2. Handshake

1. Device opens the WebSocket and sends `HELLO` with `token`, `name` and
   `version: 1`, plus the optional `lanIp` / `lanPort` (see below). Bad
   credentials get an `ERROR` and a close. `bad_version` is terminal — the
   device stops retrying, because only new firmware can fix it. `unauthorized`
   is **not**: the device backs off to `reconnect_max_ms` and keeps trying (see
   §8 for why).
2. Server replies `HELLO_OK` with `streamWindow`, the per-stream credit.
3. Device sends one `OPEN_TUNNEL` claiming `tunnel.subdomain` as an HTTP tunnel.
4. Server replies `TUNNEL_OK` with `publicUrl`, which the device prints.

If step 3 is refused (typically `subdomain_taken`, when the server has not yet
reaped a previous session of ours) the connection is authenticated but publicly
dead — nothing will ever route to it. The device drops it and reconnects on the
backoff rather than sitting there looking connected.

`name` defaults to `pico-<machine.unique_id() hex>`, so one identical
`settings.json` can go to a whole fleet and each board is still tellable apart
in the server's logs. It is **not** the routing key — `subdomain` is, and the
server's token entry decides which subdomains a token may claim.

### `lanIp` / `lanPort` in HELLO

Both optional, both purely informational, and the server must never route or
authenticate on them. They exist because the device is headless: when it is
reachable only through the tunnel, nothing tells you what address DHCP gave it
on its own network. The device sends what it currently believes its LAN address
to be, refreshed on every reconnect, and the server records it in its log and
exposes it on `GET /status`.

They are agent-supplied, so the server treats them as untrusted display strings:
length-capped, stripped of control characters, and never fed into routing.

## 3. When a handler runs

This is the load-bearing rule on the device side, and the one thing uptunnel
does not signal for us.

The device is single-threaded and the tunnel is one socket. If a handler could
block waiting for more bytes, it would have to pump the tunnel socket from
inside itself — re-entrancy this design does not support.

So `tunnel._pump()` dispatches nothing until a **complete unit** is buffered, at
which point everything the handler will read is already in memory and `recv()`
never blocks. A complete unit is:

- **Before the WebSocket upgrade** — a whole HTTP request: request line, all
  headers, `\r\n\r\n`, and exactly `Content-Length` bytes of body
  (`_request_complete`). Chunked request bodies are not recognised; browsers
  don't use them for the small JSON bodies `/api` takes.
- **After the upgrade** — exactly one WebSocket frame from the browser,
  forwarded verbatim and **still masked**. `ws_protocol.frame_len()` says when
  one has fully arrived; `ws_protocol.decode()` then unmasks it, byte-identical
  to the LAN path.

## 4. Response direction

Device → server is plain `STREAM_DATA`, ending in `STREAM_EOF`. The server
copies bytes straight to the public socket, so it never parses a response.
Consequences worth knowing:

- Responses are `Connection: close`, so the server ends the public socket when
  it sees `STREAM_EOF`.
- Static files stream in 512-byte reads (`static_files.CHUNK`), coalesced into
  1KB frames (`tunnel._OUT_CHUNK`). A page load is several hundred KB through a
  150MHz MCU — expect it to be slow. Caching at the server is the obvious future
  win, and it is invisible to the device.

## 5. Flow control

Each stream has a credit window per direction, `streamWindow` bytes (256KiB by
default), and a sender must stop at zero credit.

- **Inbound**, the device acks the moment it has buffered the bytes
  (`STREAM_ACK` from `_on_stream`). Requests are small, so this never throttles.
- **Outbound**, `TunnelStream.credit` is decremented per frame and restored by
  `STREAM_ACK`. A response bigger than the window stalls in `_out` until credit
  arrives; the largest asset we serve (a ~78KB gzipped bundle) is well under
  256KiB, so this is a backstop, not a hot path.

Separately, `Tunnel._push()` blocks the writer once the queue passes
`_TX_HIGH_WATER`, and gives up after `_TX_STALL_MS` **without progress** (not
total time — a 78KB bundle legitimately stalls for seconds on this hardware).
That is the same backpressure a blocking LAN socket applies inside
`static_files.write_all()`, and it is what stops a slow uplink turning a file
into unbounded heap use.

Two rules in that write path are not obvious, and breaking either one silently
truncates responses. Both were found on the device, not in a simulator:

- **A blocked write must be retried with the identical buffer.** MicroPython's
  `ssl` socket returns `None` when mbedtls reports `WANT_WRITE`, and mbedtls
  will keep refusing if the retry offers a longer buffer — which is what happens
  if you just re-offer a queue other code has appended to since. `_pending`
  holds that exact snapshot until a call actually consumes bytes.
- **A stalled writer must keep reading.** TLS is bidirectional, so mbedtls has
  to consume an incoming record — a session ticket or key update arrives
  mid-transfer unbidden — before it will accept another write. A writer that
  never reads deadlocks for good. `_soak()` therefore pulls bytes into `_rx`
  during a stall but dispatches nothing, leaving the frames for the event loop;
  running a handler from inside another handler is the re-entrancy §3 exists to
  avoid. Fixing this took the 78KB bundle from "fails after 5.6s" to 1.1s.

RAM is bounded on the way in by `tunnel.max_frame_bytes` (32KB, matching the
server's own cap on an HTTP request head). A larger inbound frame drops the
connection instead of the heap.

## 6. Security

- **The public leg needs its own auth.** The HELLO token protects device→server
  only. The device's `/api` has no authentication and sends
  `Access-Control-Allow-Origin: *` — defensible on a LAN, wide open once
  published. Terminate HTTP Basic (or better) at the tunnel server; with a fleet
  that needs per-device credentials, not one shared password.
- **MicroPython's `ssl` defaults to `CERT_NONE`.** `wss` gives confidentiality,
  not proof the device reached *your* server. Pinning a CA cert on the device is
  worth doing before a fleet goes out.
- **Per-device tokens.** One shared fleet token means a single extracted device
  compromises every device. Flash is readable by anyone holding the board.
- The token never enters git: it lives in `.env`, and
  `tools/build_settings.py` merges it into the `settings.json` that is uploaded.

## 7. Fleet routing

`subdomain` is the routing key, and the public surface is
**subdomain-per-device**:

```
kitchen.tunnel.example.com  ->  subdomain "kitchen"
```

Do **not** use a path prefix (`/d/kitchen/…`). The web app references assets as
root-absolute (`/assets/…`) and derives its WebSocket URL from
`window.location.host` (`web/src/lib/api.js`), so a subdomain needs **zero**
web-app changes while a path prefix breaks every asset URL and the WS.

## 8. Reconnect behaviour, and why `disabled` is never persisted

The connect, the TLS handshake and the WebSocket handshake are all **blocking**
on the device, so every attempt freezes its event loop for up to
`connect_timeout_ms` (and delays the momentary-hold deadman in `server/pins.py`
by the same amount).

`tunnel.startup_only` decides what that costs:

- **false (the default)** — backoff-retry from `reconnect_min_ms` to
  `reconnect_max_ms`. A server redeploy, a wifi blip or a black-holed link all
  recover on their own. The price is a recurring stall whenever the server is
  unreachable.
- **true** — exactly one attempt per boot. On failure, or when an established
  tunnel later drops, the device switches the tunnel off for the rest of the
  boot and carries on as a normal LAN device. It pays the stall once and never
  again — **and nothing reconnects by itself**, so it stays unreachable from the
  internet until it is power-cycled.

That switch is `Tunnel.disabled`, and it is **deliberately not persisted** to
`state.json`. Its whole purpose is to be cleared by a restart: a device that
gave up must come back with a clean slate on the next boot. Do not "fix" this by
adding it to `server/state.py`.

`bad_version` sets `disabled` regardless of `startup_only`: a protocol mismatch
needs a new binary on one side, so retrying genuinely cannot help.

`unauthorized` deliberately does **not**. It looks like a permanent credential
failure but usually is not: a relay restarted before its token file loaded, a
rolled-back deploy, or another service briefly answering on the hostname all
produce it. A device that switched itself off for those would need a physical
power cycle to come back, which defeats the point of remote access. Instead it
pins the backoff at `reconnect_max_ms` and keeps trying — slow enough to cost
nothing, and it self-heals when the server does.

### Proving the session is alive

Three separate checks, because each catches something the others miss
(`Tunnel._check_liveness`):

- **Bytes received** — nothing at all for `idle_timeout_ms` means the socket is
  dead. Catches a black-holed link, where TCP alone would sit there for minutes.
- **Pong received** — the device pings every `keepalive_ms` with a sequenced
  payload and requires an answer within `idle_timeout_ms`. Bytes arriving only
  prove the socket works; a pong proves the *server* is still processing us.
- **`tunnel_id` present** — proof the public side can still route here. A
  session can be authenticated and healthy on the wire while nothing in the
  world can reach it; that is the "device says connected, URL returns 502" case,
  and only this check sees it.

All three run **before** the write path, so a `_drain()` that throws on every
pass can never suppress them. And a session that holds for `healthy_ms` resets
the backoff to `reconnect_min_ms`, so one rough patch does not cost 60-second
recovery for the rest of the boot.

### Nothing here is persisted

`disabled`, the backoff, the liveness timestamps and the watchdog counters are
all per-session by design and are **deliberately not written** to `state.json` —
a device that gave up must come back with a clean slate on the next boot. Do not
"fix" this by adding them to `server/state.py`.

## 9. What the device expects of the server

1. Reject any HELLO with an unknown token (`unauthorized`, close 4001).
2. Allocate unique `streamId`s; never reuse one within a session.
3. Keep a single inbound unit under `max_frame_bytes` (32KB) — the device drops
   the connection above that rather than allocating unbounded RAM.
4. Forward browser WebSocket frames verbatim and masked.
5. Copy device→server `STREAM_DATA` straight to the public socket, and end that
   socket on `STREAM_EOF`.
6. Ping on the heartbeat, and **answer the device's own pings with a pong** —
   the device now drops a session that stops answering, so a server that ignores
   client pings will be reconnected to every `idle_timeout_ms`.
7. Tolerate more than one missed pong before terminating the agent
   (`HEARTBEAT_MISSES`, default 2), and count inbound frames and client pings as
   liveness. Terminating on a single missed control frame frees the subdomain
   while the device — which gets no RST back through a black-holed NAT — still
   believes it is connected, which surfaces as an unexplained 502.
8. Honour `max_streams` (default 6) — the device refuses excess streams with
   `STREAM_RESET {"code": "too_many_streams"}`, which the server should turn
   into a 502 rather than hanging the browser.
