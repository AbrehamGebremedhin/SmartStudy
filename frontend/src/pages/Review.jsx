import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Icon from '../components/ui/Icon'
import EmptyState from '../components/ui/EmptyState'
import ErrorState from '../components/ui/ErrorState'
import LoadingState from '../components/ui/LoadingState'
import BookmarkButton from '../components/ui/BookmarkButton'
import { awardXP } from '../lib/gamification'
import { getMistakes, resolveMistake } from '../services/mistakes.service'
import { getBookmarks, removeBookmark } from '../services/bookmarks.service'
import { askAboutQuestion } from '../lib/askTutor'

const TABS = [
  { key: 'mistakes', label: 'Mistakes', icon: 'target' },
  { key: 'saved', label: 'Saved', icon: 'bookmark' },
]

export default function Review() {
  const [tab, setTab] = useState('mistakes')
  return (
    <>
      <div className="pg-top">
        <h2><Icon name="target" size={20} /> Review</h2>
        <p>Drill your mistakes, or revisit questions you saved</p>
      </div>
      <div className="pg-body">
        <div className="filter-row">
          {TABS.map(t => (
            <button key={t.key} className={`btn btn-sm ${tab === t.key ? 'btn-ochre' : 'btn-ghost'}`}
                    onClick={() => setTab(t.key)}>
              <Icon name={t.icon} size={14} /> {t.label}
            </button>
          ))}
        </div>
        {tab === 'mistakes' ? <MistakesTab /> : <SavedTab />}
      </div>
    </>
  )
}

// Drill wrong-answered questions until you get them right; a correct answer
// removes the card from the bank. Cards come pre-normalized from the backend
// (options: [{ letter, text, image_url }]), so one render path covers both
// MCQ- and exam-sourced mistakes.
function MistakesTab() {
  const navigate = useNavigate()
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [state, setState] = useState({}) // index -> { selected, revealed, resolved }

  function load() {
    setLoading(true)
    setError(null)
    setState({})
    getMistakes()
      .then(list => setCards(list.map(m => ({ ...m.question, __subject: m.subject }))))
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

  if (loading) return <LoadingState title="Loading your mistakes…" />
  if (error) return <ErrorState title="Couldn't load mistakes" error={error} onRetry={load} />
  if (cards.length === 0) return (
    <EmptyState icon="target" title="No Mistakes to Review"
                description="Questions you miss in MCQ quizzes and mock exams land here so you can drill them until they stick." />
  )

  return (
    <>
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
                  <button className="btn btn-ghost btn-sm" style={{ marginTop: 10 }}
                          onClick={() => askAboutQuestion(navigate, q.__subject, q)}>
                    <Icon name="tutor" size={14} /> Ask tutor about this
                  </button>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </>
  )
}

// Questions the user starred to revisit — stays until explicitly unsaved
// (unlike mistakes, answering correctly doesn't remove it).
function SavedTab() {
  const navigate = useNavigate()
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [state, setState] = useState({}) // index -> { selected, revealed }
  const [removed, setRemoved] = useState({}) // index -> true

  function load() {
    setLoading(true)
    setError(null)
    setState({})
    setRemoved({})
    getBookmarks()
      .then(list => setCards(list.map(b => ({ ...b.question, __subject: b.subject }))))
      .catch(setError)
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  function pick(i, letter) {
    if (state[i]?.revealed) return
    setState(s => ({ ...s, [i]: { selected: letter, revealed: true } }))
  }

  function unsave(i) {
    setRemoved(r => ({ ...r, [i]: true }))
    removeBookmark(cards[i].question)
  }

  const visible = cards.map((q, i) => ({ q, i })).filter(({ i }) => !removed[i])

  if (loading) return <LoadingState title="Loading your saved questions…" />
  if (error) return <ErrorState title="Couldn't load saved questions" error={error} onRetry={load} />
  if (visible.length === 0) return (
    <EmptyState icon="bookmark" title="No Saved Questions"
                description="Tap the bookmark icon on any MCQ or mock exam question to save it here for later." />
  )

  return (
    <>
      {visible.map(({ q, i }) => {
        const st = state[i] || {}
        const correct = q.correct_answer
        return (
          <div key={i} className="mcq-card anim">
            <div className="mcq-top">
              <span className="mcq-topic">{q.topic ?? `Question ${i + 1}`}</span>
              <div className="mcq-top-actions">
                {st.revealed && (
                  <span className={`q-mark ${st.selected === correct ? 'ok' : 'no'}`}>
                    {st.selected === correct ? '✓' : '✗'}
                  </span>
                )}
                <BookmarkButton active onToggle={() => unsave(i)} />
              </div>
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
                  <strong>{st.selected === correct ? '✓ Correct!' : `✗ The answer is ${correct}`}</strong>
                  {(q.correct_explanations ?? []).map((e, j) => (
                    <div key={j} style={{ marginTop: 3 }}>• {e}</div>
                  ))}
                  {st.selected !== correct && q.incorrect_explanations?.[st.selected] && (
                    <div style={{ marginTop: 8, color: 'var(--vermillion)' }}>
                      Why your choice is wrong: {q.incorrect_explanations[st.selected]}
                    </div>
                  )}
                  <button className="btn btn-ghost btn-sm" style={{ marginTop: 10 }}
                          onClick={() => askAboutQuestion(navigate, q.__subject, q)}>
                    <Icon name="tutor" size={14} /> Ask tutor about this
                  </button>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </>
  )
}
