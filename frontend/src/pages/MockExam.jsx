import { useState, useEffect, useMemo, useRef } from 'react'
import { api } from '../services/apiClient'
import Icon from '../components/ui/Icon'
import EmptyState from '../components/ui/EmptyState'
import Confetti from '../components/ui/Confetti'
import { awardXP, resultMessage } from '../lib/gamification'

// ponytail: no history/genStorage persistence in v1 — a mock exam is a one-off sitting.
// Timer is in-memory; a refresh restarts the exam. Add persistence only if asked.

function fmtTime(s) {
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

export default function MockExam() {
  const [subjects, setSubjects] = useState([])
  const [config, setConfig] = useState({ subject: '' })
  const [questions, setQuestions] = useState([])
  const [selected, setSelected] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [started, setStarted] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [timeLeft, setTimeLeft] = useState(0)
  const [xpEarned, setXpEarned] = useState(0)
  const submitRef = useRef(null)

  const spec = subjects.find(s => s.subject === config.subject)

  // Load available subjects (with per-subject exam spec) once.
  useEffect(() => {
    api.get('/exam/subjects')
      .then(d => {
        setSubjects(d.subjects)
        if (d.subjects[0]) setConfig(c => ({ ...c, subject: d.subjects[0].subject }))
      })
      .catch(e => setError(e.message))
  }, [])

  function reset() {
    setQuestions([]); setSelected({}); setStarted(false); setSubmitted(false)
    setTimeLeft(0); setXpEarned(0); setError(null)
  }

  async function start() {
    reset()
    setLoading(true)
    try {
      const d = await api.get(`/exam/practice?subject=${encodeURIComponent(config.subject)}`)
      if (!d.questions.length) { setError('No questions available for this subject.'); return }
      setQuestions(d.questions)
      setTimeLeft(d.minutes * 60)
      setStarted(true)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function pick(qi, letter) {
    if (submitted) return
    setSelected(s => ({ ...s, [qi]: letter }))
  }

  function submitExam() {
    if (submitted) return
    setSubmitted(true)
    const correct = questions.filter((q, i) => selected[i] === q.correct_answer).length
    let gained = 0
    questions.forEach((q, i) => {
      gained += awardXP(selected[i] === q.correct_answer ? 'mcq_correct' : 'mcq_incorrect',
        { subject: config.subject }).gained
    })
    gained += awardXP('quiz_complete', { correct, total: questions.length, subject: config.subject }).gained
    setXpEarned(gained)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  submitRef.current = submitExam

  // Countdown — auto-submit at 0.
  useEffect(() => {
    if (!started || submitted) return
    if (timeLeft <= 0) { submitRef.current?.(); return }
    const id = setTimeout(() => setTimeLeft(t => t - 1), 1000)
    return () => clearTimeout(id)
  }, [started, submitted, timeLeft])

  const answeredCount = Object.keys(selected).length
  const score = submitted
    ? { correct: questions.filter((q, i) => selected[i] === q.correct_answer).length, total: questions.length }
    : null

  // Weak areas: topics with the most wrong answers, with their grade/unit (study suggestions).
  const weakAreas = useMemo(() => {
    if (!submitted) return []
    const m = {}
    questions.forEach((q, i) => {
      if (selected[i] !== q.correct_answer) {
        const t = q.topic || 'General'
        if (!m[t]) m[t] = { count: 0, grade: q.grade, unit: q.unit }
        m[t].count += 1
      }
    })
    return Object.entries(m).sort((a, b) => b[1].count - a[1].count).slice(0, 8)
  }, [submitted]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="pg-top">
        <h2>Mock Exam</h2>
        <p>Sit a full EUEE-style paper under real time pressure</p>
      </div>
      <div className="pg-body">
        {/* Config */}
        {!started && (
          <div className="cfg">
            <div className="cfg-grid">
              <div className="cfg-f">
                <label className="cfg-lbl">Subject</label>
                <select value={config.subject}
                        onChange={e => setConfig({ subject: e.target.value })}>
                  {subjects.map(s => (
                    <option key={s.subject} value={s.subject}>
                      {s.subject[0].toUpperCase() + s.subject.slice(1)}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            {spec && (
              <div className="exam-spec">
                <span><Icon name="quiz" size={15} /> {spec.num_questions} questions</span>
                <span><Icon name="clock" size={15} /> {spec.minutes} minutes</span>
              </div>
            )}
            <button className="btn btn-ochre btn-block" onClick={start} disabled={loading || !config.subject}>
              {loading ? <span className="spinner" /> : 'Start Exam'}
            </button>
          </div>
        )}

        {error && <div className="form-error">{error}</div>}

        {!started && !error && (
          <EmptyState icon="quiz" title="Ready for a Real Exam?"
                      description="Pick a subject and sit a timed paper sized like the actual EUEE. Answers are revealed only at the end." />
        )}

        {/* Sticky exam header: timer + progress (during exam, before submit) */}
        {started && !submitted && (
          <div className="exam-bar">
            <div className={`exam-timer ${timeLeft <= 300 ? 'low' : ''}`}>
              <Icon name="clock" size={16} /> {fmtTime(timeLeft)}
            </div>
            <div className="exam-prog">{answeredCount}/{questions.length} answered</div>
            <button className="btn btn-ochre btn-sm" onClick={submitExam}>Submit</button>
          </div>
        )}

        {/* Results + weak areas (after submit) */}
        {score && (
          <ExamResults score={score} xpEarned={xpEarned} weakAreas={weakAreas} onNew={reset} />
        )}

        {/* Questions */}
        {questions.map((q, qi) => {
          const userAnswer = selected[qi]
          const correct = q.correct_answer
          return (
            <div key={q.id} className="mcq-card anim">
              <div className="mcq-top">
                <span className="mcq-topic">{submitted ? (q.topic ?? `Question ${qi + 1}`) : `Question ${qi + 1}`}</span>
                {submitted && (
                  <span className={`q-mark ${userAnswer === correct ? 'ok' : 'no'}`}>
                    {userAnswer === correct ? '✓' : '✗'}
                  </span>
                )}
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
                    let cls = 'mcq-opt'
                    if (submitted && isCorrect) cls += ' ok'
                    else if (submitted && isSelected && !isCorrect) cls += ' no'
                    else if (!submitted && isSelected) cls += ' sel'
                    return (
                      <button key={opt.letter} className={cls} onClick={() => pick(qi, opt.letter)}>
                        <span className="o-let">{opt.letter}</span>
                        {opt.image_url
                          ? <img className="opt-img" src={opt.image_url} alt={`option ${opt.letter}`} loading="lazy" />
                          : <span>{opt.text}</span>}
                      </button>
                    )
                  })}
                </div>

                {submitted && (
                  <div className="mcq-expl">
                    <strong>{userAnswer === correct ? '✓ Correct!' : userAnswer ? `✗ The answer is ${correct}` : `Unanswered — the answer is ${correct}`}</strong>
                    {(q.correct_explanations ?? []).map((e, i) => (
                      <div key={i} style={{ marginTop: 3 }}>• {e}</div>
                    ))}
                    {userAnswer && userAnswer !== correct && q.incorrect_explanations?.[userAnswer] && (
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

        {started && !submitted && questions.length > 0 && (
          <button className="btn btn-ochre btn-block" onClick={submitExam} style={{ marginTop: 16 }}>
            Submit Exam ({answeredCount}/{questions.length} answered)
          </button>
        )}
      </div>
    </>
  )
}

function ExamResults({ score, xpEarned, weakAreas, onNew }) {
  const pct = Math.round((score.correct / score.total) * 100)
  const band = pct >= 80 ? 'band-high' : pct >= 50 ? 'band-mid' : 'band-low'
  const label = pct >= 80 ? 'Excellent' : pct >= 50 ? 'Keep Practicing' : 'Needs Work'
  return (
    <div className="mcq-results anim res-wrap">
      <div className="results-header">
        {pct >= 80 && <Confetti />}
        <div className="results-title">Exam Complete</div>
        <div className="results-score">
          <span className="score-num">{score.correct}</span>
          <span className="score-sep">/{score.total}</span>
          <span className="score-pct">{pct}%</span>
        </div>
        <div className={`score-band ${band}`}>{label}</div>
        <div className="res-msg">{resultMessage(pct, String(score.total))}</div>
        {xpEarned > 0 && <div className="res-xp"><Icon name="star" size={14} /> +{xpEarned} XP earned</div>}
      </div>

      {weakAreas.length > 0 && (
        <div className="weak-areas">
          <div className="weak-title"><Icon name="target" size={15} /> Areas to study</div>
          <p className="weak-sub">Topics where you missed the most — focus here to improve.</p>
          <ul className="weak-list">
            {weakAreas.map(([topic, info]) => {
              const loc = info.grade
                ? `Grade ${info.grade}${info.unit ? ` · Unit ${info.unit}` : ''}`
                : null
              return (
                <li key={topic}>
                  <span>{topic}{loc && <span className="weak-loc"> — {loc}</span>}</span>
                  <span className="weak-count">{info.count} missed</span>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      <div className="res-actions">
        <button className="btn btn-ochre" onClick={onNew}>New Exam</button>
      </div>
    </div>
  )
}
