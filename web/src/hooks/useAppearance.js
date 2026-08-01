import { useCallback, useEffect, useState } from 'react'
import { loadAppearance, saveAppearance, applyAppearance } from '../lib/appearance'

// Owns appearance state, persists it, keeps <html> attributes in sync, and
// re-resolves when the OS theme flips (only matters while mode === 'system').
export function useAppearance() {
  const [appearance, setAppearance] = useState(loadAppearance)

  useEffect(() => {
    applyAppearance(appearance)
    saveAppearance(appearance)
  }, [appearance])

  useEffect(() => {
    if (appearance.mode !== 'system') return
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => applyAppearance(appearance)
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [appearance])

  const set = useCallback((patch) => setAppearance((a) => ({ ...a, ...patch })), [])

  return { appearance, set }
}
