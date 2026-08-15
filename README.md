# RemoteSwitchPico

A Raspberry Pi **Pico 2 W** that joins your Wi-Fi, hosts a **React + Tailwind**
dashboard, and exposes an HTTP API for live health stats and LED control.

The Pico serves everything itself — the built web app *and* the API. Your
laptop is only used to **build** the app; nothing else needs to be running.

## Architecture

```
Browser ─────────> Pico 2 W (port 80)
   │                 ├─ GET       /                -> static web app  (www/)
   │                 ├─ WebSocket /api/ws/health   -> live stats + LED state (pushed)
   │                 ├─ GET       /api/health      -> JSON snapshot (one-shot)
   │                 └─ POST      /api/blink       -> LED / blink control
   │
   └─ React app
        • WebSocket /api/ws/health  -> live stats, pushed every 1s
        • POST /api/blink           -> LED commands (TanStack Query mutation)
```

All API endpoints live under `/api` (the WebSocket too); everything else is
served as the static web app.

**Hybrid** data flow, by design:
- **Live stats** stream over a **WebSocket** (`useHealthSocket`). The Pico pushes
  a `{type:"stats", stats, led}` frame on connect and then every second — this is
  the "constantly pulling stats", done as server push rather than polling.
- **LED commands** use a **traditional HTTP request** (`useLedCommand` ->
  `POST /api/blink`), managed by TanStack Query as a mutation.
- After a command, the Pico applies it and immediately **broadcasts** the new
  state to every WebSocket client, so the UI reflects it right away.

## Layout

```
main.py              # entry point — runs on boot
server/              # firmware package (all the logic)
  config.py          # Wi-Fi credentials + timing/port constants
  wifi_conn.py       # Wi-Fi station connection
  led/               # LED subsystem
    controller.py    #   LedController: drives the pin from the active pattern
    patterns.py      #   FixedPattern / TickPattern / MorsePattern
    morse.py         #   Morse table + standard-timing timeline builder
  metrics.py         # get_pico_state(): RAM / flash / CPU / RSSI / uptime
  static_files.py    # serves the built web app from www/ (with SPA fallback)
  ws_protocol.py     # WebSocket handshake + frame encode/decode
  webserver.py       # PicoServer: the HTTP/WebSocket event loop + routes
www/                 # built web app (generated — served by the Pico)
web/                 # React source (built locally, NOT uploaded to the Pico)
Pipfile              # host Python tooling (mpremote + Pico 2 W type stubs)
```

## Host Python environment (Pipenv)

Host-side Python tooling lives in a Pipenv environment (this is *not* what runs
on the Pico — the Pico runs MicroPython). It provides `mpremote` and the
Pico 2 W type stubs so `machine`, `network`, etc. resolve in the editor.

```bash
pipenv install --dev        # create the venv (Python 3.11) + install tools
pipenv run mpremote         # talk to the Pico over USB (repl/upload/run)
```

The venv lives outside the project (in `~/.local/share/virtualenvs/`), so it's
never uploaded to the Pico. VS Code is pointed at it via
`python.defaultInterpreterPath` in `.vscode/settings.json`.

## 1. Configure Wi-Fi

Credentials live in `.env`, which is gitignored so they never get committed:

```bash
cp .env.example .env        # then fill in WIFI_SSID / WIFI_PASS
```

Everything else is configured in `settings.json` at the project root
(`server/config.py` just loads it and provides fallback defaults). Every key is
optional — omit one and its default is used. Available keys: `wifi_ssid`,
`wifi_pass`, `http_port`, `stats_interval_ms`, `poll_timeout_ms`,
`wifi_timeout_s`, `default_tick_on_ms`, `default_tick_off_ms`,
`default_morse_message`, `default_morse_wpm`.

`deploy.sh` merges `WIFI_SSID`/`WIFI_PASS` from `.env` into a temporary copy of
`settings.json` and uploads *that*, so the device gets working credentials
while the committed `settings.json` keeps them empty. If you upload by other
means (e.g. the MicroPico "Upload project to Pico" command), the board gets the
credential-less `settings.json` and won't join your network — use
`pipenv run deploy` / `pipenv run upload`.

## 2. Build the web app (on your machine)

```bash
cd web
npm install
npm run build      # outputs to ../www
```

For local development against a running Pico:

```bash
npm run dev        # then enter the Pico's IP in the "Pico address" box
```

## 3. Upload to the Pico

Using the **MicroPico** VS Code extension: run **"Upload project to Pico"**.
`.vscode/settings.json` is already configured to upload `main.py`, the
`server/` package, and `www/`, while **ignoring `web/` and `node_modules/`**.

The Pico prints its address on boot:

```
Dashboard:   http://192.168.x.x/
```

Open that URL from any device on the network.

## API

