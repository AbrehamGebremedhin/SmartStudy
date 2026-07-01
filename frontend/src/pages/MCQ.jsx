import { useState, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import ConfigPanel from '../components/ui/ConfigPanel'
import DifficultyTag from '../components/ui/DifficultyTag'
import EmptyState from '../components/ui/EmptyState'
import Icon from '../components/ui/Icon'
import Confetti from '../components/ui/Confetti'
import GeneratingState from '../components/ui/GeneratingState'
import ErrorState from '../components/ui/ErrorState'
import { saveGeneration, loadGeneration, updateGeneration } from '../lib/genStorage'
import { awardXP, recordLastGen, resultMessage } from '../lib/gamification'
import { useGenerationWS } from '../hooks/useGenerationWS'
import { recordMistake } from '../services/mistakes.service'
import { recordAttempts } from '../services/analytics.service'

const MCQ_STAGES = [
  { id: 'validating',      label: 'Validating parameters…' },
  { id: 'cache_check',     label: 'Checking for cached questions…' },
  { id: 'loading_context', label: 'Loading curriculum context…' },
  { id: 'generating',      label: 'Crafting questions…' },
  { id: 'saving',          label: 'Saving…' },
]

const DEFAULT_CONFIG = {
  subject: 'biology',
  grade: 12,
  unit: '1',
  difficulty: 'medium',
  numItems: 5,
  topic: null,
}

export default function MCQ() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const genId = searchParams.get('gen')

  const fromNote = searchParams.get('from_note')
  const fromChat = searchParams.get('from_chat')

  const [config, setConfig] = useState(() => ({
    ...DEFAULT_CONFIG,
    subject: searchParams.get('subject') || DEFAULT_CONFIG.subject,
    grade: searchParams.get('grade') ? Number(searchParams.get('grade')) : DEFAULT_CONFIG.grade,
    unit: searchParams.get('unit') || DEFAULT_CONFIG.unit,
    topic: searchParams.get('topic') || DEFAULT_CONFIG.topic,
  }))
  const [questions, setQuestions] = useState([])
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState({})
  const [revealed, setRevealed] = useState({})
  const [currentGenId, setCurrentGenId] = useState(null)
  const [hovered, setHovered] = useState(null) // { qi, letter }
  const [isRetake, setIsRetake] = useState(false) // retakes earn no XP
  const [xpEarned, setXpEarned] = useState(0)

  const { connect, status: wsStatus, currentStageIndex, result: wsResult, error: wsError } = useGenerationWS('mcq')
  const loading = wsStatus === 'connecting' || wsStatus === 'running'

  // Restore from localStorage when navigated from history
  useEffect(() => {
    if (!genId) return
    const saved = loadGeneration(genId)
    if (saved) {
      setQuestions(saved.questions ?? [])
      setSelected(saved.selected ?? {})
      setRevealed(saved.revealed ?? {})
      setCurrentGenId(genId)
      setIsRetake(Boolean(saved.completedAt))
      setXpEarned(saved.xpEarned ?? 0)
      if (saved.config) setConfig(saved.config)
    }
  }, [genId])

  function handleChange(key, value) {
    setConfig(prev => ({ ...prev, [key]: value }))
    setQuestions([])
    setSelected({})
    setRevealed({})
    setCurrentGenId(null)
    setIsRetake(false)
    setXpEarned(0)
    setSearchParams({})
  }

  // Handle WS result
  useEffect(() => {
    if (!wsResult) return
    const qs = wsResult.questions ?? []
    const gid = wsResult.generation_id
    setQuestions(qs)
    setCurrentGenId(gid)
    setIsRetake(false)
    setXpEarned(0)
    saveGeneration(gid, { type: 'mcq', questions: qs, config, selected: {}, revealed: {} })
    setSearchParams({ gen: gid })
    awardXP('gen_mcq', { subject: config.subject })
    recordLastGen({ type: 'mcq', genId: gid, subject: config.subject, grade: config.grade, unit: config.unit, topic: config.topic })
  }, [wsResult]) // eslint-disable-line react-hooks/exhaustive-deps

  // Propagate WS errors
  useEffect(() => {
    if (wsError) setError(wsError.detail ?? 'Generation failed.')
  }, [wsError])

  function handleGenerate() {
    setError(null)
    setSelected({})
    setRevealed({})
    setCurrentGenId(null)
    const isSAT = config.subject === 'sat'
    connect({
      subject: config.subject,
      grade: isSAT ? null : config.grade,
      unit: isSAT ? null : config.unit,
      topic: config.topic || null,
      num_questions: config.numItems,
      difficulty: config.difficulty,
      note_id: fromNote || null,
      chat_session_id: fromChat || null,
    })
  }

  function pick(qi, letter) {
    if (revealed[qi]) return
    const newSelected = { ...selected, [qi]: letter }
    const newRevealed = { ...revealed, [qi]: true }
    setSelected(newSelected)
    setRevealed(newRevealed)

    const allDone = questions.length > 0 &&
      Object.keys(newRevealed).length === questions.length
    const correct = allDone
      ? questions.filter((q, i) => newSelected[i] === q.correct_answer).length
      : 0

    const isCorrect = letter === questions[qi]?.correct_answer
    if (!isCorrect && questions[qi]) recordMistake('mcq', config.subject, questions[qi])
    // Log the attempt for mastery analytics — first attempts only, so retakes don't skew accuracy.
    if (!isRetake && questions[qi]) {
      const isSAT = config.subject === 'sat'
      recordAttempts([{
        subject: config.subject,
        grade: isSAT ? null : config.grade,
        unit: isSAT ? null : String(config.unit),
        topic: questions[qi].topic ?? null,
        correct: isCorrect,
      }])
    }

    let gainedNow = 0
    if (!isRetake) {
      gainedNow += awardXP(isCorrect ? 'mcq_correct' : 'mcq_incorrect', { subject: config.subject }).gained
      if (allDone) {
        gainedNow += awardXP('quiz_complete', { correct, total: questions.length, subject: config.subject }).gained
      }
    }
    if (gainedNow > 0) setXpEarned(x => x + gainedNow)

    if (currentGenId) {
      const existing = loadGeneration(currentGenId)
      const updates = { selected: newSelected, revealed: newRevealed }
      if (gainedNow > 0) updates.xpEarned = (existing?.xpEarned ?? 0) + gainedNow
      if (allDone) {
        updates.score = { correct, total: questions.length }
        updates.completedAt = new Date().toISOString()
        if (!isRetake) updates.xpAwarded = true
      }
      updateGeneration(currentGenId, updates)
    }
  }

  function handleNewQuiz() {
    setSearchParams({})
    setQuestions([])
    setSelected({})
    setRevealed({})
    setCurrentGenId(null)
    setIsRetake(false)
    setXpEarned(0)
  }

  function handleRetry() {
    setSelected({})
    setRevealed({})
    setIsRetake(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const allAnswered = questions.length > 0 &&
    Object.keys(revealed).length === questions.length

  const score = allAnswered
    ? {
        correct: questions.filter((q, i) => selected[i] === q.correct_answer).length,
        total: questions.length,
      }
    : null

  const showConfig = !genId

  return (
    <>
      <div className="pg-top">
        <h2>Practice MCQs</h2>
        <p>Curriculum-based questions with explanations</p>
      </div>
      <div className="pg-body">
        {(fromNote || fromChat) && !genId && (
          <div className="context-banner">
            <Icon name={fromNote ? 'file-text' : 'chat'} size={15} />
            {fromNote ? 'Generating from your note — topic and subject are pre-filled.' : 'Generating from your chat session.'}
          </div>
        )}

        {showConfig ? (
          <ConfigPanel
            config={config}
            onChange={handleChange}
            onGenerate={handleGenerate}
            loading={loading}
            numItemsLabel="Questions"
            generateLabel="Generate Questions"
  
            showTopic={false}
          />
        ) : (
          <div className="back-row">
            <button className="btn btn-ghost btn-sm" onClick={handleNewQuiz}>
              ← New Quiz
            </button>
          </div>
        )}

        {error && (
          <ErrorState title="Couldn't generate questions" error={error} onRetry={handleGenerate} />
        )}

        {loading && (
          <GeneratingState
            stageDefs={MCQ_STAGES}
            currentStageIndex={currentStageIndex}
            status={wsStatus}
          />
        )}

        {!loading && questions.length === 0 && !error && (
          <EmptyState
            icon="quiz"
            title="Ready When You Are"
            description="Configure above and tap Generate to create practice questions from your textbook content."
          />
        )}

        {/* If exam is complete, show results first, then questions below */}
        {allAnswered && score && (
          <MCQResults
            questions={questions}
            selected={selected}
            score={score}
            xpEarned={xpEarned}
            isRetake={isRetake}
            genId={currentGenId}
            onRetry={handleRetry}
            onNewQuiz={handleNewQuiz}
            notesTopic={config.topic || questions[0]?.topic || null}
            onNotes={topic =>
              navigate(`/notes?subject=${config.subject}&grade=${config.grade}&unit=${config.unit}&topic=${encodeURIComponent(topic)}`)
            }
          />
        )}

        {questions.map((q, qi) => {
          const isRevealed = revealed[qi]
          const userAnswer = selected[qi]
          const correct = q.correct_answer
          const options = q.options ?? []

          return (
            <div key={qi} className="mcq-card anim">
              <div className="mcq-top">
                <span className="mcq-topic">{q.topic ?? `Question ${qi + 1}`}</span>
                <DifficultyTag difficulty={q.difficulty ?? config.difficulty} />
              </div>
              <div className="mcq-body">
                {q.passage && (
                  <div className="mcq-passage">{q.passage}</div>
                )}
                <div className="mcq-q">{qi + 1}. {q.question}</div>
                <div className="mcq-opts">
                  {options.map((opt, oi) => {
                    const letter = opt[0]
                    const isCorrect = letter === correct
                    const isSelected = letter === userAnswer
                    const tooltipText = isRevealed && !isCorrect
                      ? q.incorrect_explanations?.[letter]
                      : null
                    const showTooltip =
                      tooltipText &&
                      hovered?.qi === qi &&
                      hovered?.letter === letter

                    let cls = 'mcq-opt'
                    if (isRevealed && isCorrect) cls += ' ok'
                    else if (isRevealed && isSelected && !isCorrect) cls += ' no'

                    return (
                      <div key={oi} className="opt-wrap">
                        <button
                          className={cls}
                          onClick={() => pick(qi, letter)}
                          onMouseEnter={() => tooltipText && setHovered({ qi, letter })}
                          onMouseLeave={() => setHovered(null)}
                        >
                          <span className="o-let">{letter}</span>
                          <span>{opt.slice(3)}</span>
                        </button>
                        {showTooltip && (
                          <div className="opt-tooltip">✗ {tooltipText}</div>
                        )}
                      </div>
                    )
                  })}
                </div>

                {isRevealed && (
                  <div className="mcq-expl">
                    <strong>
                      {userAnswer === correct ? '✓ Correct!' : `✗ The answer is ${correct}`}
                    </strong>
                    {(q.correct_explanations ?? []).map((e, i) => (
                      <div key={i} style={{ marginTop: 3 }}>• {e}</div>
                    ))}
                    {userAnswer !== correct && q.incorrect_explanations?.[userAnswer] && (
                      <div style={{ marginTop: 8, color: 'var(--vermillion)' }}>
                        Why your choice is wrong: {q.incorrect_explanations[userAnswer]}
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

function useCountUp(target, duration = 800) {
  const [value, setValue] = useState(0)
  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setValue(target)
      return
    }
    let raf
    const start = performance.now()
    function tick(now) {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      setValue(Math.round(eased * target))
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, duration])
  return value
}

function MCQResults({ questions, selected, score, xpEarned, isRetake, genId, onRetry, onNewQuiz, notesTopic, onNotes }) {
  const pct = Math.round((score.correct / score.total) * 100)
  const band = pct >= 80 ? 'band-high' : pct >= 50 ? 'band-mid' : 'band-low'
  const label = pct >= 80 ? 'Excellent' : pct >= 50 ? 'Keep Practicing' : 'Needs Work'
  const displayCorrect = useCountUp(score.correct)
  const celebrate = pct >= 80 && !isRetake

  return (
    <div className="mcq-results anim res-wrap">
      <div className="results-header">
        {celebrate && <Confetti />}
        <div className="results-title">Exam Complete</div>
        <div className="results-score">
          <span className="score-num">{displayCorrect}</span>
          <span className="score-sep">/{score.total}</span>
          <span className="score-pct">{pct}%</span>
        </div>
        <div className={`score-band ${band}`}>{label}</div>
        <div className="res-msg">{resultMessage(pct, genId ?? '')}</div>
        {isRetake ? (
          <div className="res-xp">Practice round — XP already earned</div>
        ) : xpEarned > 0 ? (
          <div className="res-xp"><Icon name="star" size={14} /> +{xpEarned} XP earned</div>
        ) : null}
      </div>

      <div className="res-actions">
        <button className="btn btn-ochre" onClick={onRetry}>
          <Icon name="retry" size={15} /> Retry Quiz
        </button>
        <button className="btn btn-ghost" onClick={onNewQuiz}>New Quiz</button>
        {notesTopic && (
          <button className="btn btn-indigo" onClick={() => onNotes(notesTopic)}>
            Generate Notes
          </button>
        )}
      </div>

      <table className="results-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Topic</th>
            <th>Your Answer</th>
            <th>Correct</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {questions.map((q, qi) => {
            const isCorrect = selected[qi] === q.correct_answer
            return (
              <tr key={qi} className={isCorrect ? 'row-ok' : 'row-no'}>
                <td>{qi + 1}</td>
                <td className="topic-cell">{q.topic ?? `Q${qi + 1}`}</td>
                <td>{selected[qi] ?? '—'}</td>
                <td>{q.correct_answer}</td>
                <td>{isCorrect ? '✓' : '✗'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
