import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import SubjectChips from '../components/ui/SubjectChips'
import { GRADES, getDaysUntilEUEE } from '../lib/curriculum'

export default function Home() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState('euee')
  const [grade, setGrade] = useState(10)

  const days = getDaysUntilEUEE()
  const isEUEE = mode === 'euee'
  const firstName = user?.name?.split(' ')[0] ?? 'Student'

  return (
    <div className="pg-body">
      <div className="hero anim">
        <div className="hero-hi">ሰላም፣</div>
        <div className="hero-name">Welcome back, {firstName}</div>
        <div className="hero-sub">
          {isEUEE
            ? 'Every question brings you closer to passing EUEE.'
            : `Grade ${grade} study companion — build strong foundations.`}
        </div>
        {isEUEE && (
          <div className="euee-block">
            <span className="euee-num pulse">{days}</span>
            <span className="euee-txt">days until<br />EUEE 2027</span>
          </div>
        )}
        <div className="stats-row">
          <div className="stat-box">
            <div className="stat-v">—</div>
            <div className="stat-l">Questions</div>
          </div>
          <div className="stat-box">
            <div className="stat-v">—</div>
            <div className="stat-l">Accuracy</div>
          </div>
          <div className="stat-box">
            <div className="stat-v">—</div>
            <div className="stat-l">Sessions</div>
          </div>
        </div>
      </div>

      <div className="mode-bar anim">
        <button
          className={`mode-btn${isEUEE ? ' on' : ''}`}
          onClick={() => setMode('euee')}
        >
          🎯 EUEE Prep
          <span className="m-sub">Grade 12</span>
        </button>
        <button
          className={`mode-btn${!isEUEE ? ' on' : ''}`}
          onClick={() => setMode('school')}
        >
          📚 School Help
          <span className="m-sub">Grade {grade}</span>
        </button>
      </div>

      {!isEUEE && (
        <div style={{ marginBottom: 18, display: 'flex', gap: 6 }}>
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
          <div className="act-i" style={{ background: 'var(--ochre-glow)' }}>📝</div>
          <h3>{isEUEE ? 'Practice Exam' : 'Quick Quiz'}</h3>
          <p>{isEUEE ? 'EUEE-style MCQs with solutions' : 'Test any unit'}</p>
        </div>
        <div className="act-card" onClick={() => navigate('/flashcards')}>
          <div className="act-i" style={{ background: 'var(--highland-l)' }}>🃏</div>
          <h3>Flashcards</h3>
          <p>Rapid review of key concepts</p>
        </div>
        <div className="act-card" onClick={() => navigate('/notes')}>
          <div className="act-i" style={{ background: 'var(--indigo-l)' }}>📓</div>
          <h3>Study Notes</h3>
          <p>Full notes with worked examples</p>
        </div>
        <div className="act-card" onClick={() => navigate('/chat')}>
          <div className="act-i" style={{ background: 'var(--vermillion-l)' }}>💬</div>
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
