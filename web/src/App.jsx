import { useState } from 'react'
import { useHealthSocket } from './hooks/useHealthSocket'
import { useLedCommand, usePinCommand } from './hooks/usePico'
import { useAppearance } from './hooks/useAppearance'
import { getPicoHost, setPicoHost, isDev } from './lib/api'
import ConnectionStatus from './components/ConnectionStatus'
import HealthSection from './components/HealthSection'
import LedSection from './components/LedSection'
import PinsSection from './components/PinsSection'
import SettingsView from './components/SettingsView'

export default function App() {
  const [host, setHost] = useState(getPicoHost)
  const [draft, setDraft] = useState(host)
  const [view, setView] = useState('dash')
  const { appearance, set } = useAppearance()

  // Live stats stream over WebSocket; LED commands over HTTP (TanStack Query).
  const socket = useHealthSocket(host)
  const command = useLedCommand(host)
  const pinCommand = usePinCommand(host)

  const stats = socket.stats
  const led = socket.led
  const status = !host ? 'closed' : socket.status

  const disabled = status !== 'open' || command.isPending
  const send = (cmd) => command.mutate(cmd)
  // Pin commands fire rapidly (momentary keep-alives), so they don't gate on
  // isPending — just require an open connection.
  const pinsDisabled = status !== 'open'
  const sendPin = (cmd) => pinCommand.mutate(cmd)

  const applyHost = (e) => {
    e.preventDefault()
    setHost(setPicoHost(draft))
  }

  return (
    <div className="app-bg text-body">
      {view === 'settings' ? (
        <SettingsView appearance={appearance} set={set} onBack={() => setView('dash')} />
      ) : (
        <div className="mx-auto max-w-3xl px-4 py-8 sm:py-12">
          {/* Header */}
          <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <div className="theme-logo flex h-11 w-11 items-center justify-center rounded-xl text-xl font-bold text-white shadow-lg">
                π
              </div>
              <div>
                <h1 className="text-xl font-bold text-strong">Pico 2 W Dashboard</h1>
                <p className="text-sm text-muted">Live control &amp; monitoring</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <ConnectionStatus status={status} />
              <button
                onClick={() => setView('settings')}
                aria-label="Settings"
                className="flex h-10 w-10 items-center justify-center rounded-xl border border-line bg-card text-body hover:text-strong"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <path d="M3 6h18M3 12h18M3 18h18" />
                </svg>
              </button>
            </div>
          </header>

          {/* Host config (dev only — in production the app is served by the Pico) */}
          {isDev() && (
            <form
              onSubmit={applyHost}
              className="mb-6 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-inset p-3"
            >
              <label className="text-sm text-muted">Pico address</label>
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="192.168.1.50"
                className="flex-1 rounded-lg border border-fieldln bg-field px-3 py-1.5 text-sm text-strong outline-none focus:border-primary"
              />
              <button
                type="submit"
                className="rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-onprimary hover:bg-primaryhover"
              >
                Connect
              </button>
              <p className="w-full text-xs text-muted">
                No device? Enter your Pico's IP above, or{' '}
                <button
                  type="button"
                  onClick={() => setDraft(window.location.host)}
                  className="font-mono text-primary underline underline-offset-2 hover:text-primaryhover"
                >
                  {window.location.host}
                </button>{' '}
                to use the built-in mock server.
              </p>
            </form>
          )}

          {status === 'closed' && host && (
            <div className="mb-6 rounded-xl border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
              Can't reach the Pico at <span className="font-mono">{host}</span>. Check that it's
              powered on and on the same network.
            </div>
          )}

          {/* Sections */}
          <div className="space-y-6">
            <HealthSection stats={stats} lastUpdate={socket.lastUpdate} />
            <PinsSection pins={socket.pins} sendPin={sendPin} disabled={pinsDisabled} />
            <LedSection led={led} send={send} disabled={disabled} />
          </div>

          <footer className="mt-10 text-center text-xs text-faint">
            {host
              ? `Live stats via ws://${host}/api/ws/health · commands via POST /api/blink & /api/pin`
              : 'Set the Pico address to connect'}
          </footer>
        </div>
      )}
    </div>
  )
}
