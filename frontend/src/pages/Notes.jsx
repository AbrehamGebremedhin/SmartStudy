import { useState } from 'react'
import ConfigPanel from '../components/ui/ConfigPanel'
import EmptyState from '../components/ui/EmptyState'
import { generateNotes } from '../services/notes.service'

const DEFAULT_CONFIG = {
  subject: 'biology',
  grade: 12,
  unit: '1',
  difficulty: 'medium',
  topic: '',
}

export default function Notes() {
  const [config, setConfig] = useState(DEFAULT_CONFIG)
  const [notes, setNotes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

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
      })
      setNotes(res.notes ?? null)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div className="pg-top">
        <h2>Study Notes</h2>
        <p>Comprehensive notes with worked examples</p>
      </div>
      <div className="pg-body">
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

        {notes && <NotesContent notes={notes} />}
      </div>
    </>
  )
}

function NotesContent({ notes }) {
  const sections = notes.sections ?? []

  return (
    <div className="notes-w anim">
      {notes.title && (
        <div className="n-sec">
          <h3 className="n-sec-t">{notes.title}</h3>
          {notes.introduction && <div className="n-text">{notes.introduction}</div>}
        </div>
      )}

      {sections.map((sec, i) => (
        <div key={i} className="n-sec">
          <h3 className="n-sec-t">{sec.title ?? sec.heading}</h3>
          {sec.content && <div className="n-text">{sec.content}</div>}
          {(sec.concepts ?? sec.key_concepts ?? []).map((c, j) => (
            <div key={j} className="n-card">
              <h4>{c.term ?? c.title ?? c.name}</h4>
              <div className="n-text">{c.definition ?? c.description ?? c.content}</div>
            </div>
          ))}
          {(sec.examples ?? []).map((ex, j) => (
            <div key={j} className="n-card tibeb-left">
              <div className="n-text" style={{ fontWeight: 600, color: 'var(--ink)' }}>
                Example {j + 1}
              </div>
              <div className="n-text">{typeof ex === 'string' ? ex : ex.text ?? ex.content}</div>
            </div>
          ))}
        </div>
      ))}

      {(notes.review_questions ?? notes.questions ?? []).length > 0 && (
        <div className="n-sec">
          <h3 className="n-sec-t">Review Questions</h3>
          {(notes.review_questions ?? notes.questions).map((q, i) => (
            <div key={i} className="n-card tibeb-left">
              <div className="n-text" style={{ fontWeight: 600, color: 'var(--ink)' }}>
                {i + 1}. {typeof q === 'string' ? q : q.question ?? q.text}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
