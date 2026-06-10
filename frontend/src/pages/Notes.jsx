import { useState, useEffect, useRef } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import ConfigPanel from '../components/ui/ConfigPanel'
import EmptyState from '../components/ui/EmptyState'
import { generateNotes, chatWithNote } from '../services/notes.service'
import { evaluateAnswer } from '../services/evaluation.service'
import { saveGeneration, loadGeneration } from '../lib/genStorage'

const DEFAULT_CONFIG = {
  subject: 'biology',
  grade: 12,
  unit: '1',
  difficulty: 'medium',
  topic: '',
}

export default function Notes() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const genId = searchParams.get('gen')

  // Pre-fill params (used when navigating here from MCQ/Flashcard/Chat)
  const fromChat = searchParams.get('from_chat')

  const [config, setConfig] = useState(() => ({
    ...DEFAULT_CONFIG,
    subject: searchParams.get('subject') || DEFAULT_CONFIG.subject,
    grade: searchParams.get('grade') ? Number(searchParams.get('grade')) : DEFAULT_CONFIG.grade,
    unit: searchParams.get('unit') || DEFAULT_CONFIG.unit,
    topic: searchParams.get('topic') || DEFAULT_CONFIG.topic,
  }))
  const [notes, setNotes] = useState(null)
  const [currentGenId, setCurrentGenId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Note chat state
  const [chatHistory, setChatHistory] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [chatError, setChatError] = useState(null)
  const chatBottomRef = useRef(null)

  useEffect(() => {
    if (!genId) return
    const saved = loadGeneration(genId)
    if (saved) {
      setNotes(saved.notes ?? null)
      setCurrentGenId(genId)
      if (saved.config) setConfig(saved.config)
    }
  }, [genId])

  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatHistory])

  function handleChange(key, value) {
    setConfig(prev => ({ ...prev, [key]: value }))
    if (key !== 'topic') setNotes(null)
  }

  async function handleGenerate() {
    if (!config.topic.trim()) {
      setError('Please enter a topic.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const res = await generateNotes({
        subject: config.subject,
        topic: config.topic,
        grade: config.grade,
        unit: config.unit,
        chat_session_id: fromChat || null,
      })
      const n = res.notes ?? null
      setNotes(n)
      setCurrentGenId(res.generation_id)
      setChatHistory([])
      saveGeneration(res.generation_id, { type: 'notes', notes: n, config })
      setSearchParams({ gen: res.generation_id })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  async function handleChatSend(question) {
    const q = (question ?? chatInput).trim()
    if (!q || !currentGenId) return
    const newHistory = [...chatHistory, { role: 'user', content: q }]
    setChatHistory(newHistory)
    setChatInput('')
    setChatLoading(true)
    setChatError(null)
    try {
      const res = await chatWithNote(currentGenId, q, chatHistory)
      setChatHistory([...newHistory, { role: 'assistant', content: res.answer, key_concepts: res.key_concepts, follow_up_questions: res.follow_up_questions }])
    } catch (e) {
      setChatError(e.message)
    } finally {
      setChatLoading(false)
    }
  }

  return (
    <>
      <div className="pg-top">
        <h2>Study Notes</h2>
        <p>Comprehensive notes with worked examples</p>
      </div>
      <div className="pg-body">
        {genId && notes ? (
          <div style={{ marginBottom: 16 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => {
              setSearchParams({})
              setNotes(null)
            }}>
              ← New Notes
            </button>
          </div>
        ) : (
          <ConfigPanel
            config={config}
            onChange={handleChange}
            onGenerate={handleGenerate}
            loading={loading}
            showDifficulty={false}
            showNumItems={false}
            showTopic={true}
            generateLabel="Generate Notes"
          />
        )}

        {error && (
          <div style={{ color: 'var(--vermillion)', marginBottom: 16, fontSize: 14 }}>
            {error}
          </div>
        )}

        {!loading && !notes && !error && (
          <EmptyState
            icon="≡"
            title="Generate Study Notes"
            description="Enter a topic for detailed notes with key concepts, examples, and review questions."
          />
        )}

        {notes && <NotesContent notes={notes} subject={config.subject} />}

        {notes && currentGenId && (
          <>
            {/* ── What's Next? ── */}
            <div style={{ marginTop: 32, padding: '20px 24px', background: 'var(--sandstone)', borderRadius: 'var(--r-xl)', display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center' }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--ink-3)', marginRight: 4 }}>Study with:</span>
              <button
                className="btn btn-ochre btn-sm"
                onClick={() => navigate(`/mcq?from_note=${currentGenId}&subject=${config.subject}&grade=${config.grade}&unit=${config.unit}&topic=${encodeURIComponent(notes.title || config.topic)}`)}
              >
                Practice MCQs
              </button>
              <button
                className="btn btn-sm"
                style={{ background: 'var(--indigo)', color: '#fff' }}
                onClick={() => navigate(`/flashcards?from_note=${currentGenId}&subject=${config.subject}&grade=${config.grade}&unit=${config.unit}&topic=${encodeURIComponent(notes.title || config.topic)}`)}
              >
                Create Flashcards
              </button>
            </div>

            {/* ── Note Chat ── */}
            <div style={{ marginTop: 24 }}>
              <h3 className="n-sec-t" style={{ marginBottom: 16 }}>Ask About This Note</h3>
              <div style={{ background: 'var(--parchment)', border: '1.5px solid var(--border)', borderRadius: 'var(--r-xl)', overflow: 'hidden' }}>

                {/* Message thread */}
                {chatHistory.length > 0 && (
                  <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12, maxHeight: 420, overflowY: 'auto' }}>
                    {chatHistory.map((msg, i) => (
                      <div key={i}>
                        <div style={{
                          alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                          display: 'inline-block',
                          maxWidth: '85%',
                          background: msg.role === 'user' ? 'var(--ink)' : 'var(--sandstone)',
                          color: msg.role === 'user' ? 'var(--parchment)' : 'var(--ink)',
                          borderRadius: msg.role === 'user' ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                          padding: '10px 14px',
                          fontSize: 14,
                          lineHeight: 1.6,
                        }}>
                          {msg.content}
                        </div>
                        {msg.role === 'assistant' && msg.follow_up_questions?.length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                            {msg.follow_up_questions.map((q, j) => (
                              <button
                                key={j}
                                onClick={() => handleChatSend(q)}
                                disabled={chatLoading}
                                style={{ background: 'var(--ochre-glow)', border: 'none', borderRadius: 20, padding: '4px 12px', fontSize: 12, cursor: 'pointer', color: 'var(--ochre-deep)', fontWeight: 600 }}
                              >
                                {q}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                    {chatLoading && (
                      <div style={{ fontSize: 13, color: 'var(--ink-3)', fontStyle: 'italic' }}>Thinking…</div>
                    )}
                    {chatError && (
                      <div style={{ fontSize: 13, color: 'var(--vermillion)' }}>{chatError}</div>
                    )}
                    <div ref={chatBottomRef} />
                  </div>
                )}

                {/* Input row */}
                <div style={{ display: 'flex', gap: 8, padding: '12px 16px', borderTop: chatHistory.length > 0 ? '1px solid var(--border)' : 'none', background: 'var(--parchment)' }}>
                  <input
                    type="text"
                    value={chatInput}
                    onChange={e => setChatInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleChatSend() } }}
                    placeholder="Ask anything about this note…"
                    disabled={chatLoading}
                    style={{ flex: 1, padding: '9px 14px', borderRadius: 'var(--r-s)', border: '1.5px solid var(--border)', background: 'var(--parchment)', color: 'var(--ink)', fontSize: 14, outline: 'none', fontFamily: 'var(--f-body)' }}
                    onFocus={e => { e.target.style.borderColor = 'var(--ochre)' }}
                    onBlur={e => { e.target.style.borderColor = 'var(--border)' }}
                  />
                  <button
                    className="btn btn-ochre btn-sm"
                    onClick={() => handleChatSend()}
                    disabled={chatLoading || !chatInput.trim()}
                  >
                    {chatLoading ? '…' : 'Send'}
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  )
}

// ─── Primitives ──────────────────────────────────────────────────────────────

function SecTitle({ children }) {
  return <h3 className="n-sec-t">{children}</h3>
}

function Label({ children, color = 'var(--ink-3)' }) {
  return (
    <div className="n-label" style={{ color }}>{children}</div>
  )
}

function BulletList({ items }) {
  if (!items?.length) return null
  return (
    <ul style={{ paddingLeft: 20, marginTop: 6 }}>
      {items.map((it, i) => (
        <li key={i} className="n-text" style={{ marginBottom: 4 }}>{it}</li>
      ))}
    </ul>
  )
}

function Chips({ items }) {
  if (!items?.length) return null
  return (
    <div className="n-chips">
      {items.map((it, i) => <span key={i} className="n-chip">{it}</span>)}
    </div>
  )
}

// ─── Main renderer ───────────────────────────────────────────────────────────

function NotesContent({ notes, subject }) {
  const overview      = notes.overview ?? null
  const objectives    = notes.learning_objectives ?? []
  const keyConcepts   = notes.key_concepts ?? []
  const framework     = notes.theoretical_framework ?? null
  const formulas      = notes.formulas_and_equations ?? []
  const workedEx      = notes.worked_examples ?? []
  const practiceProbs = notes.practice_problems ?? []
  const realWorld     = notes.real_world_applications ?? []
  const connections   = notes.connections ?? null
  const reviewQs      = notes.review_questions ?? []

  return (
    <div className="notes-w anim">

      {/* ── Cover: title + overview ── */}
      {(notes.title || overview) && (
        <div className="n-sec">
          {/* Dark cover card */}
          <div style={{
            background: 'var(--ink)',
            borderRadius: 'var(--r-xl)',
            padding: '32px 28px',
            marginBottom: 16,
            position: 'relative',
            overflow: 'hidden',
          }}>
            <div style={{
              position: 'absolute', inset: 0,
              background: 'radial-gradient(ellipse at 80% 20%, rgba(196,132,29,0.15) 0%, transparent 60%)',
              pointerEvents: 'none',
            }} />
            {notes.title && (
              <div style={{
                fontFamily: 'var(--f-display)',
                fontSize: 26,
                fontWeight: 700,
                color: 'var(--ochre-glow)',
                marginBottom: 10,
                position: 'relative',
              }}>
                {notes.title}
              </div>
            )}
            {overview?.brief_summary && (
              <p style={{
                fontSize: 15,
                lineHeight: 1.8,
                color: 'rgba(246,240,228,0.55)',
                maxWidth: 640,
                position: 'relative',
              }}>
                {overview.brief_summary}
              </p>
            )}
            {overview?.prerequisites?.length > 0 && (
              <div style={{ marginTop: 16, position: 'relative' }}>
                <div style={{ fontSize: 10, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.12em', color: 'rgba(196,132,29,0.5)', marginBottom: 8 }}>
                  Prerequisites
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {overview.prerequisites.map((p, i) => (
                    <span key={i} style={{
                      background: 'rgba(196,132,29,0.12)',
                      border: '1px solid rgba(196,132,29,0.2)',
                      borderRadius: 20,
                      padding: '3px 12px',
                      fontSize: 12,
                      color: 'var(--ochre-glow)',
                    }}>{p}</span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* 2-col overview detail cards */}
          {(overview?.importance || overview?.historical_context) && (
            <div className="n-grid-2">
              {overview?.importance && (
                <div className="n-card" style={{ borderTop: '3px solid var(--ochre)' }}>
                  <Label color="var(--ochre-deep)">Why it matters</Label>
                  <div className="n-text">{overview.importance}</div>
                </div>
              )}
              {overview?.historical_context && (
                <div className="n-card" style={{ borderTop: '3px solid var(--indigo)' }}>
                  <Label color="var(--indigo)">Historical context</Label>
                  <div className="n-text">{overview.historical_context}</div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── Learning Objectives ── */}
      {objectives.length > 0 && (
        <div className="n-sec">
          <SecTitle>Learning Objectives</SecTitle>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {objectives.map((obj, i) => (
              <div key={i} className="n-obj">
                <div className="n-obj-num">{i + 1}</div>
                <div className="n-obj-body">
                  <div className="n-obj-title">{obj.objective}</div>
                  {obj.success_criteria?.length > 0 && (
                    <ul style={{ paddingLeft: 16, margin: 0 }}>
                      {obj.success_criteria.map((sc, j) => (
                        <li key={j} className="n-text" style={{ marginBottom: 2 }}>{sc}</li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Key Concepts ── */}
      {keyConcepts.length > 0 && (
        <div className="n-sec">
          <SecTitle>Key Concepts</SecTitle>
          {keyConcepts.map((kc, i) => (
            <div key={i} className="n-concept-card">
              <h4>{kc.concept}</h4>
              {kc.detailed_explanation && (
                <div className="n-text" style={{ marginBottom: 14 }}>{kc.detailed_explanation}</div>
              )}

              {kc.sub_concepts?.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <Label>Sub-concepts</Label>
                  {kc.sub_concepts.map((sc, j) => (
                    <div key={j} className="n-sub">
                      <div className="n-sub-title">{sc.name}</div>
                      <div className="n-text">{sc.explanation}</div>
                      <BulletList items={sc.applications} />
                    </div>
                  ))}
                </div>
              )}

              {kc.examples?.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <Label color="var(--ochre-deep)">Examples</Label>
                  {kc.examples.map((ex, j) => (
                    <div key={j} style={{
                      background: 'var(--sandstone)',
                      borderRadius: 'var(--r-s)',
                      padding: '12px 16px',
                      marginBottom: 8,
                      borderLeft: '3px solid var(--ochre)',
                    }}>
                      {ex.scenario && <div className="n-text" style={{ fontWeight: 600, marginBottom: 4 }}>{ex.scenario}</div>}
                      {ex.demonstration && <div className="n-text">{ex.demonstration}</div>}
                      {ex.analysis && <div className="n-text" style={{ marginTop: 6, color: 'var(--ink-3)', fontStyle: 'italic' }}>{ex.analysis}</div>}
                    </div>
                  ))}
                </div>
              )}

              {kc.common_misconceptions?.length > 0 && (
                <div>
                  <Label color="var(--vermillion)">Common Misconceptions</Label>
                  {kc.common_misconceptions.map((m, j) => (
                    <div key={j} className="n-misc" style={{ background: 'var(--vermillion-l)', marginBottom: 6 }}>
                      <div className="n-text" style={{ color: 'var(--vermillion)', fontWeight: 600 }}>✗ {m.misconception}</div>
                      <div className="n-text" style={{ color: 'var(--highland)', marginTop: 5, paddingTop: 5, borderTop: '1px solid rgba(0,0,0,0.06)' }}>✓ {m.correction}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Theoretical Framework ── */}
      {framework && (framework.principles?.length || framework.theories?.length || framework.models?.length) ? (
        <div className="n-sec">
          <SecTitle>Theoretical Framework</SecTitle>
          {framework.principles?.length > 0 && (
            <div className="n-card" style={{ marginBottom: 10 }}>
              <Label>Core Principles</Label>
              <Chips items={framework.principles} />
            </div>
          )}
          {framework.theories?.map((t, i) => (
            <div key={i} className="n-card" style={{ marginBottom: 10 }}>
              <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--ink)', marginBottom: 6 }}>{t.name}</div>
              <div className="n-text" style={{ marginBottom: 8 }}>{t.explanation}</div>
              <BulletList items={t.applications} />
            </div>
          ))}
          {framework.models?.length > 0 && (
            <div className="n-card">
              <Label>Models</Label>
              <Chips items={framework.models} />
            </div>
          )}
        </div>
      ) : null}

      {/* ── Formulas & Equations ── */}
      {formulas.length > 0 && (
        <div className="n-sec">
          <SecTitle>Formulas & Equations</SecTitle>
          {formulas.map((f, i) => (
            <div key={i} className="n-card" style={{ marginBottom: 10 }}>
              <div className="n-formula">{f.formula}</div>
              {f.variables && Object.keys(f.variables).length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <Label>Variables</Label>
                  <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <tbody>
                      {Object.entries(f.variables).map(([k, v]) => (
                        <tr key={k}>
                          <td style={{ fontFamily: 'var(--f-mono)', fontWeight: 700, fontSize: 14, padding: '4px 12px 4px 0', color: 'var(--indigo)', width: '20%', verticalAlign: 'top' }}>{k}</td>
                          <td className="n-text" style={{ padding: '4px 0' }}>{v}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {f.derivation && (
                <div style={{ marginBottom: 8 }}>
                  <Label>Derivation</Label>
                  <div className="n-text">{f.derivation}</div>
                </div>
              )}
              {f.applications?.length > 0 && (
                <>
                  <Label>Applications</Label>
                  <BulletList items={f.applications} />
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Worked Examples ── */}
      {workedEx.length > 0 && (
        <div className="n-sec">
          <SecTitle>Worked Examples</SecTitle>
          {workedEx.map((ex, i) => (
            <div key={i} className="n-card tibeb-left" style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 800, textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--ochre)', marginBottom: 10 }}>
                Example {i + 1}
              </div>
              {ex.problem_statement && (
                <div className="n-text" style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: 14, fontSize: 16 }}>
                  {ex.problem_statement}
                </div>
              )}
              {ex.approach?.length > 0 && (
                <div style={{ marginBottom: 14 }}>
                  <Label>Approach</Label>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
                    {ex.approach.map((step, j) => (
                      <div key={j} className="n-step">
                        <div className="n-step-num">{j + 1}</div>
                        <div className="n-text">{step}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {ex.solution && (
                <div style={{
                  background: 'var(--highland-l)',
                  borderRadius: 'var(--r-s)',
                  padding: '12px 16px',
                  borderLeft: '3px solid var(--highland)',
                  marginBottom: 10,
                }}>
                  <Label color="var(--highland)">Solution</Label>
                  <div className="n-text">{ex.solution}</div>
                </div>
              )}
              {ex.common_pitfalls?.length > 0 && (
                <>
                  <Label color="var(--vermillion)">Common Pitfalls</Label>
                  <BulletList items={ex.common_pitfalls} />
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ── Practice Problems ── */}
      {practiceProbs.length > 0 && (
        <div className="n-sec">
          <SecTitle>Practice Problems</SecTitle>
          {practiceProbs.map((prob, i) => (
            <PracticeProblem key={i} index={i} problem={prob} />
          ))}
        </div>
      )}

      {/* ── Real-World Applications ── */}
      {realWorld.length > 0 && (
        <div className="n-sec">
          <SecTitle>Real-World Applications</SecTitle>
          <div className="n-grid-2">
            {realWorld.map((app, i) => (
              <div key={i} className="n-card" style={{ borderTop: '3px solid var(--highland)' }}>
                <Label color="var(--highland)">Context</Label>
                <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--ink)', marginBottom: 6 }}>{app.context}</div>
                <div className="n-text" style={{ marginBottom: 8 }}>{app.explanation}</div>
                <BulletList items={app.examples} />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Connections ── */}
      {connections && (connections.related_topics?.length || connections.future_applications?.length) ? (
        <div className="n-sec">
          <SecTitle>Connections</SecTitle>
          <div className="n-grid-2">
            {connections.related_topics?.length > 0 && (
              <div className="n-card">
                <Label>Related Topics</Label>
                <Chips items={connections.related_topics} />
              </div>
            )}
            {connections.future_applications?.length > 0 && (
              <div className="n-card">
                <Label>Future Applications</Label>
                <Chips items={connections.future_applications} />
              </div>
            )}
          </div>
        </div>
      ) : null}

      {/* ── Review Questions ── */}
      {reviewQs.length > 0 && (
        <div className="n-sec">
          <SecTitle>Review Questions</SecTitle>
          {reviewQs.map((q, i) => (
            <ReviewQuestion key={i} index={i} question={q} subject={subject} note={notes} />
          ))}
        </div>
      )}

    </div>
  )
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function PracticeProblem({ index, problem }) {
  const [hintsOpen, setHintsOpen] = useState(false)
  return (
    <div className="n-card" style={{ marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, marginBottom: problem.hints?.length ? 10 : 0 }}>
        <div className="n-text" style={{ fontWeight: 600, color: 'var(--ink)' }}>
          {index + 1}. {problem.question}
        </div>
        {problem.difficulty_level && (
          <span style={{ fontSize: 10, padding: '3px 10px', borderRadius: 20, background: 'var(--ochre-glow)', color: 'var(--ochre-deep)', fontWeight: 800, flexShrink: 0 }}>
            {problem.difficulty_level}
          </span>
        )}
      </div>
      {problem.hints?.length > 0 && (
        <>
          <button
            onClick={() => setHintsOpen(o => !o)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--indigo)', fontSize: 13, fontWeight: 700, padding: 0, display: 'flex', alignItems: 'center', gap: 4 }}
          >
            {hintsOpen ? '▲' : '▼'} {hintsOpen ? 'Hide hints' : 'Show hints'}
          </button>
          {hintsOpen && (
            <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border)' }}>
              <BulletList items={problem.hints} />
              {problem.solution_approach && (
                <div className="n-text" style={{ marginTop: 6, fontStyle: 'italic', color: 'var(--ink-3)' }}>
                  Approach: {problem.solution_approach}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ReviewQuestion({ index, question, subject, note }) {
  const [draft, setDraft] = useState('')
  const [evaluating, setEvaluating] = useState(false)
  const [result, setResult] = useState(null)
  const [evalError, setEvalError] = useState(null)

  const text = typeof question === 'string' ? question : question.question ?? question.text ?? ''

  async function handleEvaluate() {
    if (!draft.trim()) return
    setEvaluating(true)
    setResult(null)
    setEvalError(null)
    try {
      const res = await evaluateAnswer({
        subject: subject ?? 'general',
        question: typeof question === 'string' ? { question: text } : question,
        student_answer: draft.trim(),
        note: note ?? null,
      })
      setResult(res)
    } catch (e) {
      setEvalError(e.message)
    } finally {
      setEvaluating(false)
    }
  }

  const scorePct = result ? Math.round(result.score * 100) : null
  const scoreColor = scorePct >= 80 ? 'var(--highland)' : scorePct >= 50 ? 'var(--ochre-deep)' : 'var(--vermillion)'
  const scoreBg = scorePct >= 80 ? 'var(--highland-l)' : scorePct >= 50 ? 'var(--ochre-glow)' : 'var(--vermillion-l)'

  return (
    <div className="n-card" style={{ marginBottom: 10 }}>
      {/* Question */}
      <div className="n-text" style={{ fontWeight: 600, color: 'var(--ink)', marginBottom: 14 }}>
        {index + 1}. {text}
      </div>

      {/* Answer input */}
      {!result && (
        <>
          <textarea
            value={draft}
            onChange={e => setDraft(e.target.value)}
            placeholder="Write your answer here…"
            rows={4}
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '10px 12px',
              borderRadius: 'var(--r-s)',
              border: '1.5px solid var(--border)',
              background: 'var(--parchment)',
              color: 'var(--ink)',
              fontSize: 14,
              fontFamily: 'var(--f-body)',
              lineHeight: 1.6,
              resize: 'vertical',
              outline: 'none',
              transition: 'border-color 0.15s',
            }}
            onFocus={e => { e.target.style.borderColor = 'var(--ochre)' }}
            onBlur={e => { e.target.style.borderColor = 'var(--border)' }}
            disabled={evaluating}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
            <button
              className="btn btn-ochre btn-sm"
              onClick={handleEvaluate}
              disabled={evaluating || !draft.trim()}
            >
              {evaluating ? 'Evaluating…' : 'Submit Answer'}
            </button>
          </div>
        </>
      )}

      {evalError && (
        <div className="n-text" style={{ color: 'var(--vermillion)', marginTop: 8 }}>{evalError}</div>
      )}

      {/* Evaluation result */}
      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {/* Score hero */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            background: scoreBg,
            borderRadius: 'var(--r-s)',
            padding: '12px 16px',
            borderLeft: `3px solid ${scoreColor}`,
          }}>
            <div style={{
              fontFamily: 'var(--f-mono)',
              fontSize: 26,
              fontWeight: 800,
              color: scoreColor,
              lineHeight: 1,
            }}>
              {scorePct}%
            </div>
            <div>
              <div style={{ fontWeight: 700, fontSize: 14, color: scoreColor }}>
                {result.is_correct ? 'Correct' : scorePct >= 50 ? 'Partially Correct' : 'Needs Improvement'}
              </div>
              <div className="n-text" style={{ marginTop: 2 }}>{result.feedback}</div>
            </div>
          </div>

          {/* Strengths */}
          {result.strengths?.length > 0 && result.strengths[0] !== 'Evaluation failed' && (
            <div style={{ background: 'var(--highland-l)', borderRadius: 'var(--r-s)', padding: '10px 14px', borderLeft: '3px solid var(--highland)' }}>
              <Label color="var(--highland)">Strengths</Label>
              <BulletList items={result.strengths} />
            </div>
          )}

          {/* Key points missed */}
          {result.key_points_missed?.length > 0 && result.key_points_missed[0] !== 'Evaluation failed' && (
            <div style={{ background: 'var(--ochre-glow)', borderRadius: 'var(--r-s)', padding: '10px 14px', borderLeft: '3px solid var(--ochre)' }}>
              <Label color="var(--ochre-deep)">Key Points Missed</Label>
              <BulletList items={result.key_points_missed} />
            </div>
          )}

          {/* Misconceptions */}
          {result.misconceptions?.length > 0 && result.misconceptions[0] !== 'Evaluation failed' && (
            <div style={{ background: 'var(--vermillion-l)', borderRadius: 'var(--r-s)', padding: '10px 14px', borderLeft: '3px solid var(--vermillion)' }}>
              <Label color="var(--vermillion)">Misconceptions</Label>
              <BulletList items={result.misconceptions} />
            </div>
          )}

          {/* Improvement suggestions */}
          {result.improvement_suggestions?.length > 0 && (
            <div style={{ background: 'var(--sandstone)', borderRadius: 'var(--r-s)', padding: '10px 14px' }}>
              <Label>Improvement Suggestions</Label>
              <BulletList items={result.improvement_suggestions} />
            </div>
          )}

          {/* Model answer */}
          {result.correct_solution?.length > 0 && (
            <div style={{ background: 'var(--sandstone)', borderRadius: 'var(--r-s)', padding: '10px 14px', borderLeft: '3px solid var(--indigo)' }}>
              <Label color="var(--indigo)">Model Answer</Label>
              <BulletList items={result.correct_solution} />
            </div>
          )}

          {/* Try again */}
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => { setResult(null); setDraft('') }}
            >
              Try Again
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
