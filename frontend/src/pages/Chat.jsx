import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ALL_SUBJECTS } from '../lib/curriculum'
import {
  listSessions,
  getSession,
  createSession,
  sendMessage,
  updateSessionTitle,
} from '../services/chat.service'

export default function Chat() {
  const { sessionId } = useParams()
  const navigate = useNavigate()

  const [sessions, setSessions] = useState([])
  const [activeSession, setActiveSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState(null)
  const [showNewModal, setShowNewModal] = useState(false)

  const endRef = useRef(null)

  useEffect(() => {
    listSessions().then(setSessions).catch(console.error)
  }, [])

  useEffect(() => {
    if (sessionId) {
      getSession(sessionId).then(s => {
        setActiveSession(s)
        setMessages(s.messages ?? [])
      }).catch(console.error)
    } else if (sessions.length > 0) {
      navigate(`/chat/${sessions[0].id}`, { replace: true })
    }
  }, [sessionId, sessions, navigate])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend() {
    if (!input.trim() || !activeSession || sending) return
    const question = input.trim()
    setInput('')
    setMessages(m => [...m, { role: 'user', content: question, id: Date.now() }])
    setSending(true)
    setError(null)
    try {
      const res = await sendMessage(activeSession.id, question)
      const answerText = res.current_response?.answer ?? res.current_response?.content ?? ''
      setMessages(m => [...m, { role: 'assistant', content: answerText, id: Date.now() + 1 }])

      if (res.title && res.title !== activeSession.title) {
        setActiveSession(s => ({ ...s, title: res.title }))
        setSessions(ss => ss.map(s => s.id === activeSession.id ? { ...s, title: res.title } : s))
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setSending(false)
    }
  }

  async function handleNewSession(subject, grade) {
    try {
      const session = await createSession({ subject, grade })
      setSessions(ss => [session, ...ss])
      setShowNewModal(false)
      navigate(`/chat/${session.id}`)
    } catch (e) {
      setError(e.message)
    }
  }

  const userInitial = activeSession?.subject?.[0]?.toUpperCase() ?? 'U'

  return (
    <>
      <div className="chat-tabs">
        {sessions.map(s => (
          <button
            key={s.id}
            className={`ct-btn${activeSession?.id === s.id ? ' on' : ''}`}
            onClick={() => navigate(`/chat/${s.id}`)}
          >
            {s.title}
          </button>
        ))}
        <button
          className="ct-btn"
          style={{ color: 'var(--ochre)' }}
          onClick={() => setShowNewModal(true)}
        >
          + New
        </button>
      </div>

      {showNewModal && (
        <NewSessionModal
          onConfirm={handleNewSession}
          onCancel={() => setShowNewModal(false)}
        />
      )}

      <div className="chat-wrap">
        {messages.length === 0 && !activeSession && (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--ink-3)', flexDirection: 'column', gap: 12 }}>
            <div style={{ fontSize: 36, opacity: 0.3 }}>◉</div>
            <div style={{ fontSize: 14 }}>Start a new session to ask your tutor</div>
          </div>
        )}

        <div className="chat-msgs">
          {messages.map((m, i) => (
            <div key={m.id ?? i} className={`c-msg ${m.role}`}>
              <div className="c-av">
                {m.role === 'user' ? userInitial : 'S'}
              </div>
              <div className="c-bub">{m.content}</div>
            </div>
          ))}
          {sending && (
            <div className="c-msg assistant">
              <div className="c-av">S</div>
              <div className="c-bub" style={{ color: 'var(--ink-3)' }}>
                <span className="pulse">Thinking…</span>
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        {error && (
          <div style={{ padding: '8px 18px', color: 'var(--vermillion)', fontSize: 13 }}>
            {error}
          </div>
        )}

        <div className="chat-bar">
          <div className="cb-wrap">
            <textarea
              className="cb-in"
              placeholder={activeSession ? 'Ask anything about your subjects…' : 'Create a session first'}
              value={input}
              disabled={!activeSession || sending}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              rows={1}
            />
            <button className="cb-send" onClick={handleSend} disabled={!activeSession || sending}>
              ↑
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

function NewSessionModal({ onConfirm, onCancel }) {
  const [subject, setSubject] = useState('biology')
  const [grade, setGrade] = useState(12)

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(30,22,16,0.5)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 200, padding: 16,
    }}>
      <div style={{
        background: 'var(--card)', borderRadius: 'var(--r-xl)',
        padding: 32, width: '100%', maxWidth: 380,
        boxShadow: 'var(--sh-3)',
      }}>
        <h3 style={{ fontFamily: 'var(--f-display)', fontSize: 20, marginBottom: 20 }}>
          New Chat Session
        </h3>
        <div className="cfg-f" style={{ marginBottom: 14 }}>
          <label className="cfg-lbl">Subject</label>
          <select value={subject} onChange={e => setSubject(e.target.value)}>
            {ALL_SUBJECTS.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
        <div className="cfg-f" style={{ marginBottom: 24 }}>
          <label className="cfg-lbl">Grade</label>
          <select value={grade} onChange={e => setGrade(Number(e.target.value))}>
            {[9, 10, 11, 12].map(g => <option key={g} value={g}>Grade {g}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onCancel}>Cancel</button>
          <button className="btn btn-ochre" style={{ flex: 1 }} onClick={() => onConfirm(subject, grade)}>
            Start Chat
          </button>
        </div>
      </div>
    </div>
  )
}
