// Mirrors server/led/morse.py so the client preview matches the real LED.

export const MORSE = {
  A: '.-', B: '-...', C: '-.-.', D: '-..', E: '.', F: '..-.', G: '--.', H: '....',
  I: '..', J: '.---', K: '-.-', L: '.-..', M: '--', N: '-.', O: '---', P: '.--.',
  Q: '--.-', R: '.-.', S: '...', T: '-', U: '..-', V: '...-', W: '.--', X: '-..-',
  Y: '-.--', Z: '--..',
  0: '-----', 1: '.----', 2: '..---', 3: '...--', 4: '....-',
  5: '.....', 6: '-....', 7: '--...', 8: '---..', 9: '----.',
  '.': '.-.-.-', ',': '--..--', '?': '..--..', "'": '.----.', '!': '-.-.--',
  '/': '-..-.', '(': '-.--.', ')': '-.--.-', '&': '.-...', ':': '---...',
  ';': '-.-.-.', '=': '-...-', '+': '.-.-.', '-': '-....-', _: '..--.-',
  '"': '.-..-.', '@': '.--.-.',
}

// Milliseconds per Morse unit at the given WPM (PARIS standard), clamped like
// the firmware.
export function unitMs(wpm) {
  const w = Math.max(1, Math.min(60, Math.round(wpm)))
  return Math.max(1, Math.floor(1200 / w))
}

// Human-readable dot/dash string (space -> "/").
export function morseString(message) {
  return message
    .toUpperCase()
    .split('')
    .map((c) => (c === ' ' ? '/' : MORSE[c] || ''))
    .filter(Boolean)
    .join(' ')
}

// Ordered [{level, dur}] segments that loop, matching build_timeline() on the
// device: dot=1u, dash=3u, symbol gap=1u, letter gap=3u, word gap=7u, plus a
// trailing word gap before the message repeats.
export function buildSegments(message, unit) {
  const events = []
  let firstLetter = true

  for (const ch of message.toUpperCase()) {
    if (ch === ' ') {
      events.push({ level: 0, dur: 7 * unit })
      firstLetter = true
      continue
    }
    const code = MORSE[ch]
    if (!code) continue

    if (!firstLetter) events.push({ level: 0, dur: 3 * unit })
    firstLetter = false

    for (let i = 0; i < code.length; i++) {
      events.push({ level: 1, dur: (code[i] === '-' ? 3 : 1) * unit })
      if (i < code.length - 1) events.push({ level: 0, dur: unit })
    }
  }

  if (!events.length) return []
  events.push({ level: 0, dur: 7 * unit })
  return events
}
