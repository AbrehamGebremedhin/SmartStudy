import { useState, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import ConfigPanel from '../components/ui/ConfigPanel'
import EmptyState from '../components/ui/EmptyState'
import { generateFlashcards } from '../services/flashcards.service'
import { saveGeneration, loadGeneration } from '../lib/genStorage'

const DEFAULT_CONFIG = {
  subject: 'biology',
  grade: 12,
  unit: '1',
  difficulty: 'medium',
  numItems: 10,
  topic: null,
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
    topic: searchParams.get('topic') || DEFAULT_CONFIG.topic,
  }))
  const [cards, setCards] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [idx, setIdx] = useState(0)
  const [flipped, setFlipped] = useState(false)

  useEffect(() => {
    if (!genId) return
    const saved = loadGeneration(genId)
    if (saved) {
      setCards(saved.cards ?? [])
      if (saved.config) setConfig(saved.config)
    }
  }, [genId])

  function handleChange(key, value) {
    setConfig(prev => ({ ...prev, [key]: value }))
    setCards([])
    setIdx(0)
    setFlipped(false)
    setSearchParams({})
  }

  async function handleGenerate() {
    setLoading(true)
    setError(null)
    setIdx(0)
    setFlipped(false)
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
      saveGeneration(res.generation_id, { type: 'flashcard', cards: c, config })
      setSearchParams({ gen: res.generation_id })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
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

  return (
    <>
      <div className="pg-top">
        <h2>Flashcards</h2>
        <p>Tap to flip — reveal the answer</p>
      </div>
      <div className="pg-body">
        {(fromNote || fromChat) && !genId && (
          <div style={{ padding: '10px 14px', background: 'var(--ochre-glow)', borderRadius: 'var(--r-s)', marginBottom: 12, fontSize: 13, color: 'var(--ochre-deep)', fontWeight: 600 }}>
            {fromNote ? '📄 Generating from your note — topic and subject are pre-filled.' : '💬 Generating from your chat session.'}
          </div>
        )}

        {genId && cards.length > 0 ? (
          <div style={{ marginBottom: 16 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => {
              setSearchParams({})
              setCards([])
              setIdx(0)
              setFlipped(false)
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
            showTopic={!fromNote && !fromChat}
          />
        )}

        {error && (
          <div style={{ color: 'var(--vermillion)', marginBottom: 16, fontSize: 14 }}>
            {error}
          </div>
        )}

        {!loading && cards.length === 0 && !error && (
          <EmptyState
            icon="▣"
            title="Create Flashcards"
            description="Pick a subject, then generate cards to flip through and test yourself."
          />
        )}

        {cards.length > 0 && config.topic && (
          <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'flex-end' }}>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => navigate(`/notes?subject=${config.subject}&grade=${config.grade}&topic=${encodeURIComponent(config.topic)}`)}
            >
              Generate Notes on "{config.topic}" →
            </button>
          </div>
        )}

        {card && (
          <>
            <div className="fc-wrap anim">
              <div
                className={`fc-card${flipped ? ' flip' : ''}`}
                onClick={() => setFlipped(f => !f)}
                style={{ minHeight: 240 }}
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

            <div className="fc-topic">{card.topic}</div>
            <div className="fc-nav">
              <button className="btn btn-ghost btn-sm" onClick={prev}>← Prev</button>
              <span className="fc-ct">{idx + 1} / {cards.length}</span>
              <button className="btn btn-ghost btn-sm" onClick={next}>Next →</button>
            </div>
          </>
        )}
      </div>
    </>
  )
}
