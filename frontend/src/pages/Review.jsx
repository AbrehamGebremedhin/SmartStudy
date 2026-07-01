import { useEffect, useState } from 'react'
import Icon from '../components/ui/Icon'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import LoadingState from '../components/ui/LoadingState'
import { awardXP } from '../lib/gamification'
import { getMistakes, resolveMistake } from '../services/mistakes.service'

// Drill wrong-answered questions until you get them right; a correct answer
// removes the card from the bank. Cards come pre-normalized from the backend
// (options: [{ letter, text, image_url }]), so one render path covers both
// MCQ- and exam-sourced mistakes.
export default function Review() {
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [state, setState] = useState({}) // index -> { selected, revealed, resolved }

  function load() {
    setLoading(true)
    setError(null)
    setState({})
    getMistakes()
      .then(list => setCards(list.map(m => m.question)))
      .catch(setError)
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  function pick(i, letter) {
    if (state[i]?.revealed) return
    const q = cards[i]
    const correct = letter === q.correct_answer
    setState(s => ({ ...s, [i]: { selected: letter, revealed: true, resolved: correct } }))
    if (correct) {
      awardXP('mcq_correct', { subject: null })
      resolveMistake(q.question).catch(() => {})
    }
  }

  const remaining = cards.length - Object.values(state).filter(s => s?.resolved).length

  if (loading) return <PageWrap><LoadingState title="Loading your mistakes…" /></PageWrap>
  if (error) return <PageWrap><ErrorState title="Couldn't load mistakes" error={error} onRetry={load} /></PageWrap>
  if (cards.length === 0) return (
    <PageWrap>
      <EmptyState icon="target" title="No Mistakes to Review"
                  description="Questions you miss in MCQ quizzes and mock exams land here so you can drill them until they stick." />
    </PageWrap>
  )

  return (
    <PageWrap>
      <div className="review-filter">
        <span className="rf-chip active">{remaining} to master</span>
      </div>
      {cards.map((q, i) => {
        const st = state[i] || {}
        const correct = q.correct_answer
        return (
          <div key={i} className={`mcq-card anim ${st.resolved ? 'row-ok' : ''}`}>
            <div className="mcq-top">
              <span className="mcq-topic">{q.topic ?? `Question ${i + 1}`}</span>
              {st.revealed && (
                <span className={`q-mark ${st.resolved ? 'ok' : 'no'}`}>{st.resolved ? '✓' : '✗'}</span>
              )}
            </div>
            <div className="mcq-body">
              {q.passage && <div className="mcq-passage">{q.passage}</div>}
              <div className="mcq-q">{i + 1}. {q.question}</div>
              {q.question_image_url && (
                <img className="mcq-img" src={q.question_image_url} alt="question diagram" loading="lazy" />
              )}
              <div className="mcq-opts">
                {(q.options ?? []).map(opt => {
                  const isCorrect = opt.letter === correct
                  const isSelected = opt.letter === st.selected
                  let cls = 'mcq-opt'
                  if (st.revealed && isCorrect) cls += ' ok'
                  else if (st.revealed && isSelected && !isCorrect) cls += ' no'
                  return (
                    <button key={opt.letter} className={cls} onClick={() => pick(i, opt.letter)}>
                      <span className="o-let">{opt.letter}</span>
                      {opt.image_url
                        ? <img className="opt-img" src={opt.image_url} alt={`option ${opt.letter}`} loading="lazy" />
                        : <span>{opt.text}</span>}
                    </button>
                  )
                })}
              </div>
              {st.revealed && (
                <div className="mcq-expl">
                  <strong>{st.resolved ? '✓ Correct — removed from your bank' : `✗ The answer is ${correct}`}</strong>
                  {(q.correct_explanations ?? []).map((e, j) => (
                    <div key={j} style={{ marginTop: 3 }}>• {e}</div>
                  ))}
                  {!st.resolved && q.incorrect_explanations?.[st.selected] && (
                    <div style={{ marginTop: 8, color: 'var(--vermillion)' }}>
                      Why your choice is wrong: {q.incorrect_explanations[st.selected]}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </PageWrap>
  )
}

function PageWrap({ children }) {
  return (
    <>
      <div className="pg-top">
        <h2><Icon name="target" size={20} /> Review Mistakes</h2>
        <p>Drill the questions you missed until they stick</p>
      </div>
      <div className="pg-body">{children}</div>
    </>
  )
}
