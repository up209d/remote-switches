import Meter from './Meter'
import StatTile from './StatTile'
import { formatUptime, formatKb, rssiQuality, signalLabel } from '../lib/format'

export default function HealthSection({ stats, lastUpdate }) {
  const mem = stats?.memory
  const net = stats?.network
  const cpu = stats?.cpu
  const storage = stats?.storage

  return (
    <section className="rounded-2xl border border-line bg-card p-6 theme-shadow backdrop-blur">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-strong">Server Health</h2>
          <p className="text-sm text-muted">{stats?.board || 'Raspberry Pi Pico 2 W'}</p>
        </div>
        <LiveDot lastUpdate={lastUpdate} />
      </div>

      {!stats ? (
        <SkeletonGrid />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Uptime" value={formatUptime(stats.uptime_seconds)} />
            <StatTile label="CPU" value={cpu?.freq_mhz ?? '—'} unit="MHz" />
            <StatTile
              label="Wi-Fi"
              value={net?.rssi_dbm ?? '—'}
              unit="dBm"
              sub={net?.rssi_dbm != null ? signalLabel(net.rssi_dbm) : undefined}
            />
            <StatTile label="IP" value={net?.ip || '—'} size="sm" />
          </div>

          <div className="mt-6 space-y-5">
            <div>
              <Meter
                value={mem?.usage_percent ?? 0}
                label="RAM usage"
                tone="auto"
              />
              <p className="mt-1 text-xs text-faint">
                {formatKb(mem?.used_kb)} used of {formatKb(mem?.total_kb)} · {formatKb(mem?.free_kb)} free
              </p>
            </div>

            {storage?.total_kb ? (
              <div>
                <Meter
                  value={100 - (storage.free_kb / storage.total_kb) * 100}
                  label="Flash storage"
                  tone="sky"
                />
                <p className="mt-1 text-xs text-faint">
                  {formatKb(storage.total_kb - storage.free_kb)} used of {formatKb(storage.total_kb)} ·{' '}
                  {formatKb(storage.free_kb)} free
                </p>
              </div>
            ) : null}

            <div>
              <Meter value={rssiQuality(net?.rssi_dbm)} label="Signal quality" tone="emerald" />
            </div>
          </div>
        </>
      )}
    </section>
  )
}

function LiveDot({ lastUpdate }) {
  const fresh = lastUpdate && Date.now() - lastUpdate < 3000
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-muted">
      <span
        className={`h-2 w-2 rounded-full ${fresh ? 'bg-success' : 'bg-faint'}`}
      />
      live
    </span>
  )
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="h-20 animate-pulse rounded-xl bg-inset" />
      ))}
    </div>
  )
}
