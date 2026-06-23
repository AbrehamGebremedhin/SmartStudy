import { useState, useEffect } from 'react'
import { api } from '../services/apiClient'
import Icon from '../components/ui/Icon'
import EmptyState from '../components/ui/EmptyState'
import Confetti from '../components/ui/Confetti'
import DifficultyTag from '../components/ui/DifficultyTag'
import { awardXP, resultMessage } from '../lib/gamification'

// ponytail: no history/genStorage persistence in v1 — exam practice isn't a "generation".
// Add it later if these need to show up under Progress.

export default function PastExams() {
  const [subjects, setSubjects] = useState([])
  const [years, setYears] = useState([])
  const [config, setConfig] = useState({ subject: '', year: '', numItems: 10 })
  const [questions, setQuestions] = useState([])
  const [selected, setSelected] = useState({})
  const [revealed, setRevealed] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [xpEarned, setXpEarned] = useState(0)
  const [hovered, setHovered] = useState(null) // { qi, letter }

  // Load available subjects once.
  useEffect(() => {
    api.get('/exam/subjects')
      .then(d => {
        setSubjects(d.subjects)
        if (d.subjects[0]) setConfig(c => ({ ...c, subject: d.subjects[0].subject }))
      })
      .catch(e => setError(e.message))
  }, [])

  // Load years when subject changes.
  useEffect(() => {
    if (!config.subject) return
    setYears([])
    api.get(`/exam/${config.subject}/years`).then(d => setYears(d.years)).catch(() => setYears([]))
  }, [config.subject])

  function reset() {
    setQuestions([]); setSelected({}); setRevealed({}); setXpEarned(0); setError(null)
  }

  async function load() {
    reset()
    setLoading(true)
    try {
      const params = new URLSearchParams({ subject: config.subject, limit: String(config.numItems) })
      if (config.year) params.set('year', config.year)
      const d = await api.get(`/exam/practice?${params}`)
      if (!d.questions.length) setError('No questions found for this selection.')
      setQuestions(d.questions)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function pick(qi, letter) {
    if (revealed[qi]) return
    const ns = { ...selected, [qi]: letter }
    const nr = { ...revealed, [qi]: true }
    setSelected(ns); setRevealed(nr)

    const correct = letter === questions[qi].correct_answer
    let gained = awardXP(correct ? 'mcq_correct' : 'mcq_incorrect', { subject: config.subject }).gained
    const allDone = Object.keys(nr).length === questions.length
    if (allDone) {
      const n = questions.filter((q, i) => ns[i] === q.correct_answer).length
      gained += awardXP('quiz_complete', { correct: n, total: questions.length, subject: config.subject }).gained
    }
    if (gained > 0) setXpEarned(x => x + gained)
  }

  const allAnswered = questions.length > 0 && Object.keys(revealed).length === questions.length
  const score = allAnswered
    ? { correct: questions.filter((q, i) => selected[i] === q.correct_answer).length, total: questions.length }
    : null

  return (
    <>
      <div className="pg-top">
        <h2>Past Exams</h2>
        <p>Real EUEE questions with worked explanations</p>
      </div>
      <div className="pg-body">
        {questions.length === 0 && (
          <div className="cfg">
            <div className="cfg-grid">
              <div className="cfg-f">
                <label className="cfg-lbl">Subject</label>
                <select value={config.subject}
                        onChange={e => setConfig(c => ({ ...c, subject: e.target.value, year: '' }))}>
                  {subjects.map(s => (
                    <option key={s.subject} value={s.subject}>
                      {s.subject[0].toUpperCase() + s.subject.slice(1)} ({s.count})
                    </option>
                  ))}
                </select>
              </div>
              <div className="cfg-f">
                <label className="cfg-lbl">Year (E.C)</label>
                <select value={config.year} onChange={e => setConfig(c => ({ ...c, year: e.target.value }))}>
                  <option value="">All years</option>
                  {years.map(y => <option key={y} value={y}>{y}</option>)}
                </select>
              </div>
              <div className="cfg-f">
                <label className="cfg-lbl">Questions</label>
                <select value={config.numItems}
                        onChange={e => setConfig(c => ({ ...c, numItems: Number(e.target.value) }))}>
                  {[5, 10, 20, 30].map(n => <option key={n} value={n}>{n}</option>)}
                </select>
              </div>
            </div>
            <button className="btn btn-ochre btn-block" onClick={load} disabled={loading || !config.subject}>
              {loading ? <span className="spinner" /> : 'Start Practice'}
            </button>
          </div>
        )}

        {error && <div className="form-error">{error}</div>}

        {questions.length > 0 && (
          <div className="back-row">
            <button className="btn btn-ghost btn-sm" onClick={reset}>← New Set</button>
          </div>
        )}

        {!loading && questions.length === 0 && !error && (
          <EmptyState icon="quiz" title="Practice Past Papers"
                      description="Pick a subject and year, then start practicing real exam questions." />
        )}

        {score && (
          <ExamResults score={score} xpEarned={xpEarned} onNew={reset} />
        )}

        {questions.map((q, qi) => {
          const isRevealed = revealed[qi]
          const userAnswer = selected[qi]
          const correct = q.correct_answer
          return (
            <div key={q.id} className="mcq-card anim">
              <div className="mcq-top">
                <span className="mcq-topic">{q.topic ?? `Question ${qi + 1}`}</span>
                <DifficultyTag difficulty={q.difficulty ?? 'medium'} />
              </div>
              <div className="mcq-body">
                {q.passage && <div className="mcq-passage">{q.passage}</div>}
                <div className="mcq-q">{qi + 1}. {q.question}</div>
                {q.question_image_url && (
                  <img className="mcq-img" src={q.question_image_url} alt="question diagram" loading="lazy" />
                )}
                <div className="mcq-opts">
                  {q.options.map(opt => {
                    const isCorrect = opt.letter === correct
                    const isSelected = opt.letter === userAnswer
                    const tooltipText = isRevealed && !isCorrect
                      ? q.incorrect_explanations?.[opt.letter]
                      : null
                    const showTooltip = tooltipText &&
                      hovered?.qi === qi && hovered?.letter === opt.letter
                    let cls = 'mcq-opt'
                    if (isRevealed && isCorrect) cls += ' ok'
                    else if (isRevealed && isSelected && !isCorrect) cls += ' no'
                    return (
                      <div key={opt.letter} className="opt-wrap">
                        <button className={cls} onClick={() => pick(qi, opt.letter)}
                                onMouseEnter={() => tooltipText && setHovered({ qi, letter: opt.letter })}
                                onMouseLeave={() => setHovered(null)}>
                          <span className="o-let">{opt.letter}</span>
                          {opt.image_url
                            ? <img className="opt-img" src={opt.image_url} alt={`option ${opt.letter}`} loading="lazy" />
                            : <span>{opt.text}</span>}
                        </button>
                        {showTooltip && <div className="opt-tooltip">✗ {tooltipText}</div>}
                      </div>
                    )
                  })}
                </div>

                {isRevealed && (
                  <div className="mcq-expl">
                    <strong>{userAnswer === correct ? '✓ Correct!' : `✗ The answer is ${correct}`}</strong>
                    {(q.correct_explanations ?? []).map((e, i) => (
                      <div key={i} style={{ marginTop: 3 }}>• {e}</div>
                    ))}
                    {userAnswer !== correct && q.incorrect_explanations?.[userAnswer] && (
                      <div style={{ marginTop: 8, color: 'var(--vermillion)' }}>
                        Why your choice is wrong: {q.incorrect_explanations[userAnswer]}
                      </div>
                    )}
                    {q.workout_steps && (
                      <div style={{ marginTop: 8, whiteSpace: 'pre-line' }}>
                        <strong>Working:</strong> {q.workout_steps}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </>
  )
}

function ExamResults({ score, xpEarned, onNew }) {
  const pct = Math.round((score.correct / score.total) * 100)
  const band = pct >= 80 ? 'band-high' : pct >= 50 ? 'band-mid' : 'band-low'
  const label = pct >= 80 ? 'Excellent' : pct >= 50 ? 'Keep Practicing' : 'Needs Work'
  return (
    <div className="mcq-results anim res-wrap">
      <div className="results-header">
        {pct >= 80 && <Confetti />}
        <div className="results-title">Set Complete</div>
        <div className="results-score">
          <span className="score-num">{score.correct}</span>
          <span className="score-sep">/{score.total}</span>
          <span className="score-pct">{pct}%</span>
        </div>
        <div className={`score-band ${band}`}>{label}</div>
        <div className="res-msg">{resultMessage(pct, String(score.total))}</div>
        {xpEarned > 0 && <div className="res-xp"><Icon name="star" size={14} /> +{xpEarned} XP earned</div>}
      </div>
      <div className="res-actions">
        <button className="btn btn-ochre" onClick={onNew}>New Set</button>
      </div>
    </div>
  )
}
