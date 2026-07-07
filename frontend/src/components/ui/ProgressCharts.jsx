import { useEffect, useMemo, useRef, useState } from 'react'
import { getTrends, getMastery, getRetention } from '../../services/analytics.service'
import { subjectLabel } from '../../lib/curriculum'
import Icon from './Icon'

const SOURCES = [
  { key: 'all', label: 'All' },
  { key: 'mcq', label: 'Quizzes' },
  { key: 'exam', label: 'Mock exams' },
  { key: 'review', label: 'Notes review' },
  { key: 'drill', label: 'Drills' },
]
const TREND_DAYS = 30

// Analytics section of the Progress page: accuracy trend (per-source filter),
// practice-vs-mock comparison per unit, and flashcard retention. Self-contained:
// fetches its own data, hides whatever has none.
export default function ProgressCharts() {
  const [trends, setTrends] = useState([])
  const [mastery, setMastery] = useState([])
  const [retention, setRetention] = useState([])

  useEffect(() => {
    getTrends(TREND_DAYS).then(setTrends).catch(() => {})
    getMastery(null, { bySource: true }).then(setMastery).catch(() => {})
    getRetention().then(setRetention).catch(() => {})
  }, [])

  return (
    <>
      {trends.length > 0 && <TrendChart rows={trends} />}
      <PracticeVsMock rows={mastery} />
      <RetentionRow rows={retention} />
    </>
  )
}

// ─── Accuracy trend ──────────────────────────────────────────────────────────