| Method | Path         | Body                                              | Response / Behaviour              |
|--------|--------------|---------------------------------------------------|-----------------------------------|
| WS     | `/api/ws/health` | —                                             | pushes `{type:"stats",stats,led}` |
| GET    | `/api/health`    | —                                             | `{status, stats, led, pins, tunnel}` |
| POST   | `/api/blink`     | `{"mode":"fixed","on":true\|false}`           | `{status, led}`                   |
| POST   | `/api/blink`     | `{"mode":"tick","on_ms":500,"off_ms":500}`    | `{status, led}`                   |
| POST   | `/api/blink`     | `{"mode":"morse","message":"SOS","wpm":10}`   | `{status, led}`                   |
| GET    | `/api/logs`      | —                                             | `{status, files:[{name,size}]}`   |
| GET    | `/api/logs/tail` | `?name=tunnel.log&lines=200`                  | `text/plain`, the last `lines` lines |

### Log files

`/api/logs` lists the `*.log` files the device keeps on flash (today that's
`tunnel.log`), and `/api/logs/tail` streams the end of one — up to 500 lines,
newest last. **Settings → Log files** in the web app is a reader for both.

This exists because reading the log over USB destroys the evidence: every
`mpremote` command interrupts `main.py`, so `fs cat :tunnel.log` ends the run
you were diagnosing. Over HTTP the device keeps going. The tail is located in
one pass and copied to the socket in another (`server/logs.py`), so a 175KB log
never lands on the heap.

### LED modes

- **fixed** — steady on or off.
- **tick** — asymmetric blink: on for `on_ms`, off for `off_ms`, repeating.
- **morse** — blinks a message in International Morse code, repeating, using
  standard PARIS timing (`unit_ms = 1200 / wpm`; dot = 1 unit, dash = 3, symbol
  gap = 1, letter gap = 3, word gap = 7). Lives in `server/led/`.

The LED subsystem is a small package (`server/led/`): a `controller` that drives
the pin from a swappable `pattern` (`FixedPattern` / `TickPattern` /
`MorsePattern`), with the Morse table + timing in `morse.py`.

CORS is enabled (`*`) so the dev server can talk to the Pico cross-origin.

## Staying connected (reverse tunnel)

`settings.json` has a `tunnel` block that dials out to an
[up-tunnel](https://github.com/up209d/up-tunnel) relay, so the device is
reachable from the internet through NAT. Beyond the connection settings, these
control what happens when it goes wrong:

| Key | Default | What it does |
|-----|---------|--------------|
| `tunnel.keepalive_ms` | 20000 | How often the device pings the relay. |
| `tunnel.idle_timeout_ms` | 60000 | Drop the session after this long with no bytes, or no answer to our pings. |
| `tunnel.healthy_ms` | 60000 | Hold a session this long and the reconnect backoff resets to `reconnect_min_ms`. |
| `tunnel.log_heartbeat_ms` | 300000 | Write one `tunnel: ok …` line to `tunnel.log` this often. 0 disables. |
| `tunnel.log_max_lines` | 1000 | Ceiling on `tunnel.log`; a trim keeps the newest 80%. |
| `wifi_grace_ms` | 30000 | Reassociate after Wi-Fi has been down this long; reboot if that fails. |
| `watchdog.enabled` | true | Arm `machine.WDT` as a last resort. |
| `watchdog.stall_timeout_ms` | 60000 | Reboot after this long with no clean event-loop pass. |

The RP2 hardware watchdog maxes out at 8388 ms, so the reboot is two-stage: the
hardware timer catches a genuine hang within its own ceiling, and
`stall_timeout_ms` catches the slower failure it cannot see — a loop that keeps
running, and keeps feeding the watchdog, while every pass throws.

### When the tunnel is down

1. **Ask the device.** `curl http://<pico-ip>/api/health | jq .tunnel` shows
   `connected`, `public_url`, `backoff_ms` and `since_pong_ms`. If it says
   connected and the public URL still 502s, the relay dropped the session
   without the device noticing — which is what the pong and `tunnel_id` checks
   in `server/tunnel.py` exist to catch.
2. **Read the log.** `curl 'http://<pico-ip>/api/logs/tail?name=tunnel.log&lines=200'`
   (or **Settings → Log files** in the web app) — every connect, failure, retry
   and event-loop error is in there, with a `tunnel: ok …` heartbeat in between
   so a *gap* is itself evidence. Timestamps are NTP-synced (`server/timesync.py`);
   a line still stamped in year 2000 means the sync never landed and the clock
   is uptime. Read it over HTTP, not `./fs.sh cat :tunnel.log` — see below.
3. **Ask the relay.** `curl -s localhost:8082/status | jq '.agents[]'` on the
   relay host lists connected agents — including `lanIp`, which is how you find
   this board on your LAN when you don't know its DHCP address. The relay's
   `health.log` records the same on every reconnect.

**Do not use `mpremote` while diagnosing.** Every `mpremote` command — `fs ls`
and `fs cat` included — enters the raw REPL and kills the running app, so the
tunnel will drop the moment you look at it. That is exactly why `/api/logs/tail`
exists: it reads the same file with the app still running. Diagnose over the
network throughout.
