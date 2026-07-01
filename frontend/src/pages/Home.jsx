import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import SubjectChips from '../components/ui/SubjectChips'
import Icon from '../components/ui/Icon'
import Stele from '../components/ui/Stele'
import CountUp from '../components/ui/CountUp'
import { GRADES, getDaysUntilEUEE, subjectLabel, typeIcon } from '../lib/curriculum'
import { getLevelInfo, getStreak, getStats, getLastActivity } from '../lib/gamification'
import { getHistory } from '../services/history.service'
import { getMastery } from '../services/analytics.service'
import { getMistakeCount } from '../services/mistakes.service'
import { api } from '../services/apiClient'
import { loadGeneration, routeForType } from '../lib/genStorage'

function relTime(iso) {
  if (!iso) return ''
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default function Home() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState('euee')
  const [grade, setGrade] = useState(10)
  const [sessions, setSessions] = useState(null)

  // localStorage reads are idempotent — safe as lazy initializers under StrictMode
  const [level] = useState(() => getLevelInfo())
  const [streak] = useState(() => getStreak())
  const [stats] = useState(() => getStats())
  const [lastGen] = useState(() => getLastActivity())

  useEffect(() => {
    getHistory(100)
      .then(items => setSessions(items.length))
      .catch(() => {})
  }, [])

  const days = getDaysUntilEUEE()
  const isEUEE = mode === 'euee'
  const firstName = user?.name?.split(' ')[0] ?? 'Student'

  return (
    <div className="pg-body">
      <div className="hero anim">
        <Stele mono height={260} className="hero-stele" />
        <div className="hero-hi">ሰላም፣</div>
        <div className="hero-name">Welcome back, {firstName}</div>
        <div className="hero-sub">
          {isEUEE
            ? 'Every question brings you closer to passing EUEE.'
            : `Grade ${grade} study companion — build strong foundations.`}
        </div>

        <div className="g-row">
          <div className="g-level">
            <span className="g-level-geez">{level.geez}</span>
            <span className="g-level-name">{level.name} · {level.translation}</span>
          </div>
          <div className="g-xp">
            <div className="g-xpbar">
              <div className="g-xpbar-fill" style={{ '--w': `${level.pct}%` }} />
            </div>
            <div className="g-xpnum">
              {level.isMax ? `${level.xp} XP · highest rank` : `${level.xp} / ${level.next.threshold} XP to ${level.next.name}`}
            </div>
          </div>
          <div
            className={`g-streak${streak.activeToday ? '' : ' cold'}`}
            title={streak.activeToday ? `Best streak: ${streak.best} days` : 'Study today to keep your streak alive'}
          >
            <Icon name="flame" size={16} className={streak.activeToday ? 'g-flame' : undefined} />
            <span>{streak.current}</span>
            <span className="g-streak-l">day{streak.current === 1 ? '' : 's'}</span>
          </div>
        </div>

        {isEUEE && (
          <div className="euee-block">
            <span className="euee-num pulse"><CountUp value={days} duration={1100} /></span>
            <span className="euee-txt">days until<br />EUEE 2027</span>
          </div>
        )}
        <div className="stats-row">
          <div className="stat-box">
            <div className="stat-v"><CountUp value={stats.questionsAnswered > 0 ? stats.questionsAnswered : NaN} /></div>
            <div className="stat-l">Questions</div>
          </div>
          <div className="stat-box">
            <div className="stat-v"><CountUp value={stats.accuracyPct != null ? stats.accuracyPct : NaN} suffix="%" /></div>
            <div className="stat-l">Accuracy</div>
          </div>
          <div className="stat-box">
            <div className="stat-v"><CountUp value={sessions == null ? NaN : sessions} /></div>
            <div className="stat-l">Sessions</div>
          </div>
        </div>
      </div>

      <TodayCard navigate={navigate} />

      <ContinueCard lastGen={lastGen} navigate={navigate} />

      <div className="mode-bar anim">
        <button
          className={`mode-btn${isEUEE ? ' on' : ''}`}
          onClick={() => setMode('euee')}
        >
          <span className="m-top"><Icon name="target" size={15} /> EUEE Prep</span>
          <span className="m-sub">Grade 12</span>
        </button>
        <button
          className={`mode-btn${!isEUEE ? ' on' : ''}`}
          onClick={() => setMode('school')}
        >
          <span className="m-top"><Icon name="school" size={15} /> School Help</span>
          <span className="m-sub">Grade {grade}</span>
        </button>
      </div>

      {!isEUEE && (
        <div className="grade-row">
          {GRADES.map(g => (
            <button
              key={g}
              className={`btn btn-sm ${grade === g ? 'btn-ochre' : 'btn-ghost'}`}
              onClick={() => setGrade(g)}
            >
              Grade {g}
            </button>
          ))}
        </div>
      )}

      <div className="act-grid anim">
        <div className="act-card" onClick={() => navigate('/mcq')}>
          <div className="act-i act-i-ochre"><Icon name="quiz" /></div>
          <h3>{isEUEE ? 'Practice Exam' : 'Quick Quiz'}</h3>
          <p>{isEUEE ? 'EUEE-style MCQs with solutions' : 'Test any unit'}</p>
        </div>
        <div className="act-card" onClick={() => navigate('/flashcards')}>
          <div className="act-i act-i-highland"><Icon name="cards" /></div>
          <h3>Flashcards</h3>
          <p>Rapid review of key concepts</p>
        </div>
        <div className="act-card" onClick={() => navigate('/notes')}>
          <div className="act-i act-i-indigo"><Icon name="notes" /></div>
          <h3>Study Notes</h3>
          <p>Full notes with worked examples</p>
        </div>
        <div className="act-card" onClick={() => navigate('/chat')}>
          <div className="act-i act-i-vermillion"><Icon name="tutor" /></div>
          <h3>Ask Tutor</h3>
          <p>AI help with difficult topics</p>
        </div>
      </div>

      <div className="sec-head">Subjects</div>
      <SubjectChips
        exclude={['general_business']}
        onSelect={() => navigate('/mcq')}
      />
    </div>
  )
}

