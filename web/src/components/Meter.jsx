export default function Meter({ value = 0, label, tone = 'emerald' }) {
  const pct = Math.max(0, Math.min(100, value))
  const tones = {
    emerald: 'bg-success',
    amber: 'bg-warn',
    rose: 'bg-danger',
    sky: 'bg-info',
  }
  const color =
    tone === 'auto'
      ? pct > 85
        ? tones.rose
        : pct > 60
          ? tones.amber
          : tones.emerald
      : tones[tone] || tones.emerald

  return (
    <div>
      {label && (
        <div className="mb-1 flex justify-between text-xs text-muted">
          <span>{label}</span>
          <span className="tabular-nums">{pct.toFixed(0)}%</span>
        </div>
      )}
      <div className="h-2 w-full overflow-hidden rounded-full bg-track">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