// One line at a time — the source chips switch which flow is plotted, so the
// chart never needs a multi-hue legend. "All" folds in legacy rows (source
// NULL, pre-source mcq/exam mix) so long-time users' history isn't understated.
function TrendChart({ rows }) {
  const [source, setSource] = useState('all')
  const [hover, setHover] = useState(null) // point index
  const wrapRef = useRef(null)

  const points = useMemo(() => {
    const byDate = {}
    for (const r of rows) {
      if (source !== 'all' && r.source !== source) continue
      const d = byDate[r.date] ?? (byDate[r.date] = { total: 0, correct: 0 })
      d.total += r.total
      d.correct += r.correct
    }
    return Object.entries(byDate)
      .map(([date, d]) => ({ date, ...d, accuracy: Math.round((d.correct / d.total) * 100) }))
      .sort((a, b) => (a.date < b.date ? -1 : 1))
  }, [rows, source])

  // Fixed 30-day window ending today; x = day position, so gaps are real gaps.
  const W = 600, H = 190, PL = 34, PR = 16, PT = 14, PB = 24
  const end = new Date(); end.setHours(0, 0, 0, 0)
  const start = new Date(end); start.setDate(start.getDate() - (TREND_DAYS - 1))
  const x = date => {
    const [y, m, d] = date.split('-').map(Number)
    const idx = Math.round((new Date(y, m - 1, d) - start) / 86400000)
    return PL + (Math.min(Math.max(idx, 0), TREND_DAYS - 1) / (TREND_DAYS - 1)) * (W - PL - PR)
  }
  const y = acc => PT + (1 - acc / 100) * (H - PT - PB)

  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.date).toFixed(1)},${y(p.accuracy).toFixed(1)}`).join(' ')
  const area = points.length > 1
    ? `${path} L${x(points[points.length - 1].date).toFixed(1)},${y(0)} L${x(points[0].date).toFixed(1)},${y(0)} Z`
    : ''
  const last = points[points.length - 1]

  function onMove(e) {
    if (!points.length) return
    const svg = e.currentTarget
    const rect = svg.getBoundingClientRect()
    const px = ((e.clientX - rect.left) / rect.width) * W
    let best = 0
    points.forEach((p, i) => { if (Math.abs(x(p.date) - px) < Math.abs(x(points[best].date) - px)) best = i })
    setHover(best)
  }

  const fmt = date => new Date(...date.split('-').map((v, i) => i === 1 ? Number(v) - 1 : Number(v)))
    .toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  const hp = hover != null ? points[hover] : null

  return (
    <div className="an-card anim">
      <div className="an-head">
        <span className="an-title">Accuracy trend</span>
        <span className="an-sub">last {TREND_DAYS} days</span>
      </div>
      <div className="an-chips">
        {SOURCES.map(s => (
          <button key={s.key} className={`btn btn-sm ${source === s.key ? 'btn-ochre' : 'btn-ghost'}`}
                  onClick={() => { setSource(s.key); setHover(null) }}>
            {s.label}
          </button>
        ))}
      </div>

      {points.length === 0 ? (
        <div className="an-empty">No {SOURCES.find(s => s.key === source)?.label.toLowerCase()} attempts in the last {TREND_DAYS} days.</div>
      ) : (
        <div className="an-wrap" ref={wrapRef}>
          <svg viewBox={`0 0 ${W} ${H}`} className="an-svg" onPointerMove={onMove} onPointerLeave={() => setHover(null)}>
            {/* recessive hairline grid at 0 / 50 / 100 */}
            {[0, 50, 100].map(v => (
              <g key={v}>
                <line x1={PL} x2={W - PR} y1={y(v)} y2={y(v)} className="an-grid" />
                <text x={PL - 6} y={y(v) + 3} className="an-tick" textAnchor="end">{v}%</text>
              </g>
            ))}
            <text x={PL} y={H - 6} className="an-tick">{fmt(`${start.getFullYear()}-${start.getMonth() + 1}-${start.getDate()}`)}</text>
            <text x={W - PR} y={H - 6} className="an-tick" textAnchor="end">{fmt(`${end.getFullYear()}-${end.getMonth() + 1}-${end.getDate()}`)}</text>

            {area && <path d={area} className="an-area" />}
            {path && <path d={path} className="an-line" />}
            {hp && <line x1={x(hp.date)} x2={x(hp.date)} y1={PT} y2={H - PB} className="an-cross" />}
            {points.map((p, i) => (
              <circle key={p.date} cx={x(p.date)} cy={y(p.accuracy)} r={i === hover ? 5 : 4} className="an-dot" />
            ))}
            {last && !hp && (
              <text x={Math.min(x(last.date) + 8, W - PR)} y={y(last.accuracy) - 8} className="an-endlabel"
                    textAnchor={x(last.date) > W - 60 ? 'end' : 'start'}>
                {last.accuracy}%
              </text>
            )}
          </svg>
          {hp && (
            <div className="an-tip" style={{ '--tx': `${(x(hp.date) / W) * 100}%` }}>
              <span className="an-tip-v">{hp.accuracy}%</span>
              <span>{fmt(hp.date)} · {hp.correct}/{hp.total} correct</span>
            </div>
          )}
        </div>
      )}

      {/* Values without hovering — screen readers and the tooltip's fallback */}
      <table className="sr-only">
        <caption>Daily accuracy, last {TREND_DAYS} days</caption>
        <thead><tr><th>Date</th><th>Accuracy</th><th>Answered</th></tr></thead>
        <tbody>
          {points.map(p => (
            <tr key={p.date}><td>{p.date}</td><td>{p.accuracy}%</td><td>{p.correct} of {p.total}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── Practice vs mock ────────────────────────────────────────────────────────

// The illusion-of-mastery view: per unit, first-attempt quiz accuracy next to
// mock-exam accuracy. A big gap means the unit feels learned but doesn't hold
// up under exam conditions.
function PracticeVsMock({ rows }) {
  const units = useMemo(() => {
    const map = {}
    for (const r of rows) {
      if (r.source !== 'mcq' && r.source !== 'exam') continue
      const key = `${r.subject}|${r.grade ?? ''}|${r.unit ?? ''}`
      const u = map[key] ?? (map[key] = { subject: r.subject, grade: r.grade, unit: r.unit })
      u[r.source] = r
    }
    return Object.values(map)
      .filter(u => u.mcq && u.exam && u.mcq.total >= 3 && u.exam.total >= 3)
      .sort((a, b) => (b.mcq.total + b.exam.total) - (a.mcq.total + a.exam.total))
      .slice(0, 6)
  }, [rows])

  if (units.length === 0) return null

  return (
    <div className="an-card anim">
      <div className="an-head">
        <span className="an-title">Practice vs mock exams</span>
        <span className="an-sub">first attempts only</span>
      </div>
      <div className="an-legend">
        <span><i className="an-swatch an-c1" /> Practice quizzes</span>
        <span><i className="an-swatch an-c2" /> Mock exams</span>
      </div>
      {units.map(u => {
        const name = [subjectLabel(u.subject), u.grade ? `G${u.grade}` : '', u.unit ? `Unit ${u.unit}` : '']
          .filter(Boolean).join(' · ')
        const gap = u.mcq.accuracy - u.exam.accuracy
        return (
          <div key={name} className="an-pv-row">
            <div className="an-pv-name">
              {name}
              {gap >= 10 && (
                <span className="an-gap" title="Practice accuracy is well above mock-exam accuracy — this unit may feel more learned than it is.">
                  {gap} pt gap
                </span>
              )}
            </div>
            {[['mcq', 'an-c1'], ['exam', 'an-c2']].map(([src, cls]) => (
              <div key={src} className="an-pv-line" title={`${src === 'mcq' ? 'Practice' : 'Mock'}: ${u[src].correct}/${u[src].total} correct`}>
                <div className="an-bar"><div className={`an-fill ${cls}`} style={{ '--w': `${u[src].accuracy}%` }} /></div>
                <span className="an-pv-pct">{u[src].accuracy}%</span>
              </div>
            ))}
          </div>
        )
      })}
    </div>
  )
}

// ─── Flashcard retention ─────────────────────────────────────────────────────

// Complements accuracy: a card in Leitner box 3+ has survived ≥3 spaced
// reviews, so this measures what actually stuck, not just today's performance.
function RetentionRow({ rows }) {
  const list = rows.filter(r => r.total > 0).sort((a, b) => b.total - a.total).slice(0, 5)
  if (list.length === 0) return null

  return (
    <div className="an-card anim">
      <div className="an-head">
        <span className="an-title"><Icon name="cards" size={15} /> Flashcard retention</span>
        <span className="an-sub">cards retained long-term</span>
      </div>
      {list.map(r => (
        <div key={r.subject} className="ins-subj-row an-ret-row">
          <span className="ins-subj-name">{subjectLabel(r.subject)}</span>
          <div className="ins-subj-bar"><div className="ins-subj-fill an-ret-fill" style={{ '--w': `${Math.round((r.strong / r.total) * 100)}%` }} /></div>
          <span className="ins-subj-pct">{r.strong}/{r.total}</span>
        </div>
      ))}
    </div>
  )
}
