<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tool** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them, including dynamic-dispatch hops grep can't follow. Name a file or symbol in the query to read its current line-numbered source. If it's listed but deferred, load it by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` prints the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->



<!-- Karpathy-Inspired Claude Code Guidelines BEGIN -->

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

<!-- Karpathy-Inspired Claude Code Guidelines END -->



<!-- MicroPython Device Config BEGIN -->
## MicroPython device (this project)

**Board:** Raspberry Pi Pico 2 W (RP2350), running MicroPython. USB serial VID is `2e8a`.

**mpremote lives in the pipenv venv, not on global PATH.** Always invoke it as
`pipenv run mpremote ...` (or from inside `pipenv shell`). Version 1.28.0.

**macOS specifics (adapting the `mpremote-*` skills):** those skills document
Linux conventions (`mpy-dev`, `/dev/serial/by-id/`) that do NOT exist here.
On this machine:
- Auto-detect the first board (usual case): `pipenv run mpremote <cmd>`
- Target a specific port: `DEVICE=/dev/cu.usbmodemXXXX` (the project scripts read `$DEVICE`), or `pipenv run mpremote connect /dev/cu.usbmodemXXXX <cmd>`
- There is no `mpy-dev` and no `by-id` path — use `/dev/cu.usbmodem*` directly.

**Find the board:** `pipenv run scan` (or `./scan.sh`). Pico in normal mode =
a serial port with VID `2e8a`; in BOOTSEL mode = a `/Volumes/RP*` volume (no serial).

**Common commands (defined in Pipfile `[scripts]`):**
- `pipenv run deploy` — build `web/` → `www/`, wipe+upload `main.py`/`settings.json`/`server/`/`www/`, then run `main.py`. `DIRTY=1` keeps existing files; `NORUN=1` uploads only.
- `pipenv run upload` — upload only (no run).
- `pipenv run repl` — open REPL / view serial output.

**Keep the `resume` guidance from the skills:** the firmware runs an asyncio
event loop, so use `mpremote ... resume ...` for fs/exec ops to avoid a soft
reset that restarts the app.
<!-- MicroPython Device Config END -->



<!-- Persisted State BEGIN -->
## Persisted runtime state (state.json)

Two different files, don't confuse them:
- **`settings.json`** — deploy-time config (Wi-Fi, port, defaults). Ships with the
  firmware, loaded by `server/config.py`, overwritten on every deploy.
- **`state.json`** — written *by the device* at runtime, owned by
  `server/state.py`. Holds what the server was last commanded to do (LED pattern,
  GPIO outputs). `main.py` re-applies it before Wi-Fi comes up, so a standalone
  boot resumes exactly where it left off. `deploy.sh` deletes it (unless
  `DIRTY=1`), so a new version resets to the `settings.json` defaults.

**IMPORTANT — every new backend feature that holds mutable state must implement
both halves:**
1. **Persist** — include it in `state.save()`'s snapshot (add a key to
   `server/state.py:snapshot()`, plus a `snapshot()`-style serialiser on the
   owning module) and call `state.save(self.led)` from the handler that changed it.
2. **Restore** — re-apply it in `server/state.py:restore()` at boot, via the same
   code path a live command takes (see `LedController.apply_command` /
   `pins.restore`), never a second parallel implementation.

Rules that fall out of this:
- Serialise *durable* state only. Time-limited things (momentary `hold`, `pulse`)
  are recorded in their resting state, never as still-active.
- `save()` dedupes against the last blob written, so repeated no-op commands
  (e.g. the UI's `hold` keep-alives) cost no flash writes. Keep snapshots
  deterministic — sort dict iteration — or dedup breaks and flash gets hammered.
- A missing or corrupt `state.json` must never block boot: fall back to defaults.
- **Deliberate exception:** `Tunnel.disabled` (`server/tunnel.py`) is mutable
  runtime state that must NOT be persisted. Its whole purpose is to be cleared
  by a restart — see `docs/TUNNEL_PROTOCOL.md` §8. Don't "fix" it by adding it to
  `state.py`.
<!-- Persisted State END -->



<!-- Dev Mock Server BEGIN -->
## No-device dev mode (mock server)

`cd web && npm run dev` brings up the web app **and** a fake Pico backend in one
process — no hardware needed. Enter `localhost:5173` in the app's "Pico address"
box to point at it.

The mock is `web/dev-mock-server.js`, a dev-only vite plugin (`apply: 'serve'`,
wired in `web/vite.config.js`; excluded from production builds). It has no npm
dependencies — the WebSocket handshake uses Node's built-in `crypto`. It mocks
the Pico's whole `/api` surface:
- WS `/api/ws/health` → `{type:"stats", stats, led, pins}` on connect + every 1s
- GET `/api/health` → `{status, stats, led, pins}`
- POST `/api/blink` → `{status, led}` (fixed | tick | morse)
- POST `/api/pin` → `{status, pins}` (single or batch; ops arm/release/write/hold/pulse)

**IMPORTANT — keep it in sync.** The mock is a *parallel implementation* of the
firmware's response shapes and command handling (`server/webserver.py`,
`server/metrics.py`, `server/pins.py`, `server/led/`). It does NOT share code
with `server/`. Whenever you add or change a server endpoint, command, or
response field, update `web/dev-mock-server.js` to match — otherwise dev mode
silently drifts from the real device. Treat mock parity as part of "done" for
any `server/` change.
<!-- Dev Mock Server END -->