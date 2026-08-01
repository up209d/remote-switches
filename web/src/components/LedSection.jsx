import { useEffect, useState } from 'react'
import { usePatternPreview } from '../hooks/usePatternPreview'
import { morseString } from '../lib/morse'

const MODES = [
  { key: 'fixed', label: 'Fixed' },
  { key: 'tick', label: 'Tick' },
  { key: 'morse', label: 'Morse' },
]

export default function LedSection({ led, send, disabled }) {
  const [tab, setTab] = useState(led?.mode || 'tick')
  // Client-side visual simulation (does not touch the backend). null = off.
  const [preview, setPreview] = useState(null)

  const switchTab = (key) => {
    setPreview(null) // stop any preview when leaving the panel
    setTab(key)
  }

  return (
    <section className="rounded-2xl border border-line bg-card p-6 theme-shadow backdrop-blur">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-strong">Onboard LED</h2>
          <p className="text-sm text-muted">Fixed · Tick · Morse</p>
        </div>
        <StateBadge led={led} />
      </div>

      <Bulb led={led} preview={preview} />

      {/* Mode tabs */}
      <div className="mb-5 grid grid-cols-3 gap-1 rounded-xl border border-line bg-field p-1">
        {MODES.map((m) => (
          <button
            key={m.key}
            onClick={() => switchTab(m.key)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
              tab === m.key
                ? 'bg-raised text-strong'
                : 'text-muted hover:text-strong'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>

      {tab === 'fixed' && <FixedPanel led={led} send={send} disabled={disabled} />}
      {tab === 'tick' && (
        <TickPanel led={led} send={send} disabled={disabled} preview={preview} setPreview={setPreview} />
      )}
      {tab === 'morse' && (
        <MorsePanel led={led} send={send} disabled={disabled} preview={preview} setPreview={setPreview} />
      )}
    </section>
  )
}

/* ----------------------------- Fixed ----------------------------- */
function FixedPanel({ led, send, disabled }) {
  const isFixed = led?.mode === 'fixed'
  return (
    <div className="flex gap-2">
      <Button
        onClick={() => send({ mode: 'fixed', on: true })}
        disabled={disabled || (isFixed && led?.on)}
        active={isFixed && led?.on}
      >
        Fixed On
      </Button>
      <Button
        onClick={() => send({ mode: 'fixed', on: false })}
        disabled={disabled || (isFixed && !led?.on)}
        active={isFixed && !led?.on}
      >
        Fixed Off
      </Button>
    </div>
  )
}

/* ------------------------------ Tick ----------------------------- */
function TickPanel({ led, send, disabled, preview, setPreview }) {
  const [onMs, setOnMs] = useState(led?.mode === 'tick' ? led.on_ms : 500)
  const [offMs, setOffMs] = useState(led?.mode === 'tick' ? led.off_ms : 500)
  const running = led?.mode === 'tick' && led.on_ms === onMs && led.off_ms === offMs
  const previewing = preview?.mode === 'tick'

  // Keep the preview in sync while it's active and the sliders move.
  useEffect(() => {
    if (previewing) setPreview({ mode: 'tick', onMs, offMs })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onMs, offMs, previewing])

  return (
    <div className="space-y-4">
      <Slider label="On duration" value={onMs} min={20} max={2000} step={20} onChange={setOnMs} unit="ms" />
      <Slider label="Off duration" value={offMs} min={20} max={2000} step={20} onChange={setOffMs} unit="ms" />
      <div className="flex gap-2">
        <Button
          onClick={() => send({ mode: 'tick', on_ms: onMs, off_ms: offMs })}
          disabled={disabled || running}
          active={running}
        >
          {running ? 'Running' : 'Start ticking'}
        </Button>
        <Button onClick={() => send({ mode: 'fixed', on: false })} disabled={disabled}>
          Stop
        </Button>
        <PreviewButton
          previewing={previewing}
          onClick={() => setPreview(previewing ? null : { mode: 'tick', onMs, offMs })}
        />
      </div>
    </div>
  )
}

/* ------------------------------ Morse ---------------------------- */
function MorsePanel({ led, send, disabled, preview, setPreview }) {
  const [message, setMessage] = useState(led?.mode === 'morse' ? led.message : 'SOS')
  const [wpm, setWpm] = useState(led?.mode === 'morse' ? led.wpm : 10)
  // Only "running" when the device is transmitting these exact params, so
  // editing the message/speed re-enables the button to send the change.
  const running = led?.mode === 'morse' && led.message === message && led.wpm === wpm
  const previewing = preview?.mode === 'morse'

  useEffect(() => {
    if (previewing) setPreview({ mode: 'morse', message, wpm })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message, wpm, previewing])

  return (
    <div className="space-y-4">
      <div>
        <label className="mb-1 block text-sm text-muted">Message</label>
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          maxLength={60}
          placeholder="SOS"
          className="w-full rounded-lg border border-fieldln bg-field px-3 py-2 text-sm text-strong outline-none focus:border-primary"
        />
        <MorsePreview message={message} />
      </div>
      <Slider label="Speed" value={wpm} min={5} max={25} step={1} onChange={setWpm} unit="WPM" />
      <div className="flex gap-2">
        <Button
          onClick={() => send({ mode: 'morse', message, wpm })}
          disabled={disabled || !message.trim() || running}
          active={running}
        >
          {running ? 'Transmitting' : 'Send in Morse'}
        </Button>
        <Button onClick={() => send({ mode: 'fixed', on: false })} disabled={disabled}>
          Stop
        </Button>
        <PreviewButton
          previewing={previewing}
          disabled={!message.trim()}
          onClick={() => setPreview(previewing ? null : { mode: 'morse', message, wpm })}
        />
      </div>
    </div>
  )
}

function MorsePreview({ message }) {
  const code = morseString(message)
  if (!code) return null
  return <p className="mt-2 font-mono text-sm tracking-widest text-morse">{code}</p>
}

/* --------------------------- primitives -------------------------- */
function Slider({ label, value, min, max, step, onChange, unit }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label className="text-sm text-muted">{label}</label>
        <span className="text-xs tabular-nums text-body">
          {value} {unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-primary"
      />
    </div>
  )
}

function Button({ children, onClick, disabled, active }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? 'bg-primary text-onprimary hover:bg-primaryhover'
          : 'border border-fieldln bg-raised/60 text-body hover:bg-raised'
      }`}
    >
      {children}
    </button>
  )
}

function PreviewButton({ previewing, onClick, disabled }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`ml-auto rounded-lg border px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        previewing
          ? 'border-warn/40 bg-warn/15 text-warn hover:bg-warn/25'
          : 'border-fieldln bg-raised/60 text-body hover:bg-raised'
      }`}
    >
      {previewing ? 'Stop preview' : 'Preview'}
    </button>
  )
}

function Bulb({ led, preview }) {
  // When previewing, the bulb follows the simulated timeline. Otherwise it
  // shows the device's *active* state: lit for Fixed On / Ticking / Morse,
  // dark for Fixed Off. We deliberately don't use led.on here — that's the
  // instantaneous blink level sampled only ~1/s, which flickers unpredictably.
  const previewOn = usePatternPreview(preview)
  const liveActive =
    led?.mode === 'fixed' ? !!led.on : led?.mode === 'tick' || led?.mode === 'morse'
  const on = preview ? previewOn : liveActive

  return (
    <div className="mb-6 flex flex-col items-center gap-2">
      {/* No CSS transition: on/off must be instant to mimic real blinking. */}
      <div
        className={`flex h-24 w-24 items-center justify-center rounded-full border ${
          on
            ? 'border-success/50 bg-success/20 shadow-[0_0_45px_-5px] shadow-success/70'
            : 'border-line bg-inset'
        }`}
      >
        <svg
          viewBox="0 0 24 24"
          className={`h-10 w-10 ${on ? 'text-success' : 'text-faint'}`}
          fill="currentColor"
        >
          <path d="M9 21c0 .55.45 1 1 1h4c.55 0 1-.45 1-1v-1H9v1zm3-19C8.14 2 5 5.14 5 9c0 2.38 1.19 4.47 3 5.74V17c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-2.26c1.81-1.27 3-3.36 3-5.74 0-3.86-3.14-7-7-7z" />
        </svg>
      </div>
      <span className="h-4 text-xs text-faint">
        {preview ? `Previewing ${preview.mode} (not sent to device)` : ''}
      </span>
    </div>
  )
}

function StateBadge({ led }) {
  let label = 'Off'
  let cls = 'bg-raised/40 text-muted border-line'
  if (led?.mode === 'fixed') {
    label = led.on ? 'Fixed On' : 'Fixed Off'
    cls = led.on
      ? 'bg-warn/15 text-warn border-warn/30'
      : 'bg-raised/40 text-muted border-line'
  } else if (led?.mode === 'tick') {
    label = `Tick ${led.on_ms}/${led.off_ms}ms`
    cls = 'bg-info/15 text-info border-info/30'
  } else if (led?.mode === 'morse') {
    label = `Morse · ${led.message}`
    cls = 'bg-morse/15 text-morse border-morse/30'
  }
  return <span className={`rounded-full border px-3 py-1 text-xs font-medium ${cls}`}>{label}</span>
}
