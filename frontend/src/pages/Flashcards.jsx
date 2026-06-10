import { useState, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import ConfigPanel from '../components/ui/ConfigPanel'
import EmptyState from '../components/ui/EmptyState'
import Icon from '../components/ui/Icon'
import Confetti from '../components/ui/Confetti'
import LoadingState from '../components/ui/LoadingState'
import { generateFlashcards } from '../services/flashcards.service'
import { saveGeneration, loadGeneration, updateGeneration } from '../lib/genStorage'
import { awardXP, recordLastGen } from '../lib/gamification'

const DEFAULT_CONFIG = {
  subject: 'biology',
  grade: 12,
  unit: '1',
  difficulty: 'medium',
  numItems: 10,
  topic: null,
}

function firstUnrated(cards, ratings) {
  for (let i = 0; i < cards.length; i++) {
    if (!ratings[i]) return i
  }
  return null
}

export default function Flashcards() {
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
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [idx, setIdx] = useState(0)
  const [flipped, setFlipped] = useState(false)
  const [ratings, setRatings] = useState({}) // { idx: 'known' | 'learning' }
  const [reviewQueue, setReviewQueue] = useState(null) // indices being re-reviewed
  const [done, setDone] = useState(false)
  const [xpEarned, setXpEarned] = useState(0)
  const [isReplay, setIsReplay] = useState(false) // reopened completed deck — no re-awards

  useEffect(() => {
    if (!genId) return
    const saved = loadGeneration(genId)
    if (saved) {
      const savedCards = saved.cards ?? []
      const savedRatings = saved.ratings ?? {}
      setCards(savedCards)
      setRatings(savedRatings)
      setIsReplay(Boolean(saved.completedAt))
      setDone(Boolean(saved.completedAt))
      setXpEarned(saved.xpEarned ?? 0)
      setReviewQueue(null)
      setFlipped(false)
      setIdx(saved.completedAt ? 0 : (firstUnrated(savedCards, savedRatings) ?? 0))
      if (saved.config) setConfig(saved.config)
    }
  }, [genId])

  function resetDeckState() {
    setCards([])
    setIdx(0)
    setFlipped(false)
    setRatings({})
    setReviewQueue(null)
    setDone(false)
    setXpEarned(0)
    setIsReplay(false)
  }

  function handleChange(key, value) {
    setConfig(prev => ({ ...prev, [key]: value }))
    resetDeckState()
    setSearchParams({})
  }

  async function handleGenerate() {
    setLoading(true)
    setError(null)
    resetDeckState()
    try {
      const res = await generateFlashcards({
        subject: config.subject,
        grade: config.grade,
        unit: config.unit,
        topic: config.topic || null,
        num_cards: config.numItems,
        difficulty: config.difficulty,
        note_id: fromNote || null,
        chat_session_id: fromChat || null,
      })
      const c = res.flashcards ?? []
      setCards(c)
      saveGeneration(res.generation_id, { type: 'flashcard', cards: c, config, ratings: {} })
      setSearchParams({ gen: res.generation_id })
      awardXP('gen_flashcards', { subject: config.subject })
      recordLastGen({ type: 'flashcard', genId: res.generation_id, subject: config.subject, grade: config.grade, unit: config.unit, topic: config.topic })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  function advanceTo(next) {
    setFlipped(false)
    setTimeout(() => setIdx(next), 180)
  }

  function rate(value) {
    const i = idx
    if (!cards[i] || done) return
    const inReview = reviewQueue != null
    const isFirstRating = !inReview && !isReplay && !ratings[i]
    const newRatings = { ...ratings, [i]: value }
    setRatings(newRatings)

    let gainedNow = 0
    if (isFirstRating) {
      gainedNow += awardXP('card_rated', { known: value === 'known', subject: config.subject }).gained
    }

    const saved = genId ? loadGeneration(genId) : null
    let finished = false
    if (inReview) {
      const nextPos = reviewQueue.indexOf(i) + 1
      if (nextPos >= reviewQueue.length || nextPos === 0) finished = true
      else advanceTo(reviewQueue[nextPos])
    } else {
      const next = firstUnrated(cards, newRatings)
      if (next == null) finished = true
      else advanceTo(next)
    }

    if (finished) {
      setDone(true)
      setReviewQueue(null)
      setFlipped(false)
      const allKnown = cards.every((_, ci) => newRatings[ci] === 'known')
      if (!inReview && !isReplay && !saved?.xpAwarded) {
        gainedNow += awardXP('deck_complete', { allKnown, size: cards.length, subject: config.subject }).gained
      }
    }

    if (gainedNow > 0) setXpEarned(x => x + gainedNow)

    if (genId) {
      const updates = { ratings: newRatings }
      if (gainedNow > 0) updates.xpEarned = (saved?.xpEarned ?? 0) + gainedNow
      if (finished) {
        updates.completedAt = saved?.completedAt ?? new Date().toISOString()
        if (!inReview && !isReplay) updates.xpAwarded = true
      }
      updateGeneration(genId, updates)
    }
  }

  function reviewMissed() {
    const missed = cards.map((_, i) => i).filter(i => ratings[i] !== 'known')
    if (missed.length === 0) return
    setReviewQueue(missed)
    setDone(false)
    setFlipped(false)
    setIdx(missed[0])
  }

  function next() {
    setFlipped(false)
    setTimeout(() => setIdx(i => (i + 1) % cards.length), 180)
  }

  function prev() {
    setFlipped(false)
    setTimeout(() => setIdx(i => (i - 1 + cards.length) % cards.length), 180)
  }

  const card = cards[idx]
  const inReview = reviewQueue != null

  return (
    <>
      <div className="pg-top">
        <h2>Flashcards</h2>
        <p>Flip each card, then rate how well you knew it</p>
      </div>
      <div className="pg-body">
        {(fromNote || fromChat) && !genId && (
          <div className="context-banner">
            <Icon name={fromNote ? 'file-text' : 'chat'} size={15} />
            {fromNote ? 'Generating from your note — topic and subject are pre-filled.' : 'Generating from your chat session.'}
          </div>
        )}

        {genId && cards.length > 0 ? (
          <div className="back-row">
            <button className="btn btn-ghost btn-sm" onClick={() => {
              setSearchParams({})
              resetDeckState()
            }}>
              ← New Set
            </button>
          </div>
        ) : (
          <ConfigPanel
            config={config}
            onChange={handleChange}
            onGenerate={handleGenerate}
            loading={loading}
            numItemsLabel="Cards"
            generateLabel="Generate Flashcards"
            showTopic={false}
          />
        )}

        {error && (
          <div className="form-error">{error}</div>
        )}

        {loading && (
          <LoadingState
            title="Generating flashcards…"
            sub="Claude is crafting cards from your curriculum — this takes 5–10 seconds."
          />
        )}

        {!loading && cards.length === 0 && !error && (
          <EmptyState
            icon="cards"
            title="Create Flashcards"
            description="Pick a subject, then generate cards to flip through and test yourself."
          />
        )}

        {cards.length > 0 && config.topic && !done && (
          <div className="topic-link-row">
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => navigate(`/notes?subject=${config.subject}&grade=${config.grade}&unit=${config.unit}&topic=${encodeURIComponent(config.topic)}`)}
            >
              Generate Notes on "{config.topic}" →
            </button>
          </div>
        )}

        {done && cards.length > 0 && (
          <FlashcardResults
            cards={cards}
            ratings={ratings}
            xpEarned={xpEarned}
            isReplay={isReplay}
            onReviewMissed={reviewMissed}
            onNewSet={() => {
              setSearchParams({})
              resetDeckState()
            }}
            onPracticeMCQs={() =>
              navigate(`/mcq?subject=${config.subject}&grade=${config.grade}&unit=${config.unit}${config.topic ? `&topic=${encodeURIComponent(config.topic)}` : ''}`)
            }
          />
        )}

        {!done && card && (
          <>
            {inReview && (
              <div className="fc-review-banner">
                <Icon name="retry" size={14} />
                Reviewing {reviewQueue.length} card{reviewQueue.length === 1 ? '' : 's'} you’re still learning
              </div>
            )}

            <div className="fc-dots">
              {cards.map((_, i) => (
                <button
                  key={i}
                  className={`fc-dot${ratings[i] === 'known' ? ' k' : ratings[i] === 'learning' ? ' l' : ''}${i === idx ? ' cur' : ''}`}
                  onClick={inReview ? undefined : () => advanceTo(i)}
                  disabled={inReview}
                  aria-label={`Card ${i + 1}`}
                />
              ))}
            </div>

            <div className="fc-wrap anim">
              <div
                className={`fc-card${flipped ? ' flip' : ''}`}
                onClick={() => setFlipped(f => !f)}
              >
                <div className="fc-face fc-front">
                  <div className="fc-tag">Question</div>
                  <div className="fc-txt">{card.front}</div>
                </div>
                <div className="fc-face fc-back">
                  <div className="fc-tag">Answer</div>
                  <div className="fc-txt">{card.back}</div>
                </div>
              </div>
            </div>

            {flipped ? (
              <div className="fc-rate anim">
                <button className="fc-rate-btn fc-rate-learning" onClick={() => rate('learning')}>
                  <Icon name="retry" size={16} /> Still learning
                </button>
                <button className="fc-rate-btn fc-rate-known" onClick={() => rate('known')}>
                  <Icon name="check" size={16} /> Knew it
                </button>
              </div>
            ) : (
              <div className="fc-hint">Tap the card to reveal the answer, then rate yourself</div>
            )}

            <div className="fc-topic">{card.topic}</div>
            {!inReview && (
              <div className="fc-nav">
                <button className="btn btn-ghost btn-sm" onClick={prev}>← Prev</button>
                <span className="fc-ct">{idx + 1} / {cards.length}</span>
                <button className="btn btn-ghost btn-sm" onClick={next}>Next →</button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  )
}

function FlashcardResults({ cards, ratings, xpEarned, isReplay, onReviewMissed, onNewSet, onPracticeMCQs }) {
  const known = cards.filter((_, i) => ratings[i] === 'known').length
  const learning = cards.length - known
  const allKnown = learning === 0

  return (
    <div className="fc-done anim">
      <div className="fc-done-head">
        {allKnown && <Confetti />}
        <div className="results-title">Deck Complete</div>
        <div className="fc-done-counts">
          <div className="fc-done-count">
            <span className="fc-done-num k">{known}</span>
            <span className="fc-done-lbl">Knew it</span>
          </div>
          <div className="fc-done-count">
            <span className="fc-done-num l">{learning}</span>
            <span className="fc-done-lbl">Still learning</span>
          </div>
        </div>
        <div className="res-msg">
          {allKnown
            ? 'ጎበዝ! Every card mastered.'
            : `${learning} card${learning === 1 ? '' : 's'} to revisit — repetition builds mastery.`}
        </div>
        {xpEarned > 0 && !isReplay && (
          <div className="res-xp"><Icon name="star" size={14} /> +{xpEarned} XP earned</div>
        )}
      </div>
      <div className="fc-done-actions">
        {learning > 0 && (
          <button className="btn btn-ochre" onClick={onReviewMissed}>
            Review {learning} missed
          </button>
        )}
        <button className="btn btn-ghost" onClick={onNewSet}>New Set</button>
        <button className="btn btn-indigo" onClick={onPracticeMCQs}>Practice MCQs</button>
      </div>
    </div>
  )
}
