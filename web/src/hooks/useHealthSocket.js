import { useCallback, useEffect, useRef, useState } from 'react'
import { wsUrl } from '../lib/api'

/**
 * Live stats over WebSocket (/ws/health). The Pico pushes a
 * {type:"stats", stats, led} frame on connect and then on an interval.
 * Auto-reconnects with a simple backoff.
 */
export function useHealthSocket(host) {
  const url = wsUrl('/api/ws/health', host)

  const [status, setStatus] = useState('connecting') // connecting | open | closed
  const [stats, setStats] = useState(null)
  const [led, setLed] = useState(null)
  const [pins, setPins] = useState(null)
  const [lastUpdate, setLastUpdate] = useState(null)

  const wsRef = useRef(null)
  const reconnectRef = useRef(null)
  const attemptsRef = useRef(0)
  const closedByUs = useRef(false)

  const connect = useCallback(() => {
    if (!url) {
      setStatus('closed')
      return
    }
    setStatus('connecting')

    let ws
    try {
      ws = new WebSocket(url)
    } catch {
      scheduleReconnect()
      return
    }
    wsRef.current = ws

    ws.onopen = () => {
      attemptsRef.current = 0
      setStatus('open')
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.stats) setStats(msg.stats)
        if (msg.led) setLed(msg.led)
        if (msg.pins) setPins(msg.pins)
        setLastUpdate(Date.now())
      } catch {
        // ignore malformed frames
      }
    }

    ws.onclose = () => {
      setStatus('closed')
      if (!closedByUs.current) scheduleReconnect()
    }

    ws.onerror = () => ws.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url])

  const scheduleReconnect = useCallback(() => {
    attemptsRef.current += 1
    const delay = Math.min(1000 * attemptsRef.current, 5000)
    clearTimeout(reconnectRef.current)
    reconnectRef.current = setTimeout(connect, delay)
  }, [connect])

  useEffect(() => {
    closedByUs.current = false
    connect()
    return () => {
      closedByUs.current = true
      clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { status, stats, led, pins, lastUpdate }
}
