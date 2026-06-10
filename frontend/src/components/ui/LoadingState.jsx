import { useState, useEffect } from 'react'
import { STUDY_TIPS } from '../../lib/gamification'

// Shared LLM-wait state: ring + bar + rotating study tip to keep the
// 10–30s generation pause engaging.
export default function LoadingState({ title, sub }) {
  const [tipIndex, setTipIndex] = useState(() => Math.floor(Math.random() * STUDY_TIPS.length))

  useEffect(() => {
    const iv = setInterval(() => setTipIndex(i => (i + 1) % STUDY_TIPS.length), 4000)
    return () => clearInterval(iv)
  }, [])

  return (
    <div className="loading-state">
      <div className="loading-ring" />
      <div className="loading-bar" />
      <div className="loading-title">{title}</div>
      <div className="loading-sub">{sub}</div>
      <div className="loading-tip" key={tipIndex}>{STUDY_TIPS[tipIndex]}</div>
    </div>
  )
}
