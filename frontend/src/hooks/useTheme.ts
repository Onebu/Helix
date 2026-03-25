import { useState, useEffect, useCallback } from 'react'

type Theme = 'light' | 'dark' | 'system'

function getEffectiveTheme(theme: Theme): 'light' | 'dark' {
  if (theme === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return theme
}

function applyTheme(effective: 'light' | 'dark') {
  if (effective === 'dark') {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(() => {
    const stored = localStorage.getItem('helix-theme')
    if (stored === 'light' || stored === 'dark') return stored
    return 'system'
  })

  const effective = getEffectiveTheme(theme)

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    if (next === 'system') {
      localStorage.removeItem('helix-theme')
    } else {
      localStorage.setItem('helix-theme', next)
    }
    applyTheme(getEffectiveTheme(next))
  }, [])

  // Listen for system preference changes when in 'system' mode
  useEffect(() => {
    if (theme !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = () => applyTheme(getEffectiveTheme('system'))
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [theme])

  // Apply on mount
  useEffect(() => {
    applyTheme(effective)
  }, [effective])

  return { theme, effective, setTheme }
}
