const KEY = 'ss_theme'

export function getTheme() {
  return localStorage.getItem(KEY) ??
    (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
}

export function setTheme(theme) {
  localStorage.setItem(KEY, theme)
  document.documentElement.dataset.theme = theme
}

/** Call once at startup, before first paint, to avoid a flash of the wrong theme. */
export function initTheme() {
  document.documentElement.dataset.theme = getTheme()
}
