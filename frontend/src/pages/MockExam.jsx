import { useState, useEffect, useMemo, useRef } from 'react'
import { api } from '../services/apiClient'
import Icon from '../components/ui/Icon'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import Confetti from '../components/ui/Confetti'
import { awardXP, resultMessage } from '../lib/gamification'
import { recordMistake } from '../services/mistakes.service'

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
  const [filter, setFilter] = useState('all') // post-submit review filter: all | incorrect | unanswered
  const submitRef = useRef(null)

  const spec = subjects.find(s => s.subject === config.subject)

  // Load available subjects (with per-subject exam spec) once.
  function loadSubjects() {
    setError(null)
    api.get('/exam/subjects')
      .then(d => {
        setSubjects(d.subjects)
        if (d.subjects[0]) setConfig(c => ({ ...c, subject: d.subjects[0].subject }))
      })
      .catch(e => setError(e))
  }
  useEffect(() => { loadSubjects() }, [])

  function reset() {
    setQuestions([]); setSelected({}); setStarted(false); setSubmitted(false)
    setTimeLeft(0); setXpEarned(0); setError(null); setFilter('all')
  }

  // Status of a question after submit; drives the review filter and ✓/✗ marks.
  function qStatus(i) {
    if (selected[i] === questions[i].correct_answer) return 'correct'
    if (selected[i]) return 'wrong'
    return 'blank'
  }

  function jumpTo(i) {
    setFilter('all')
    requestAnimationFrame(() =>
      document.getElementById(`q${i}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
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
      setError(e)
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
      const right = selected[i] === q.correct_answer
      gained += awardXP(right ? 'mcq_correct' : 'mcq_incorrect', { subject: config.subject }).gained
      if (!right) recordMistake('exam', config.subject, q)  // wrong or blank → drill it
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

  // Weak areas: group misses by unit (the real study bucket) so every wrong answer is
  // covered — topics are per-question granular, grouping by them only ever shows ~1 each.
  const weakAreas = useMemo(() => {
    if (!submitted) return []
    const m = {}
    questions.forEach((q, i) => {
      if (selected[i] !== q.correct_answer) {
        const loc = q.grade ? `Grade ${q.grade}${q.unit ? ` · Unit ${q.unit}` : ''}` : 'General'
        if (!m[loc]) m[loc] = { count: 0, topics: new Set(), firstIndex: i }
        m[loc].count += 1
        if (q.topic) m[loc].topics.add(q.topic)
      }
    })
    return Object.entries(m).sort((a, b) => b[1].count - a[1].count)
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

        {error && (
          <ErrorState
            title={subjects.length ? "Couldn't start the exam" : "Couldn't load exams"}
            error={error}
            onRetry={subjects.length ? start : loadSubjects}
          />
        )}

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
          <ExamResults score={score} xpEarned={xpEarned} weakAreas={weakAreas}
                       onNew={reset} onJump={jumpTo} />
        )}

        {/* Review filter: jump straight to the questions you missed in a large paper. */}
        {submitted && (
          <div className="review-filter">
            {[['all', 'All'], ['incorrect', 'Incorrect'], ['unanswered', 'Unanswered']].map(([k, lbl]) => {
              const n = k === 'all' ? questions.length
                : k === 'incorrect' ? questions.filter((q, i) => qStatus(i) !== 'correct').length
                : questions.filter((q, i) => qStatus(i) === 'blank').length
              if (n === 0 && k !== 'all') return null  // don't offer a filter that lands on nothing
              return (
                <button key={k} className={`rf-chip ${filter === k ? 'active' : ''}`}
                        aria-pressed={filter === k}
                        onClick={() => setFilter(k)}>
                  {lbl} <span className="rf-n">{n}</span>
                </button>
              )
            })}
          </div>
        )}

        {/* Questions */}
        {questions.map((q, qi) => {
          const userAnswer = selected[qi]
          const correct = q.correct_answer
          if (submitted && filter === 'incorrect' && qStatus(qi) === 'correct') return null
          if (submitted && filter === 'unanswered' && qStatus(qi) !== 'blank') return null
          return (
            <div key={q.id} id={`q${qi}`} className="mcq-card anim">
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

function ExamResults({ score, xpEarned, weakAreas, onNew, onJump }) {
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
          <p className="weak-sub">Units where you missed the most — tap one to jump to those questions.</p>
          <ul className="weak-list">
            {weakAreas.map(([loc, info]) => (
              <li key={loc} className="weak-row" role="button" tabIndex={0}
                  onClick={() => onJump(info.firstIndex)}
                  onKeyDown={e => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), onJump(info.firstIndex))}>
                <span>{loc}{info.topics.size > 0 && (
                  <span className="weak-loc"> — {[...info.topics].slice(0, 4).join(', ')}
                    {info.topics.size > 4 ? '…' : ''}</span>
                )}</span>
                <span className="weak-count">{info.count} missed</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="res-actions">
        <button className="btn btn-ochre" onClick={onNew}>New Exam</button>
      </div>
    </div>
  )
}
