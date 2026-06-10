import { useState, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import ConfigPanel from '../components/ui/ConfigPanel'
import DifficultyTag from '../components/ui/DifficultyTag'
import EmptyState from '../components/ui/EmptyState'
import { generateMCQ } from '../services/mcq.service'
import { saveGeneration, loadGeneration, updateGeneration } from '../lib/genStorage'

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
    topic: searchParams.get('topic') || DEFAULT_CONFIG.topic,
  }))
  const [questions, setQuestions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState({})
  const [revealed, setRevealed] = useState({})
  const [currentGenId, setCurrentGenId] = useState(null)
  const [hovered, setHovered] = useState(null) // { qi, letter }

  // Restore from localStorage when navigated from history
  useEffect(() => {
    if (!genId) return
    const saved = loadGeneration(genId)
    if (saved) {
      setQuestions(saved.questions ?? [])
      setSelected(saved.selected ?? {})
      setRevealed(saved.revealed ?? {})
      setCurrentGenId(genId)
      if (saved.config) setConfig(saved.config)
    }
  }, [genId])

  function handleChange(key, value) {
    setConfig(prev => ({ ...prev, [key]: value }))
    setQuestions([])
    setSelected({})
    setRevealed({})
    setCurrentGenId(null)
    setSearchParams({})
  }

  async function handleGenerate() {
    setLoading(true)
    setError(null)
    setSelected({})
    setRevealed({})
    setCurrentGenId(null)
    try {
      const res = await generateMCQ({
        subject: config.subject,
        grade: config.grade,
        unit: config.unit,
        topic: config.topic || null,
        num_questions: config.numItems,
        difficulty: config.difficulty,
        note_id: fromNote || null,
        chat_session_id: fromChat || null,
      })
      const qs = res.questions ?? []
      const gid = res.generation_id
      setQuestions(qs)
      setCurrentGenId(gid)
      saveGeneration(gid, { type: 'mcq', questions: qs, config, selected: {}, revealed: {} })
      setSearchParams({ gen: gid })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function pick(qi, letter) {
    if (revealed[qi]) return
    const newSelected = { ...selected, [qi]: letter }
    const newRevealed = { ...revealed, [qi]: true }
    setSelected(newSelected)
    setRevealed(newRevealed)

    if (currentGenId) {
      const allDone = questions.length > 0 &&
        Object.keys(newRevealed).length === questions.length
      const updates = { selected: newSelected, revealed: newRevealed }
      if (allDone) {
        const correct = questions.filter((q, i) => newSelected[i] === q.correct_answer).length
        updates.score = { correct, total: questions.length }
        updates.completedAt = new Date().toISOString()
      }
      updateGeneration(currentGenId, updates)
    }
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
          <div style={{ padding: '10px 14px', background: 'var(--ochre-glow)', borderRadius: 'var(--r-s)', marginBottom: 12, fontSize: 13, color: 'var(--ochre-deep)', fontWeight: 600 }}>
            {fromNote ? '📄 Generating from your note — topic and subject are pre-filled.' : '💬 Generating from your chat session.'}
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
            excludeSubjects={['sat']}
            showTopic={!fromNote && !fromChat}
          />
        ) : (
          <div style={{ marginBottom: 16 }}>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setSearchParams({})
                setQuestions([])
                setSelected({})
                setRevealed({})
                setCurrentGenId(null)
              }}
            >
              ← New Quiz
            </button>
          </div>
        )}

        {error && (
          <div style={{ color: 'var(--vermillion)', marginBottom: 16, fontSize: 14 }}>
            {error}
          </div>
        )}

        {!loading && questions.length === 0 && !error && (
          <EmptyState
            icon="✦"
            title="Ready When You Are"
            description="Configure above and tap Generate to create practice questions from your textbook content."
          />
        )}

        {/* If exam is complete, show results first, then questions below */}
        {allAnswered && score && (
          <>
            <MCQResults questions={questions} selected={selected} score={score} />
            {config.topic && (
              <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'flex-end' }}>
                <button
                  className="btn btn-ghost btn-sm"
                  onClick={() => navigate(`/notes?subject=${config.subject}&grade=${config.grade}&topic=${encodeURIComponent(config.topic)}`)}
                >
                  Generate Notes on "{config.topic}" →
                </button>
              </div>
            )}
          </>
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
                  <div style={{
                    background: 'var(--sandstone)',
                    borderRadius: 'var(--r-m)',
                    padding: '12px 14px',
                    marginBottom: 14,
                    fontSize: 14,
                    lineHeight: 1.7,
                    color: 'var(--ink-2)',
                  }}>
                    {q.passage}
                  </div>
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

function MCQResults({ questions, selected, score }) {
  const pct = Math.round((score.correct / score.total) * 100)
  const band = pct >= 80 ? 'band-high' : pct >= 50 ? 'band-mid' : 'band-low'
  const label = pct >= 80 ? 'Excellent' : pct >= 50 ? 'Keep Practicing' : 'Needs Work'

  return (
    <div className="mcq-results anim" style={{ marginBottom: 24 }}>
      <div className="results-header">
        <div className="results-title">Exam Complete</div>
        <div className="results-score">
          <span className="score-num">{score.correct}</span>
          <span className="score-sep">/{score.total}</span>
          <span className="score-pct">{pct}%</span>
        </div>
        <div className={`score-band ${band}`}>{label}</div>
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
