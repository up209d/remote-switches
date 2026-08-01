export default function StatTile({ label, value, unit, sub, size = 'default' }) {
  const valueSize = size === 'sm' ? 'text-sm sm:text-base' : 'text-2xl'
  return (
    <div className="min-w-0 rounded-xl border border-line bg-inset p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className={`${valueSize} min-w-0 break-all font-semibold tabular-nums text-strong`}>
          {value}
        </span>
        {unit && <span className="shrink-0 text-sm text-muted">{unit}</span>}
      </div>
      {sub && <div className="mt-1 text-xs text-faint">{sub}</div>}
    </div>
  )
}
