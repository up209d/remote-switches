// Appearance options + persistence. The hook applies { mode, scheme, pattern }
// as data-mode / data-palette / data-bg on <html>; index.css maps those to the
// --tk-* token values that every component reads through semantic utilities.

const KEY = 'pico.appearance'

// Defaults == today's look, so a first-time visitor sees no change.
export const DEFAULTS = { mode: 'dark', scheme: 'a', pattern: 'off' }

export const MODES = [
  { key: 'system', label: 'System' },
  { key: 'light', label: 'Light' },
  { key: 'dark', label: 'Dark' },
]

// swatch = the scheme's primary accent, for the picker chips.
export const SCHEMES = [
  { key: 'a', name: 'Emerald', group: 'Accent', swatch: '#10b981' },
  { key: 'b', name: 'Indigo', group: 'Accent', swatch: '#6366f1' },
  { key: 'c', name: 'Cyan', group: 'Accent', swatch: '#06b6d4' },
  { key: 'd', name: 'Violet', group: 'Accent', swatch: '#8b5cf6' },
  { key: 'e', name: 'Midnight', group: 'Dramatic', swatch: '#3b82f6' },
  { key: 'f', name: 'Ember', group: 'Dramatic', swatch: '#f97316' },
  { key: 'g', name: 'Terminal', group: 'Dramatic', swatch: '#22c55e' },
  { key: 'h', name: 'Synthwave', group: 'Dramatic', swatch: '#ec4899' },
]

export const PATTERNS = [
  { key: 'off', label: 'Off', group: 'Basic' },
  { key: 'dots', label: 'Dots', group: 'Basic' },
  { key: 'grid', label: 'Grid', group: 'Basic' },
  { key: 'diagonal', label: 'Diagonal', group: 'Basic' },
  { key: 'waves', label: 'Waves', group: 'Basic' },
  { key: 'circuit', label: 'Circuit', group: 'Tech' },
  { key: 'cpu', label: 'CPU', group: 'Tech' },
  { key: 'pi', label: 'π', group: 'Tech' },
  { key: 'bot', label: 'Bot', group: 'Tech' },
  { key: 'grain', label: 'Grain', group: 'FX' },
  { key: 'glow', label: 'Glow', group: 'FX' },
]

const valid = (list, k) => list.some((x) => x.key === k)

export function loadAppearance() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || '{}')
    return {
      mode: valid(MODES, saved.mode) ? saved.mode : DEFAULTS.mode,
      scheme: valid(SCHEMES, saved.scheme) ? saved.scheme : DEFAULTS.scheme,
      pattern: valid(PATTERNS, saved.pattern) ? saved.pattern : DEFAULTS.pattern,
    }
  } catch {
    return { ...DEFAULTS }
  }
}

export function saveAppearance(a) {
  try {
    localStorage.setItem(KEY, JSON.stringify(a))
  } catch {
    /* storage disabled — appearance just won't persist */
  }
}

// system mode follows the OS; light/dark are explicit.
export function resolveMode(mode) {
  if (mode === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return mode
}

// Apply to <html>. Shared by the no-flash inline script (via window.__applyAppearance)
// and the React hook, so both stay in sync.
export function applyAppearance(a) {
  const root = document.documentElement
  root.setAttribute('data-mode', resolveMode(a.mode))
  root.setAttribute('data-palette', a.scheme)
  root.setAttribute('data-bg', a.pattern)
}
