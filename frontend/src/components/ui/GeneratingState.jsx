import { useEffect, useState } from 'react'
import { STUDY_TIPS } from '../../lib/gamification'
import Stele from './Stele'

/**
 * Live stage-by-stage progress display for AI generation (replaces LoadingState).
 *
 * Props:
 *   stageDefs   — [{id, label}, ...] full ordered list of expected stages
 *   currentStageIndex — 0-based index of the active/last-completed stage (-1 = not started)
 *   status      — 'connecting' | 'running' | 'done' | 'error'
 */
export default function GeneratingState({ stageDefs = [], currentStageIndex = -1, status = 'running' }) {
  const [tipIndex, setTipIndex] = useState(() => Math.floor(Math.random() * STUDY_TIPS.length))

  useEffect(() => {
    const iv = setInterval(() => setTipIndex(i => (i + 1) % STUDY_TIPS.length), 4000)
    return () => clearInterval(iv)
  }, [])

  const total = stageDefs.length
  const progressPct = status === 'done'
    ? 100
    : total > 0 ? Math.round(((currentStageIndex + 1) / total) * 100) : 0

  return (
    <div className="gen-progress" role="status" aria-live="polite">
      <Stele mono height={48} className={status === 'running' ? 'gen-stele-pulse' : ''} />

      {/* Progress bar */}
      <div className="gen-bar-track" aria-hidden="true">
        <div
          className="gen-bar-fill"
          style={{ '--gen-progress': `${progressPct}%` }}
        />
      </div>

      {/* Stage list */}
      {total > 0 && (
        <ol className="gen-stages" aria-label="Generation progress">
          {stageDefs.map((s, i) => {
            const isDone = status === 'done' || i < currentStageIndex
            const isActive = status !== 'done' && i === currentStageIndex
            const cls = isDone ? 'gen-stage is-done' : isActive ? 'gen-stage is-active' : 'gen-stage is-pending'
            return (
              <li key={s.id} className={cls}>
                <span className="gen-stage-icon" aria-hidden="true">
                  {isDone ? (
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                      <circle cx="8" cy="8" r="7.5" stroke="currentColor" strokeWidth="1" />
                      <path d="M4.5 8.5L7 11L11.5 5.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  ) : isActive ? (
                    <span className="gen-dot" />
                  ) : (
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                      <circle cx="8" cy="8" r="7.5" stroke="currentColor" strokeWidth="1" />
                    </svg>
                  )}
                </span>
                <span className="gen-stage-label">{s.label}</span>
              </li>
            )
          })}
        </ol>
      )}

      {/* Status text when connecting */}
      {status === 'connecting' && (
        <div className="gen-connecting">Connecting…</div>
      )}

      {/* Rotating study tip */}
      <div className="loading-tip" key={tipIndex}>{STUDY_TIPS[tipIndex]}</div>
    </div>
  )
}
