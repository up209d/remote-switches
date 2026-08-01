import { useEffect, useRef, useState } from 'react'
import { buildSegments, unitMs } from '../lib/morse'

/**
 * Client-side visual simulation of an LED pattern. Given a preview descriptor
 * (or null), returns a boolean that flips on/off following the same timeline
 * the firmware uses — so the bulb mimics the real LED without waiting on the
 * 1 Hz stats push.
 *
 *   preview = null
 *           | { mode: 'tick',  onMs, offMs }
 *           | { mode: 'morse', message, wpm }
 */
export function usePatternPreview(preview) {
  const [on, setOn] = useState(false)
  const timerRef = useRef(null)

  useEffect(() => {
    if (!preview) {
      setOn(false)
      return
    }

    let segments = []
    if (preview.mode === 'tick') {
      segments = [
        { level: 1, dur: Math.max(20, preview.onMs) },
        { level: 0, dur: Math.max(20, preview.offMs) },
      ]
    } else if (preview.mode === 'morse') {
      segments = buildSegments(preview.message, unitMs(preview.wpm))
    }

    if (!segments.length) {
      setOn(false)
      return
    }

    let i = 0
    let cancelled = false
    const step = () => {
      if (cancelled) return
      const seg = segments[i % segments.length]
      setOn(seg.level === 1)
      timerRef.current = setTimeout(() => {
        i += 1
        step()
      }, seg.dur)
    }
    step()

    return () => {
      cancelled = true
      clearTimeout(timerRef.current)
    }
  }, [preview])

  return on
}
