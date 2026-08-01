// The app is normally served *by the Pico*, so relative URLs hit the Pico
// directly. During local `vite` dev the page lives on localhost, so we point
// requests at an explicit Pico address (stored in localStorage).

const DEV_HOST = /^(localhost|127\.0\.0\.1)(:\d+)?$/

export function isDev() {
  return DEV_HOST.test(window.location.host)
}

export function getPicoHost() {
  return isDev() ? localStorage.getItem('picoHost') || '' : window.location.host
}

export function setPicoHost(host) {
  const cleaned = host.trim().replace(/^https?:\/\//, '').replace(/\/$/, '')
  localStorage.setItem('picoHost', cleaned)
  return cleaned
}

// HTTP URL: same-origin relative in production, absolute to Pico host in dev.
function apiUrl(path, host) {
  if (!isDev()) return path
  if (!host) return null
  return `http://${host}${path}`
}

// WebSocket URL (used for the live stats stream).
export function wsUrl(path, host) {
  if (!isDev()) {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    return `${proto}://${window.location.host}${path}`
  }
  if (!host) return null
  return `ws://${host}${path}`
}

async function postJson(path, host, command) {
  const url = apiUrl(path, host)
  if (!url) throw new Error('No Pico address set')
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(command),
  })
  if (!res.ok) throw new Error(`Command failed: ${res.status}`)
  return res.json()
}

// Traditional request for LED / blink control.
export function postBlink(host, command) {
  return postJson('/api/blink', host, command)
}

// GPIO output control. `command` is a single {gpio, op, ...} or an array of them.
export function postPin(host, command) {
  return postJson('/api/pin', host, command)
}
