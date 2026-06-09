import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getHistory, getHistoryByType } from '../services/history.service'
import { typeIcon, subjectLabel } from '../lib/curriculum'
import { loadGeneration, routeForType } from '../lib/genStorage'

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
  const navigate = useNavigate()

  useEffect(() => {
    setLoading(true)
    setError(null)
    const req = filter === 'all' ? getHistory() : getHistoryByType(filter)
    req
      .then(setItems)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [filter])

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
    if (item.type !== 'mcq') return null
    const saved = loadGeneration(item.generation_id)
    if (!saved?.score) return null
    const { correct, total } = saved.score
    const pct = Math.round((correct / total) * 100)
    const color = pct >= 80 ? 'var(--highland)' : pct >= 50 ? 'var(--ochre-deep)' : 'var(--vermillion)'
    const bg = pct >= 80 ? 'var(--highland-l)' : pct >= 50 ? 'var(--ochre-glow)' : 'var(--vermillion-l)'
    return (
      <span style={{
        fontSize: 12,
        fontWeight: 800,
        padding: '3px 10px',
        borderRadius: 20,
        background: bg,
        color,
        flexShrink: 0,
        fontFamily: 'var(--f-mono)',
      }}>
        {correct}/{total}
      </span>
    )
  }

  function handleOpen(item) {
    const route = routeForType(item.type)
    navigate(`${route}?gen=${item.generation_id}`)
  }

  return (
    <>
      <div className="pg-top">
        <h2>History</h2>
        <p>Past generated content</p>
      </div>
      <div className="pg-body">
        <div style={{ display: 'flex', gap: 6, marginBottom: 18, flexWrap: 'wrap' }}>
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
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--ink-3)' }}>Loading…</div>
        )}

        {error && (
          <div style={{ color: 'var(--vermillion)', fontSize: 14 }}>{error}</div>
        )}

        {!loading && !error && items.length === 0 && (
          <div className="empty">
            <div className="empty-i">↻</div>
            <h3>No History Yet</h3>
            <p>Generate MCQs, flashcards, or notes to see them here.</p>
          </div>
        )}

        <div className="hist-list">
          {items.map((item, i) => (
            <div
              key={item.user_generation_id ?? i}
              className="hist-row anim"
              onClick={() => handleOpen(item)}
            >
              <span className="h-ico">{typeIcon(item.type)}</span>
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
