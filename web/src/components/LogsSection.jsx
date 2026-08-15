import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchLogs, fetchLogTail } from '../lib/api'

// The device keeps bounded log files on flash (tunnel.log today). Reading them
// over USB interrupts the running app, so the settings page reads them over
// HTTP instead: GET /api/logs to list, GET /api/logs/tail for the last N lines.
const LINE_CHOICES = [100, 200, 500]

const fmtSize = (bytes) => (bytes < 1024 ? `${bytes} B` : `${(bytes / 1024).toFixed(1)} KB`)

export default function LogsSection({ host }) {
  const [picked, setPicked] = useState(null)
  const [lines, setLines] = useState(200)
  const boxRef = useRef(null)

  const list = useQuery({
    queryKey: ['logs', host],
    queryFn: () => fetchLogs(host),
    enabled: !!host,
  })

  const files = list.data?.files ?? []
  // Whatever's picked can disappear between refreshes; fall back to the first.
  const name = files.some((f) => f.name === picked) ? picked : files[0]?.name ?? null

  const tail = useQuery({
    queryKey: ['log-tail', host, name, lines],
    queryFn: () => fetchLogTail(host, name, lines),
    enabled: !!host && !!name,
  })

  // Newest lines are at the bottom, so land there whenever fresh text arrives.
  useEffect(() => {
    const el = boxRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [tail.data])

  const refresh = () => {
    list.refetch()
    tail.refetch()
  }

  if (!host) return <p className="text-sm text-muted">Set the Pico address to read its logs.</p>

  if (list.isError)
    return <p className="text-sm text-danger">Couldn't list the logs: {list.error.message}</p>

  if (list.isLoading) return <p className="text-sm text-muted">Loading…</p>

  if (!files.length) return <p className="text-sm text-muted">No log files on the device yet.</p>

  return (
    <div>
      {/* File picker */}
      <div className="flex flex-wrap gap-2">
        {files.map((f) => (
          <button
            key={f.name}
            onClick={() => setPicked(f.name)}
            aria-pressed={name === f.name}
            className={`rounded-lg border px-3.5 py-2 text-left text-sm transition-colors ${
              name === f.name
                ? 'border-primary bg-primary/10 text-strong'
                : 'border-line bg-inset text-body hover:border-fieldln'
            }`}
          >
            <span className="font-mono font-medium">{f.name}</span>
            <span className="ml-2 text-xs text-faint">{fmtSize(f.size)}</span>
          </button>
        ))}
      </div>

      {/* How much of it to pull back, and a manual refresh */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-faint">Last</span>
        <div className="inline-flex rounded-xl border border-line bg-inset p-1">
          {LINE_CHOICES.map((n) => (
            <button
              key={n}
              onClick={() => setLines(n)}
              aria-pressed={lines === n}
              className={`rounded-lg px-3 py-1 text-sm font-medium transition-colors ${
                lines === n ? 'bg-primary text-onprimary' : 'text-muted hover:text-strong'
              }`}
            >
              {n}
            </button>
          ))}
        </div>
        <span className="text-xs text-faint">lines</span>
        <button
          onClick={refresh}
          disabled={tail.isFetching}
          className="ml-auto rounded-lg border border-line bg-inset px-3.5 py-2 text-sm font-medium text-body hover:border-fieldln hover:text-strong disabled:opacity-50"
        >
          {tail.isFetching ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {tail.isError && (
        <p className="mt-3 text-sm text-danger">Couldn't read {name}: {tail.error.message}</p>
      )}

      <pre
        ref={boxRef}
        className="mt-3 h-72 overflow-auto whitespace-pre rounded-xl border border-line bg-field p-3 font-mono text-xs leading-relaxed text-body"
      >
        {tail.data?.trimEnd() || (tail.isFetching ? 'Loading…' : '(empty)')}
      </pre>
    </div>
  )
}
