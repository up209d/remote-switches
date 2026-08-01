import { MODES, SCHEMES, PATTERNS } from '../lib/appearance'

// Full-screen appearance page (mobile-first): a back button returns to the
// dashboard. Changes apply live, so the page itself recolours as you pick.
export default function SettingsView({ appearance, set, onBack }) {
  return (
    <div className="mx-auto max-w-3xl px-4 py-6 sm:py-8">
      <header className="mb-8 flex items-center gap-3">
        <button
          onClick={onBack}
          className="flex h-10 w-10 items-center justify-center rounded-xl border border-line bg-card text-body hover:text-strong"
          aria-label="Back to dashboard"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <div>
          <h1 className="text-xl font-bold text-strong">Settings</h1>
          <p className="text-sm text-muted">Appearance</p>
        </div>
      </header>

      <div className="space-y-8">
        {/* Mode */}
        <Group title="Theme mode" hint="System follows your device's light/dark setting.">
          <div className="inline-flex rounded-xl border border-line bg-inset p-1">
            {MODES.map((m) => (
              <button
                key={m.key}
                onClick={() => set({ mode: m.key })}
                aria-pressed={appearance.mode === m.key}
                className={`rounded-lg px-4 py-1.5 text-sm font-medium transition-colors ${
                  appearance.mode === m.key
                    ? 'bg-primary text-onprimary'
                    : 'text-muted hover:text-strong'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </Group>

        {/* Colour scheme */}
        <Group title="Colour scheme" hint="Accent schemes keep the calm slate surfaces; dramatic ones re-skin everything.">
          {['Accent', 'Dramatic'].map((grp) => (
            <div key={grp} className="mb-3 last:mb-0">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">{grp}</div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {SCHEMES.filter((s) => s.group === grp).map((s) => (
                  <button
                    key={s.key}
                    onClick={() => set({ scheme: s.key })}
                    aria-pressed={appearance.scheme === s.key}
                    className={`flex items-center gap-2.5 rounded-xl border px-3 py-2.5 text-left transition-colors ${
                      appearance.scheme === s.key
                        ? 'border-primary bg-primary/10'
                        : 'border-line bg-inset hover:border-fieldln'
                    }`}
                  >
                    <span className="h-5 w-5 shrink-0 rounded-full" style={{ background: s.swatch }} />
                    <span className={`text-sm font-medium ${appearance.scheme === s.key ? 'text-strong' : 'text-body'}`}>
                      {s.name}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </Group>

        {/* Background pattern */}
        <Group title="Background pattern" hint="A subtle texture behind the dashboard. Adapts to the scheme automatically.">
          {['Basic', 'Tech', 'FX'].map((grp) => (
            <div key={grp} className="mb-3 last:mb-0">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">{grp}</div>
              <div className="flex flex-wrap gap-2">
                {PATTERNS.filter((p) => p.group === grp).map((p) => (
                  <button
                    key={p.key}
                    onClick={() => set({ pattern: p.key })}
                    aria-pressed={appearance.pattern === p.key}
                    className={`rounded-lg border px-3.5 py-2 text-sm font-medium transition-colors ${
                      appearance.pattern === p.key
                        ? 'border-primary bg-primary/10 text-strong'
                        : 'border-line bg-inset text-body hover:border-fieldln'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </Group>
      </div>

      <p className="mt-10 text-center text-xs text-faint">Your choices are saved on this device.</p>
    </div>
  )
}

function Group({ title, hint, children }) {
  return (
    <section className="rounded-2xl border border-line bg-card p-5 theme-shadow sm:p-6">
      <h2 className="text-base font-semibold text-strong">{title}</h2>
      {hint && <p className="mb-4 mt-1 text-sm text-muted">{hint}</p>}
      {children}
    </section>
  )
}
