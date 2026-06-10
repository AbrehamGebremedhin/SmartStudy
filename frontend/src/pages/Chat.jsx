import { useState, useEffect, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ALL_SUBJECTS } from '../lib/curriculum'
import Icon from '../components/ui/Icon'
import { awardXP } from '../lib/gamification'
import {
  listSessions,
  getSession,
  createSession,
  sendMessage,
  updateSessionTitle,
  getSessionContext,
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
  const [contextGrade, setContextGrade] = useState(null)
  const [contextUnit, setContextUnit] = useState(null)

  const endRef = useRef(null)

  useEffect(() => {
    listSessions().then(setSessions).catch(console.error)
  }, [])

  useEffect(() => {
    if (sessionId) {
      // Restore from sessionStorage immediately if available
      let hasCached = false
      try {
        const saved = sessionStorage.getItem(`ctx_${sessionId}`)
        if (saved) {
          const { grade, unit } = JSON.parse(saved)
          setContextGrade(grade ?? null)
          setContextUnit(unit ?? null)
          hasCached = true
        }
      } catch { /* ignore */ }
      if (!hasCached) {
        setContextGrade(null)
        setContextUnit(null)
      }

      getSession(sessionId).then(s => {
        setActiveSession(s)
        setMessages(s.messages ?? [])
        // If no cached context and session has messages, fetch grade/unit from vector DB
        if (!hasCached && (s.messages?.length ?? 0) > 0) {
          getSessionContext(sessionId).then(ctx => {
            if (ctx.grade) setContextGrade(ctx.grade)
            if (ctx.unit) setContextUnit(ctx.unit)
            if (ctx.grade || ctx.unit) {
              sessionStorage.setItem(`ctx_${sessionId}`, JSON.stringify({ grade: ctx.grade, unit: ctx.unit }))
            }
          }).catch(() => {})
        }
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
      awardXP('chat_question', { subject: activeSession.subject })

      if (res.title && res.title !== activeSession.title) {
        setActiveSession(s => ({ ...s, title: res.title }))
        setSessions(ss => ss.map(s => s.id === activeSession.id ? { ...s, title: res.title } : s))
      }
      if (res.context_grade || res.context_unit) {
        const grade = res.context_grade ?? contextGrade
        const unit = res.context_unit ?? contextUnit
        if (res.context_grade) setContextGrade(res.context_grade)
        if (res.context_unit) setContextUnit(res.context_unit)
        sessionStorage.setItem(`ctx_${activeSession.id}`, JSON.stringify({ grade, unit }))
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setSending(false)
    }
  }

  async function handleNewSession(subject) {
    try {
      const session = await createSession({ subject })
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

      {activeSession && messages.length > 0 && (
        <div className="chat-context-bar">
          <span className="chat-context-label">Study tools:</span>
          <button
            className="btn btn-ghost btn-sm"
            style={{ fontSize: 12 }}
            onClick={() => { const g = contextGrade || activeSession.grade; const u = contextUnit; navigate(`/notes?from_chat=${activeSession.id}&subject=${activeSession.subject}${g ? `&grade=${g}` : ''}${u ? `&unit=${u}` : ''}&topic=${encodeURIComponent(activeSession.title)}`) }}
          >
            Generate Notes
          </button>
          <button
            className="btn btn-ghost btn-sm"
            style={{ fontSize: 12 }}
            onClick={() => { const g = contextGrade || activeSession.grade; const u = contextUnit; navigate(`/mcq?from_chat=${activeSession.id}&subject=${activeSession.subject}${g ? `&grade=${g}` : ''}${u ? `&unit=${u}` : ''}`) }}
          >
            Practice MCQs
          </button>
          <button
            className="btn btn-ghost btn-sm"
            style={{ fontSize: 12 }}
            onClick={() => { const g = contextGrade || activeSession.grade; const u = contextUnit; navigate(`/flashcards?from_chat=${activeSession.id}&subject=${activeSession.subject}${g ? `&grade=${g}` : ''}${u ? `&unit=${u}` : ''}`) }}
          >
            Create Flashcards
          </button>
        </div>
      )}

      <div className="chat-wrap">
        {messages.length === 0 && !activeSession && (
          <div
            onClick={() => setShowNewModal(true)}
            style={{
              flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexDirection: 'column', gap: 14, cursor: 'pointer',
            }}
          >
            <div className="chat-empty-ico"><Icon name="tutor" size={36} stroke={1.5} /></div>
            <div style={{ fontSize: 14, color: 'var(--ink-3)' }}>No sessions yet</div>
            <button className="btn btn-ochre btn-sm" onClick={e => { e.stopPropagation(); setShowNewModal(true) }}>
              + New Session
            </button>
          </div>
        )}

        <div className="chat-msgs">
          {messages.map((m, i) => (
            <div key={m.id ?? i} className={`c-msg ${m.role}`}>
              <div className="c-av">
                {m.role === 'user' ? userInitial : 'S'}
              </div>
              <div className="c-bub">
                <MessageContent text={m.content} />
              </div>
            </div>
          ))}
          {sending && (
            <div className="c-msg assistant">
              <div className="c-av">S</div>
              <div className="c-bub">
                <span className="typing" aria-label="Tutor is thinking"><i /><i /><i /></span>
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
          <div
            className="cb-wrap"
            onClick={!activeSession ? () => setShowNewModal(true) : undefined}
            style={!activeSession ? { cursor: 'pointer' } : undefined}
          >
            <textarea
              className="cb-in"
              placeholder={activeSession ? 'Ask anything about your subjects…' : 'Click to start a new session…'}
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
              style={!activeSession ? { pointerEvents: 'none' } : undefined}
            />
            <button
              className="cb-send"
              onClick={!activeSession ? () => setShowNewModal(true) : handleSend}
              disabled={sending}
              aria-label="Send message"
            >
              <Icon name="send" size={19} />
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

function InlineText({ text }) {
  const re = /(`[^`\n]+`|\*\*[^*\n]+\*\*|[A-Za-z0-9]+\^[A-Za-z0-9]+)/g
  const parts = []
  let last = 0
  let m
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index))
    const tok = m[0]
    if (tok.startsWith('`')) {
      parts.push(<code key={m.index}>{tok.slice(1, -1)}</code>)
    } else if (tok.startsWith('**')) {
      parts.push(<strong key={m.index}>{tok.slice(2, -2)}</strong>)
    } else {
      const [base, exp] = tok.split('^')
      parts.push(<span key={m.index}>{base}<sup>{exp}</sup></span>)
    }
    last = m.index + tok.length
  }
  if (last < text.length) parts.push(text.slice(last))
  return <>{parts}</>
}

function MessageContent({ text }) {
  if (!text) return null
  const codeBlockRe = /```([\s\S]*?)```/g
  const result = []
  let lastIndex = 0
  let match
  while ((match = codeBlockRe.exec(text)) !== null) {
    if (match.index > lastIndex) {
      result.push(<InlineText key={lastIndex} text={text.slice(lastIndex, match.index)} />)
    }
    const code = match[1].replace(/^\w+\n/, '').trim()
    result.push(<pre key={match.index}>{code}</pre>)
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) {
    result.push(<InlineText key={lastIndex} text={text.slice(lastIndex)} />)
  }
  return <>{result}</>
}

function NewSessionModal({ onConfirm, onCancel }) {
  const [subject, setSubject] = useState('biology')

  return (
    <div className="modal-backdrop">
      <div className="modal-card">
        <h3 style={{ fontFamily: 'var(--f-display)', fontSize: 20, marginBottom: 20 }}>
          New Chat Session
        </h3>
        <div className="cfg-f" style={{ marginBottom: 24 }}>
          <label className="cfg-lbl">Subject</label>
          <select value={subject} onChange={e => setSubject(e.target.value)}>
            {ALL_SUBJECTS.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-ghost" style={{ flex: 1 }} onClick={onCancel}>Cancel</button>
          <button className="btn btn-ochre" style={{ flex: 1 }} onClick={() => onConfirm(subject)}>
            Start Chat
          </button>
        </div>
      </div>
    </div>
  )
}
