// Dev-only mock of the Pico's /api surface, so `npm run dev` gives you a fully
// working dashboard with NO device attached. It runs inside the vite dev server
// (one process, one command) and mirrors the real firmware's contract:
//   WS   /api/ws/health  -> {type:"stats", stats, led, pins, tunnel} on connect + every 1s
//   GET  /api/health      -> {status, stats, led, pins, tunnel}
//   POST /api/blink        -> {status, led}   (fixed | tick | morse)
//   POST /api/pin          -> {status, pins}  (one command or a batch)
//   GET  /api/logs         -> {status, files:[{name,size}]}
//   GET  /api/logs/tail    -> text/plain, last ?lines= lines of ?name=
// State is in-memory and fake; commands are echoed back like the device would.
//
// Enter `localhost:5173` in the app's "Pico address" box to point at this mock.
import crypto from 'node:crypto'

const SAFE_GPIOS = [...Array(23).keys(), 26, 27, 28] // 0..22, 26, 27, 28
const ADC = new Set([26, 27, 28])
const WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'

// Stand-in for the device's flash logs, in the shape server/tunnel_log.py
// writes: "YYYY-MM-DD HH:MM:SS <message>", oldest first, newline-terminated.
function fakeTunnelLog(count) {
  const msgs = [
    'tunnel: connecting to relay.example.com:7000',
    'tunnel: registered as pico-2w',
    'tunnel: ok — up 5m, 12 requests',
    'tunnel: no pong in 60000ms, dropping session',
    'tunnel: retry in 4s',
    'wifi: reassociated, rssi -63 dBm',
  ]
  const lines = []
  let t = Date.parse('2026-08-15T09:00:00Z')
  for (let i = 0; i < count; i++) {
    lines.push(`${new Date(t).toISOString().replace('T', ' ').slice(0, 19)} ${msgs[i % msgs.length]}`)
    t += 37_000
  }
  return lines.join('\n') + '\n'
}

const LOGS = { 'tunnel.log': fakeTunnelLog(300) }

