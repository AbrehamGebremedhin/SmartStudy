import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getHistory, getHistoryByType } from '../services/history.service'
import { typeIcon, subjectLabel } from '../lib/curriculum'
import { loadGeneration, routeForType } from '../lib/genStorage'
import { getLevelInfo, getStreak, getStats, getAchievements } from '../lib/gamification'
import Icon from '../components/ui/Icon'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import ActivityHeatmap from '../components/ui/ActivityHeatmap'
import CountUp from '../components/ui/CountUp'

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'mcq', label: 'MCQs' },
  { key: 'flashcard', label: 'Flashcards' },
  { key: 'notes', label: 'Notes' },
]

export default function History() {
  const [filter, setFilter] = useState('all')
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [showAch, setShowAch] = useState(false)
  const navigate = useNavigate()

  // localStorage reads are idempotent — safe as lazy initializers under StrictMode
  const [level] = useState(() => getLevelInfo())
  const [streak] = useState(() => getStreak())
  const [stats] = useState(() => getStats())
  const [achievements] = useState(() => getAchievements())
  const unlockedCount = achievements.filter(a => a.unlockedAt).length

  function load() {
    setLoading(true)
    setError(null)
    const req = filter === 'all' ? getHistory() : getHistoryByType(filter)
    req
      .then(setItems)
      .catch(setError)
      .finally(() => setLoading(false))
  }

  useEffect(load, [filter])

  function formatDate(iso) {
    if (!iso) return ''
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  function itemTitle(item) {
    const p = item.request_params ?? {}
    const subject = subjectLabel(p.subject ?? '')
    const grade = p.grade ? `Grade ${p.grade}` : ''
    const unit = p.unit ? `Unit ${p.unit}` : ''
    return [subject, grade, unit].filter(Boolean).join(' — ') || item.type
  }

  function itemMeta(item) {
    const p = item.request_params ?? {}
    const parts = []
    if (p.num_questions) parts.push(`${p.num_questions} questions`)
    if (p.num_cards) parts.push(`${p.num_cards} cards`)
    if (p.difficulty) parts.push(p.difficulty.charAt(0).toUpperCase() + p.difficulty.slice(1))
    if (item.accessed_at) parts.push(formatDate(item.accessed_at))
    return parts.join(' · ')
  }

  function scoreTag(item) {
    const saved = loadGeneration(item.generation_id)
    if (!saved) return null
    if (item.type === 'mcq' && saved.score) {
      const { correct, total } = saved.score
      const pct = Math.round((correct / total) * 100)
      const cls = pct >= 80 ? 'hs-high' : pct >= 50 ? 'hs-mid' : 'hs-low'
      return <span className={`h-score ${cls}`}>{correct}/{total}</span>
    }
    if (item.type === 'flashcard' && saved.ratings && saved.cards?.length) {
      const known = saved.cards.filter((_, i) => saved.ratings[i] === 'known').length
      if (Object.keys(saved.ratings).length === 0) return null
      const pct = Math.round((known / saved.cards.length) * 100)
      const cls = pct >= 80 ? 'hs-high' : pct >= 50 ? 'hs-mid' : 'hs-low'
      return <span className={`h-score ${cls}`}>{known}/{saved.cards.length}</span>
    }
    return null
  }

  function handleOpen(item) {
    const route = routeForType(item.type)
    navigate(`${route}?gen=${item.generation_id}`)
  }

  return (
    <>
      <div className="pg-top">
        <h2>Progress</h2>
        <p>Your journey, achievements, and past sessions</p>
      </div>
      <div className="pg-body">
        <div className="ins-strip anim">
          <div className="ins-box">
            <div className="ins-v ins-geez">{level.geez}</div>
            <div className="ins-l">{level.xp} XP · {level.translation}</div>
          </div>
          <div className="ins-box">
            <div className="ins-v ins-flame">
              <Icon name="flame" size={17} /> {streak.current}
            </div>
            <div className="ins-l">Day streak · best {streak.best}</div>
          </div>
          <div className="ins-box">
            <div className="ins-v"><CountUp value={stats.questionsAnswered} /></div>
            <div className="ins-l">Questions answered</div>
          </div>
          <div className="ins-box">
            <div className="ins-v"><CountUp value={stats.accuracyPct != null ? stats.accuracyPct : NaN} suffix="%" /></div>
            <div className="ins-l">Accuracy</div>
          </div>
        </div>

        {stats.perSubject.length > 0 && (
          <div className="ins-subjects anim">
            {stats.perSubject.slice(0, 5).map(s => (
              <div key={s.id} className="ins-subj-row">
                <span className="ins-subj-name">{subjectLabel(s.id)}</span>
                <div className="ins-subj-bar">
                  <div className="ins-subj-fill" style={{ '--w': `${s.pct}%` }} />
                </div>
                <span className="ins-subj-pct">{s.pct}%</span>
              </div>
            ))}
          </div>
        )}

        <div className="anim">
          <ActivityHeatmap weeks={10} />
        </div>

        <button
          className={`ach-toggle${showAch ? ' open' : ''}`}
          onClick={() => setShowAch(o => !o)}
        >
          <Icon name="trophy" size={16} />
          Achievements ({unlockedCount}/{achievements.length})
          <Icon name="chevron-right" size={14} className="ach-toggle-chev" />
        </button>

        {showAch && (
          <div className="ach-grid anim">
            {achievements.map(a => (
              <div key={a.id} className={`ach-tile${a.unlockedAt ? '' : ' locked'}`}>
                <div className="ach-ico">
                  <Icon name={a.unlockedAt ? a.icon : 'lock'} size={20} />
                </div>
                <div className="ach-name">{a.name}{a.geez ? ` · ${a.geez}` : ''}</div>
                <div className="ach-desc">{a.desc}</div>
                {a.unlockedAt && <div className="ach-date">{formatDate(a.unlockedAt)}</div>}
              </div>
            ))}
          </div>
        )}

        <div className="sec-head">Past Sessions</div>
        <div className="filter-row">
          {FILTERS.map(f => (
            <button
              key={f.key}
              className={`btn btn-sm ${filter === f.key ? 'btn-ochre' : 'btn-ghost'}`}
              onClick={() => setFilter(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>

        {loading && (
          <div className="list-loading">Loading…</div>
        )}

        {error && (
          <ErrorState title="Couldn't load history" error={error} onRetry={load} />
        )}

        {!loading && !error && items.length === 0 && (
          <EmptyState
            icon="history"
            title="No History Yet"
            description="Generate MCQs, flashcards, or notes to see them here."
            actionLabel="Generate your first quiz"
            onAction={() => navigate('/mcq')}
          />
        )}

        <div className="hist-list">
          {items.map((item, i) => (
            <div
              key={item.user_generation_id ?? i}
              className="hist-row anim"
              onClick={() => handleOpen(item)}
            >
              <span className="h-ico"><Icon name={typeIcon(item.type)} size={20} /></span>
              <div className="h-info">
                <div className="h-title">{itemTitle(item)}</div>
                <div className="h-meta">{itemMeta(item)}</div>
              </div>
              {scoreTag(item)}
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
