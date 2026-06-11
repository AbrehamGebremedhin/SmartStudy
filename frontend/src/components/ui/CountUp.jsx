import { useEffect, useRef, useState } from 'react'

const prefersReduced = () =>
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

// Animates a number from 0 → value on mount with an ease-out curve.
// Non-numeric values (e.g. '—') render via `fallback` with no animation.
export default function CountUp({ value, suffix = '', duration = 900, fallback = '—' }) {
  const target = Number.isFinite(value) ? value : null
  const [display, setDisplay] = useState(() => (prefersReduced() ? target ?? 0 : 0))
  const raf = useRef(0)

  useEffect(() => {
    if (target == null || prefersReduced()) {
      if (target != null) setDisplay(target)
      return
    }
    const start = performance.now()
    const tick = now => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3) // ease-out cubic
      setDisplay(Math.round(eased * target))
      if (t < 1) raf.current = requestAnimationFrame(tick)
    }
    raf.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf.current)
  }, [target, duration])

  if (target == null) return fallback
  return `${display}${suffix}`
}
