import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID

export default function Login() {
  const { login, user } = useAuth()
  const navigate = useNavigate()
  const btnRef = useRef(null)

  useEffect(() => {
    if (user) { navigate('/'); return }
  }, [user, navigate])

  useEffect(() => {
    function initGoogle() {
      if (!window.google?.accounts?.id) return
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: async ({ credential }) => {
          const res = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ credential }),
          })
          if (!res.ok) return
          const { access_token } = await res.json()
          login(access_token)
          navigate('/')
        },
      })
      window.google.accounts.id.renderButton(btnRef.current, {
        theme: 'outline',
        size: 'large',
        width: 300,
        text: 'continue_with',
        shape: 'rectangular',
        logo_alignment: 'left',
      })
    }

    if (window.google?.accounts?.id) {
      initGoogle()
    } else {
      const script = document.querySelector('script[src*="accounts.google.com/gsi"]')
      if (script) script.addEventListener('load', initGoogle)
    }
  }, [login, navigate])

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">SmartStudy</div>
        <div className="login-geez">ብልሃት ትምህርቲ</div>
        <p className="login-sub">
          AI-powered study companion for Ethiopian students.<br />
          Practice MCQs, flashcards, notes, and get help from an AI tutor.
        </p>
        <div className="login-divider" />
        <div ref={btnRef} style={{ display: 'flex', justifyContent: 'center' }} />
      </div>
    </div>
  )
}
