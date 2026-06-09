import { useState, useEffect } from 'react'
import CacheTag from '../components/ui/CacheTag'
import { getHistory, getHistoryByType } from '../services/history.service'
import { typeIcon, subjectLabel } from '../lib/curriculum'

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

  useEffect(() => {
    setLoading(true)
    setError(null)
    const fetch = filter === 'all' ? getHistory() : getHistoryByType(filter)
    fetch
      .then(setItems)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [filter])

  function formatDate(iso) {
    if (!iso) return ''
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  function itemTitle(item) {
    const params = item.request_params ?? {}
    const subject = subjectLabel(params.subject ?? '')
    const grade = params.grade ? `Grade ${params.grade}` : ''
    const unit = params.unit ? `Unit ${params.unit}` : ''
    const count = params.num_questions
      ? `${params.num_questions} questions`
      : params.num_cards
      ? `${params.num_cards} cards`
      : ''
    return [subject, grade, unit].filter(Boolean).join(' — ') || item.type
  }

  function itemMeta(item) {
    const params = item.request_params ?? {}
    const parts = []
    if (params.num_questions) parts.push(`${params.num_questions} questions`)
    if (params.num_cards) parts.push(`${params.num_cards} cards`)
    if (params.difficulty) parts.push(params.difficulty.charAt(0).toUpperCase() + params.difficulty.slice(1))
    if (item.accessed_at) parts.push(formatDate(item.accessed_at))
    return parts.join(' · ')
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
          <div style={{ textAlign: 'center', padding: 40, color: 'var(--ink-3)' }}>
            Loading…
          </div>
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
            <div key={item.user_generation_id ?? i} className="hist-row anim">
              <span className="h-ico">{typeIcon(item.type)}</span>
              <div className="h-info">
                <div className="h-title">{itemTitle(item)}</div>
                <div className="h-meta">{itemMeta(item)}</div>
              </div>
              <CacheTag hit={item.was_cache_hit} />
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
