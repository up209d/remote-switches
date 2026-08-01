import { useEffect, useRef, useState } from 'react'

// Momentary keep-alive interval. Must be comfortably under the server-side
// deadman (DEADMAN_MS = 1500ms) so a held button never lets the pin lapse.
const KEEPALIVE_MS = 600
const DRIVE_MODES = [
  { key: 'momentary', label: 'Momentary' },
  { key: 'toggle', label: 'Toggle' },
  { key: 'pulse', label: 'Pulse' },
]

export default function PinsSection({ pins, sendPin, disabled }) {
  // Per-pin interaction mode is a UI concept only; the device just knows a pin
  // is an output at some level. Defaults to 'toggle' when a pin is armed.
  const [driveMode, setDriveMode] = useState({})
  const armed = pins?.filter((p) => p.mode === 'out') ?? []

  const setMode = (gpio, mode) => setDriveMode((m) => ({ ...m, [gpio]: mode }))
  const arm = (gpio) => {
    setMode(gpio, driveMode[gpio] || 'toggle')
    sendPin({ gpio, op: 'arm' })
  }
  const release = (gpio) => sendPin({ gpio, op: 'release' })
  const releaseAll = () => sendPin(armed.map((p) => ({ gpio: p.gpio, op: 'release' })))

  return (
    <section className="rounded-2xl border border-line bg-card p-6 theme-shadow backdrop-blur">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-strong">GPIO Pins</h2>
          <p className="text-sm text-muted">
            Click a pin to drive it as an output (GP23–25, GP29 are Wi-Fi and hidden)
          </p>
        </div>
        <Legend />
      </div>

      {!pins ? (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
          {Array.from({ length: 26 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-lg bg-inset" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
          {pins.map((p) => (
            <PinChip key={p.gpio} pin={p} disabled={disabled} onArm={() => arm(p.gpio)} />
          ))}
        </div>
      )}

      {armed.length > 0 && (
        <div className="mt-5 rounded-xl border border-info/30 bg-info/5 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-info">
              Output controls
              <span className="ml-2 text-xs font-normal text-muted">
                {armed.length} pin{armed.length > 1 ? 's' : ''} driven
              </span>
            </h3>
            <button
              onClick={releaseAll}
              disabled={disabled}
              className="rounded-lg border border-fieldln bg-raised/60 px-3 py-1 text-xs font-medium text-body hover:bg-raised disabled:cursor-not-allowed disabled:opacity-40"
            >
              Release all
            </button>
          </div>
          <div className="space-y-2">
            {armed.map((p) => (
              <OutputRow
                key={p.gpio}
                pin={p}
                mode={driveMode[p.gpio] || 'toggle'}
                onMode={(m) => setMode(p.gpio, m)}
                onRelease={() => release(p.gpio)}
                sendPin={sendPin}
                disabled={disabled}
              />
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

/* ------------------------------- chip ---------------------------------- */
function PinChip({ pin, disabled, onArm }) {
  const high = pin.value === 1
  const unknown = pin.value == null
  const out = pin.mode === 'out'

  const base = 'flex items-center justify-between rounded-lg border px-3 py-2 text-left transition-colors'
  const tone = out
    ? 'border-info/50 bg-info/10'
    : high
    ? 'border-success/40 bg-success/10'
    : 'border-line bg-inset'

  const inner = (
    <>
      <div className="flex flex-col leading-tight">
        <span className="text-sm font-medium text-body">GP{pin.gpio}</span>
        {out ? (
          <span className="text-[10px] font-semibold uppercase text-info">out</span>
        ) : (
          pin.adc && <span className="text-[10px] uppercase text-faint">adc</span>
        )}
      </div>
      <div className="flex items-center gap-1.5">
        <span
          className={`h-2.5 w-2.5 rounded-full ${
            unknown ? 'bg-faint' : high ? 'bg-success' : 'bg-faint'
          }`}
        />
        <span
          className={`text-xs font-semibold tabular-nums ${high ? 'text-success' : 'text-muted'}`}
        >
          {unknown ? '—' : high ? 'HIGH' : 'LOW'}
        </span>
      </div>
    </>
  )

  // Armed pins are controlled from the panel below, so the chip is passive.
  if (out) return <div className={`${base} ${tone}`}>{inner}</div>

  return (
    <button
      onClick={onArm}
      disabled={disabled}
      title="Drive this pin as an output"
      className={`${base} ${tone} hover:border-info/40 hover:bg-inset disabled:cursor-not-allowed disabled:opacity-60`}
    >
      {inner}
    </button>
  )
}

/* --------------------------- output control row ------------------------ */
function OutputRow({ pin, mode, onMode, onRelease, sendPin, disabled }) {
  const high = pin.value === 1
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-inset px-3 py-2">
      <span className="w-12 text-sm font-medium text-body">GP{pin.gpio}</span>
      <StatePill high={high} />

      {/* Mode selector */}
      <div className="flex rounded-lg border border-line bg-field p-0.5">
        {DRIVE_MODES.map((m) => (
          <button
            key={m.key}
            onClick={() => onMode(m.key)}
            className={`rounded-md px-2 py-1 text-xs font-medium ${
              mode === m.key ? 'bg-raised text-strong' : 'text-muted hover:text-strong'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="ml-auto flex items-center gap-2">
        {mode === 'momentary' && <MomentaryButton gpio={pin.gpio} high={high} sendPin={sendPin} disabled={disabled} />}
        {mode === 'toggle' && <ToggleControl gpio={pin.gpio} high={high} sendPin={sendPin} disabled={disabled} />}
        {mode === 'pulse' && <PulseControl gpio={pin.gpio} sendPin={sendPin} disabled={disabled} />}
        <button
          onClick={onRelease}
          disabled={disabled}
          title="Release back to monitor (input)"
          className="rounded-md border border-fieldln px-2 py-1 text-xs text-muted hover:bg-raised hover:text-strong disabled:cursor-not-allowed disabled:opacity-40"
        >
          Release
        </button>
      </div>
    </div>
  )
}

/* Press-and-hold: HIGH while held, LOW on release. A keep-alive re-sends HIGH
   so the server deadman never trips mid-press; every release path (up, cancel,
   pointer leaving the captured button) sends LOW so a pin can't get stuck on. */
function MomentaryButton({ gpio, high, sendPin, disabled }) {
  const timer = useRef(null)

  const stop = () => {
    if (timer.current) {
      clearInterval(timer.current)
      timer.current = null
      sendPin({ gpio, op: 'hold', value: 0 })
    }
  }
  useEffect(() => () => timer.current && clearInterval(timer.current), [])

  const start = (e) => {
    if (disabled || timer.current) return
    e.currentTarget.setPointerCapture?.(e.pointerId)
    sendPin({ gpio, op: 'hold', value: 1 })
    timer.current = setInterval(() => sendPin({ gpio, op: 'hold', value: 1 }), KEEPALIVE_MS)
  }

  return (
    <button
      onPointerDown={start}
      onPointerUp={stop}
      onPointerLeave={stop}
      onPointerCancel={stop}
      disabled={disabled}
      className={`select-none rounded-md px-4 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        high
          ? 'bg-primary text-onprimary'
          : 'border border-fieldln bg-raised/60 text-body hover:bg-raised'
      }`}
    >
      Hold HIGH
    </button>
  )
}

/* Latch: click flips and persists the level. */
function ToggleControl({ gpio, high, sendPin, disabled }) {
  return (
    <button
      onClick={() => sendPin({ gpio, op: 'write', value: high ? 0 : 1 })}
      disabled={disabled}
      role="switch"
      aria-checked={high}
      className={`relative h-7 w-14 rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        high ? 'bg-primary' : 'bg-faint'
      }`}
    >
      <span
        className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition-all ${
          high ? 'left-[30px]' : 'left-0.5'
        }`}
      />
    </button>
  )
}

/* Fire a fixed-width HIGH pulse; the server times the auto-LOW. */
function PulseControl({ gpio, sendPin, disabled }) {
  const [ms, setMs] = useState(250)
  return (
    <div className="flex items-center gap-1.5">
      <input
        type="number"
        min={20}
        max={5000}
        step={10}
        value={ms}
        onChange={(e) => setMs(Number(e.target.value))}
        className="w-16 rounded-md border border-fieldln bg-field px-2 py-1 text-sm text-strong outline-none focus:border-info"
      />
      <span className="text-xs text-faint">ms</span>
      <button
        onClick={() => sendPin({ gpio, op: 'pulse', ms })}
        disabled={disabled}
        className="rounded-md border border-fieldln bg-raised/60 px-3 py-1.5 text-sm font-medium text-body hover:bg-raised disabled:cursor-not-allowed disabled:opacity-40"
      >
        Pulse
      </button>
    </div>
  )
}

/* ------------------------------ bits ----------------------------------- */
function StatePill({ high }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
        high ? 'bg-success/15 text-success' : 'bg-raised/50 text-muted'
      }`}
    >
      {high ? 'HIGH' : 'LOW'}
    </span>
  )
}

function Legend() {
  return (
    <div className="flex items-center gap-3 text-xs text-muted">
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-full bg-success" /> HIGH
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-full bg-faint" /> LOW
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-full bg-info" /> OUT
      </span>
    </div>
  )
}
