import { useState, useEffect } from 'react'
import Icon from './Icon'
import Confetti from './Confetti'

const XP_TTL = 2400
const ACH_TTL = 4200
const COALESCE_WINDOW = 1500

let toastSeq = 0

// Mounted once in AppShell. Renders XP/achievement toasts and the level-up
// takeover, fed by window events dispatched from lib/gamification.js.
export default function GamifyLayer() {
  const [toasts, setToasts] = useState([])
  const [levelUp, setLevelUp] = useState(null)

  useEffect(() => {
    function onXp(e) {
      setToasts(ts => {
        const last = ts[ts.length - 1]
        // Rapid answering: merge consecutive XP toasts into one summed pill
        if (last?.kind === 'xp' && Date.now() - last.at < COALESCE_WINDOW) {
          return [...ts.slice(0, -1), { ...last, gained: last.gained + e.detail.gained, at: Date.now() }]
        }
        return [...ts, { id: ++toastSeq, kind: 'xp', gained: e.detail.gained, at: Date.now() }].slice(-3)
      })
    }
    function onAchievement(e) {
      setToasts(ts => [...ts, { id: ++toastSeq, kind: 'ach', achievement: e.detail.achievement, at: Date.now() }].slice(-3))
    }
    function onLevelUp(e) {
      setLevelUp(e.detail.level)
    }
    window.addEventListener('ss:xp', onXp)
    window.addEventListener('ss:achievement', onAchievement)
    window.addEventListener('ss:levelup', onLevelUp)
    return () => {
      window.removeEventListener('ss:xp', onXp)
      window.removeEventListener('ss:achievement', onAchievement)
      window.removeEventListener('ss:levelup', onLevelUp)
    }
  }, [])

  const hasToasts = toasts.length > 0
  useEffect(() => {
    if (!hasToasts) return
    const iv = setInterval(() => {
      const now = Date.now()
      setToasts(ts => ts.filter(t => now - t.at < (t.kind === 'ach' ? ACH_TTL : XP_TTL)))
    }, 300)
    return () => clearInterval(iv)
  }, [hasToasts])

  return (
    <>
      <div className="tx-stack" aria-live="polite">
        {toasts.map(t =>
          t.kind === 'xp' ? (
            <div key={t.id} className="tx-item tx-xp">
              <Icon name="star" size={15} />
              +{t.gained} XP
            </div>
          ) : (
            <div key={t.id} className="tx-item tx-ach">
              <Icon name={t.achievement.icon ?? 'trophy'} size={18} />
              <span>
                <span className="tx-ach-kicker">Achievement unlocked</span>
                {t.achievement.name}
                {t.achievement.geez ? ` · ${t.achievement.geez}` : ''}
              </span>
            </div>
          )
        )}
      </div>

      {levelUp && (
        <div className="modal-backdrop" onClick={() => setLevelUp(null)}>
          <div className="lvlup-card" onClick={e => e.stopPropagation()}>
            <Confetti />
            <div className="lvlup-kicker">Level up</div>
            <div className="lvlup-geez">{levelUp.geez}</div>
            <div className="lvlup-name">{levelUp.name} — {levelUp.translation}</div>
            <div className="lvlup-sub">
              You’ve reached a new rank on the path to mastery. በርታ — keep going!
            </div>
            <button className="btn btn-ochre" onClick={() => setLevelUp(null)}>
              Continue
            </button>
          </div>
        </div>
      )}
    </>
  )
}
