import { useState } from 'react'
import ConfigPanel from '../components/ui/ConfigPanel'
import DifficultyTag from '../components/ui/DifficultyTag'
import EmptyState from '../components/ui/EmptyState'
import { generateMCQ } from '../services/mcq.service'

const DEFAULT_CONFIG = {
  subject: 'biology',
  grade: 12,
  unit: '1',
  difficulty: 'medium',
  numItems: 5,
}

export default function MCQ() {
  const [config, setConfig] = useState(DEFAULT_CONFIG)
  const [questions, setQuestions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState({})
  const [revealed, setRevealed] = useState({})

  function handleChange(key, value) {
    setConfig(prev => ({ ...prev, [key]: value }))
    setQuestions([])
    setSelected({})
    setRevealed({})
  }

  async function handleGenerate() {
    setLoading(true)
    setError(null)
    setSelected({})
    setRevealed({})
    try {
      const res = await generateMCQ({
        subject: config.subject,
        grade: config.grade,
        unit: config.unit,
        num_questions: config.numItems,
        difficulty: config.difficulty,
      })
      setQuestions(res.questions ?? [])
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function pick(qi, letter) {
    if (revealed[qi]) return
    setSelected(p => ({ ...p, [qi]: letter }))
    setRevealed(p => ({ ...p, [qi]: true }))
  }

  return (
    <>
      <div className="pg-top">
        <h2>Practice MCQs</h2>
        <p>Curriculum-based questions with explanations</p>
      </div>
      <div className="pg-body">
        <ConfigPanel
          config={config}
          onChange={handleChange}
          onGenerate={handleGenerate}
          loading={loading}
          numItemsLabel="Questions"
          generateLabel="Generate Questions"
          excludeSubjects={['sat']}
        />

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
                    let cls = 'mcq-opt'
                    if (isRevealed) {
                      if (letter === correct) cls += ' ok'
                      else if (letter === userAnswer) cls += ' no'
                    }
                    return (
                      <button key={oi} className={cls} onClick={() => pick(qi, letter)}>
                        <span className="o-let">{letter}</span>
                        <span>{opt.slice(3)}</span>
                      </button>
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
