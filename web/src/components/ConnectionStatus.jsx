const MAP = {
  open: { label: 'Connected', dot: 'bg-success', ring: 'bg-success/30', text: 'text-success' },
  connecting: { label: 'Connecting…', dot: 'bg-warn', ring: 'bg-warn/30', text: 'text-warn' },
  closed: { label: 'Disconnected', dot: 'bg-danger', ring: 'bg-danger/30', text: 'text-danger' },
}

export default function ConnectionStatus({ status }) {
  const s = MAP[status] || MAP.closed
  return (
    <div className="inline-flex items-center gap-2 rounded-full border border-line bg-card px-3 py-1.5">
      <span className="relative flex h-2.5 w-2.5">
        {status !== 'closed' && (
          <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${s.ring}`} />
        )}
        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${s.dot}`} />
      </span>
      <span className={`text-sm font-medium ${s.text}`}>{s.label}</span>
    </div>
  )
}