// Daily focus: the concrete things waiting for the student right now. Turns the
// passive streak/XP into a return hook. Each row is fully actionable; the card
// hides itself when nothing is pending.
function TodayCard({ navigate }) {
  const [due, setDue] = useState(0)
  const [mistakes, setMistakes] = useState(0)
  const [weakest, setWeakest] = useState(null)

  useEffect(() => {
    api.get('/flashcards/due?limit=100').then(d => setDue(d.length)).catch(() => {})
    getMistakeCount().then(r => setMistakes(r.count)).catch(() => {})
    getMastery().then(rows => {
      const w = rows.find(r => r.total >= 3 && r.accuracy < 100)
      if (w) setWeakest(w)
    }).catch(() => {})
  }, [])

  const items = []
  if (due > 0) items.push({
    icon: 'cards', label: `${due} flashcard${due === 1 ? '' : 's'} due for review`,
    badge: due, onClick: () => navigate('/flashcards'),
  })
  if (mistakes > 0) items.push({
    icon: 'target', label: `${mistakes} mistake${mistakes === 1 ? '' : 's'} to drill`,
    badge: mistakes, onClick: () => navigate('/review'),
  })
  if (weakest) {
    const loc = [subjectLabel(weakest.subject), weakest.unit ? `Unit ${weakest.unit}` : ''].filter(Boolean).join(' · ')
    items.push({
      icon: 'quiz', label: `Weakest: ${loc} (${weakest.accuracy}%)`, badge: null,
      onClick: () => navigate(`/mcq?subject=${weakest.subject}${weakest.grade ? `&grade=${weakest.grade}` : ''}${weakest.unit ? `&unit=${encodeURIComponent(weakest.unit)}` : ''}`),
    })
  }
  if (items.length === 0) return null

  return (
    <div className="weak-areas anim">
      <div className="weak-title"><Icon name="flame" size={15} /> Today's focus</div>
      <ul className="weak-list">
        {items.map((it, i) => (
          <li key={i} className="weak-row" role="button" tabIndex={0}
              onClick={it.onClick}
              onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), it.onClick())}>
            <span><Icon name={it.icon} size={14} /> {it.label}</span>
            {it.badge != null && <span className="weak-count">{it.badge}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

function ContinueCard({ lastGen, navigate }) {
  if (!lastGen?.genId) return null
  const saved = loadGeneration(lastGen.genId)
  if (!saved) return null

  const typeLabel = lastGen.type === 'mcq' ? 'Quiz' : lastGen.type === 'flashcard' ? 'Flashcards' : 'Notes'
  const title = lastGen.topic ||
    [subjectLabel(lastGen.subject), lastGen.grade ? `Grade ${lastGen.grade}` : null, lastGen.unit ? `Unit ${lastGen.unit}` : null]
      .filter(Boolean)
      .join(' · ')

  let progress = null
  if (lastGen.type === 'mcq' && saved.questions?.length) {
    const answered = Object.keys(saved.revealed ?? {}).length
    progress = saved.completedAt ? 'Completed · review or retry' : `${answered}/${saved.questions.length} answered`
  } else if (lastGen.type === 'flashcard' && saved.cards?.length) {
    const rated = Object.keys(saved.ratings ?? {}).length
    progress = saved.completedAt ? 'Deck completed' : `${rated}/${saved.cards.length} cards rated`
  }

  return (
    <button
      className="cont-card anim"
      onClick={() => navigate(`${routeForType(lastGen.type)}?gen=${lastGen.genId}`)}
    >
      <div className="cont-ico"><Icon name={typeIcon(lastGen.type)} /></div>
      <div className="cont-info">
        <div className="cont-kicker">Continue studying</div>
        <div className="cont-title">{title}</div>
        <div className="cont-meta">
          {typeLabel}{progress ? ` · ${progress}` : ''} · {relTime(lastGen.at)}
        </div>
      </div>
      <Icon name="arrow-right" size={18} className="cont-arrow" />
    </button>
  )
}