export function devMockServer() {
  // ---- in-memory state ---------------------------------------------------
  let led = { mode: 'fixed', on: false }
  const outPins = new Map() // gpio -> { value, offAt }
  const clients = new Set()

  const now = () => Date.now()

  function stats() {
    const totalKb = 520.9
    const usedKb = 150 + Math.round(Math.random() * 40)
    return {
      status: 'ok',
      board: 'Raspberry Pi Pico 2 W (mock)',
      uptime_seconds: Math.floor(process.uptime()),
      cpu: { freq_mhz: 150 },
      memory: {
        free_kb: +(totalKb - usedKb).toFixed(2),
        used_kb: +usedKb.toFixed(2),
        total_kb: totalKb,
        usage_percent: +((usedKb / totalKb) * 100).toFixed(1),
      },
      storage: { free_kb: 1600, total_kb: 2000 },
      network: { ip: '127.0.0.1', rssi_dbm: -55 - Math.round(Math.random() * 10) },
    }
  }

  // Mirrors server/tunnel.py:snapshot(). Reported as a healthy session, since
  // there is no tunnel in dev mode and a permanently "down" badge would just be
  // noise. `null` here is what the firmware sends when the tunnel is disabled.
  function tunnel() {
    return {
      connected: true,
      public_url: 'https://mock-device.tunnel.example.com',
      lan_ip: '127.0.0.1',
      disabled: false,
      backoff_ms: 2000,
      up_ms: Math.floor(process.uptime() * 1000),
      since_pong_ms: 500 + Math.round(Math.random() * 500),
    }
  }

  function readPins() {
    return SAFE_GPIOS.map((n) => {
      const armed = outPins.has(n)
      return {
        gpio: n,
        value: armed ? outPins.get(n).value : 0,
        adc: ADC.has(n),
        mode: armed ? 'out' : 'in',
      }
    })
  }

  function applyLed(msg) {
    if (msg.mode === 'fixed') led = { mode: 'fixed', on: !!msg.on }
    else if (msg.mode === 'tick')
      led = { mode: 'tick', on_ms: msg.on_ms ?? 500, off_ms: msg.off_ms ?? 500, on: true }
    else if (msg.mode === 'morse')
      led = { mode: 'morse', message: msg.message ?? 'SOS', wpm: msg.wpm ?? 10, on: true }
    else return false
    return true
  }

  function applyPin(c) {
    const n = parseInt(c.gpio, 10)
    if (!SAFE_GPIOS.includes(n)) return false
    const op = c.op
    if (op === 'arm') {
      if (!outPins.has(n)) outPins.set(n, { value: 0, offAt: null })
      return true
    }
    if (op === 'release') {
      outPins.delete(n)
      return true
    }
    if (!outPins.has(n)) outPins.set(n, { value: 0, offAt: null })
    const st = outPins.get(n)
    if (op === 'write') {
      st.value = c.value ? 1 : 0
      st.offAt = null
      return true
    }
    if (op === 'hold') {
      const on = !!c.value
      st.value = on ? 1 : 0
      st.offAt = on ? now() + 1500 : null
      return true
    }
    if (op === 'pulse') {
      let ms = parseInt(c.ms ?? 250, 10)
      if (Number.isNaN(ms)) ms = 250
      ms = Math.max(20, Math.min(5000, ms))
      st.value = 1
      st.offAt = now() + ms
      return true
    }
    return false
  }

  // ---- websocket framing (server -> client, unmasked text) ---------------
  function encode(str) {
    const data = Buffer.from(str)
    const len = data.length
    let header
    if (len < 126) header = Buffer.from([0x81, len])
    else if (len < 65536) {
      header = Buffer.alloc(4)
      header[0] = 0x81
      header[1] = 126
      header.writeUInt16BE(len, 2)
    } else {
      header = Buffer.alloc(10)
      header[0] = 0x81
      header[1] = 127
      header.writeBigUInt64BE(BigInt(len), 2)
    }
    return Buffer.concat([header, data])
  }

  const payload = () =>
    JSON.stringify({ type: 'stats', stats: stats(), led, pins: readPins(), tunnel: tunnel() })

  function broadcast() {
    const frame = encode(payload())
    for (const sock of clients) {
      try {
        sock.write(frame)
      } catch {
        clients.delete(sock)
      }
    }
  }

  return {
    name: 'pico-dev-mock',
    apply: 'serve',
    configureServer(server) {
      // HTTP API routes
      server.middlewares.use((req, res, next) => {
        const url = (req.url || '').split('?')[0]
        if (!url.startsWith('/api/')) return next()

        res.setHeader('Access-Control-Allow-Origin', '*')
        res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        res.setHeader('Access-Control-Allow-Headers', 'Content-Type')
        if (req.method === 'OPTIONS') {
          res.statusCode = 204
          return res.end()
        }

        const send = (obj, code = 200) => {
          res.statusCode = code
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify(obj))
        }
        const readBody = (cb) => {
          let b = ''
          req.on('data', (c) => (b += c))
          req.on('end', () => {
            try {
              cb(b ? JSON.parse(b) : {})
            } catch {
              send({ error: 'invalid json' }, 400)
            }
          })
        }

        if (url === '/api/health' && req.method === 'GET')
          return send({ status: 'ok', stats: stats(), led, pins: readPins(), tunnel: tunnel() })

        if (url === '/api/blink' && req.method === 'POST')
          return readBody((msg) => {
            if (!applyLed(msg)) return send({ error: 'unknown command' }, 400)
            send({ status: 'ok', led })
            broadcast()
          })

        if (url === '/api/pin' && req.method === 'POST')
          return readBody((msg) => {
            const cmds = Array.isArray(msg) ? msg : [msg]
            if (!cmds.length || !cmds.every(applyPin)) return send({ error: 'unknown command' }, 400)
            send({ status: 'ok', pins: readPins() })
            broadcast()
          })

        if (url === '/api/logs' && req.method === 'GET')
          return send({
            status: 'ok',
            files: Object.entries(LOGS).map(([name, text]) => ({ name, size: text.length })),
          })

        if (url === '/api/logs/tail' && req.method === 'GET') {
          const q = new URLSearchParams((req.url || '').split('?')[1] || '')
          const text = LOGS[q.get('name')]
          if (text === undefined) return send({ error: 'no such log' }, 404)
          const n = Math.max(1, Math.min(parseInt(q.get('lines'), 10) || 200, 500))
          res.statusCode = 200
          res.setHeader('Content-Type', 'text/plain; charset=utf-8')
          res.setHeader('Cache-Control', 'no-store')
          // Trailing newline: the file ends with one, so the last split entry is ''.
          return res.end(text.split('\n').slice(-(n + 1)).join('\n'))
        }

        return send({ error: 'not found' }, 404)
      })

      // WebSocket upgrade for the live stats stream
      server.httpServer?.on('upgrade', (req, socket) => {
        if (!(req.url || '').startsWith('/api/ws/health')) return // leave vite's HMR ws alone
        const key = req.headers['sec-websocket-key']
        if (!key) return
        const accept = crypto.createHash('sha1').update(key + WS_GUID).digest('base64')
        socket.write(
          'HTTP/1.1 101 Switching Protocols\r\n' +
            'Upgrade: websocket\r\n' +
            'Connection: Upgrade\r\n' +
            `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
        )
        clients.add(socket)
        socket.write(encode(payload())) // initial snapshot
        socket.on('data', () => {}) // ignore client frames (none expected)
        socket.on('close', () => clients.delete(socket))
        socket.on('error', () => clients.delete(socket))
      })

      // Tick: expire momentary holds/pulses (250ms) + periodic stats push (1s)
      let ticks = 0
      const timer = setInterval(() => {
        const t = now()
        let changed = false
        for (const st of outPins.values()) {
          if (st.offAt != null && st.value && t >= st.offAt) {
            st.value = 0
            st.offAt = null
            changed = true
          }
        }
        if (changed || ++ticks % 4 === 0) broadcast()
      }, 250)
      server.httpServer?.on('close', () => clearInterval(timer))

      server.config.logger.info('  🔌 pico dev mock at /api/* + ws /api/ws/health (no device needed)')
    },
  }
}
