export function formatUptime(seconds) {
  if (seconds == null) return '—'
  const s = Math.floor(seconds % 60)
  const m = Math.floor((seconds / 60) % 60)
  const h = Math.floor((seconds / 3600) % 24)
  const d = Math.floor(seconds / 86400)
  const parts = []
  if (d) parts.push(`${d}d`)
  if (h || d) parts.push(`${h}h`)
  if (m || h || d) parts.push(`${m}m`)
  parts.push(`${s}s`)
  return parts.join(' ')
}

export function formatKb(kb) {
  if (kb == null) return '—'
  if (kb >= 1024) return `${(kb / 1024).toFixed(2)} MB`
  return `${kb.toFixed(1)} KB`
}

// Map RSSI dBm to a rough 0-100 signal quality.
export function rssiQuality(rssi) {
  if (rssi == null) return 0
  if (rssi <= -100) return 0
  if (rssi >= -50) return 100
  return Math.round(2 * (rssi + 100))
}

export function signalLabel(rssi) {
  const q = rssiQuality(rssi)
  if (q >= 75) return 'Excellent'
  if (q >= 50) return 'Good'
  if (q >= 25) return 'Fair'
  return 'Weak'
}
