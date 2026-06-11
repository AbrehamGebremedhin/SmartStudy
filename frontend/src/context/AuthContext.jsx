import { createContext, useContext, useEffect, useState, useCallback } from 'react'

const AuthContext = createContext(null)

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID

function decodeJwt(token) {
  try {
    const payload = token.split('.')[1]
    return JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))
  } catch {
    return null
  }
}

function tokenIsValid(token) {
  const payload = decodeJwt(token)
  if (!payload) return false
  return payload.exp * 1000 > Date.now()
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const stored = localStorage.getItem('ss_token')
    if (stored && tokenIsValid(stored)) {
      const payload = decodeJwt(stored)
      setUser({
        name: payload.name,
        email: payload.email,
        picture: payload.picture,
        sub: payload.sub,
      })
    }
    setLoading(false)

    const onLogout = () => {
      setUser(null)
      localStorage.removeItem('ss_token')
    }
    window.addEventListener('ss:logout', onLogout)
    return () => window.removeEventListener('ss:logout', onLogout)
  }, [])

  const login = useCallback((credential) => {
    localStorage.setItem('ss_token', credential)
    const payload = decodeJwt(credential)
    setUser({
      name: payload.name,
      email: payload.email,
      picture: payload.picture,
      sub: payload.sub,
    })
  }, [])

  useEffect(() => {
    if (!user) return
    const interval = setInterval(() => {
      const token = localStorage.getItem('ss_token')
      if (!token || !tokenIsValid(token)) {
        window.dispatchEvent(new Event('ss:logout'))
        return
      }
      const payload = decodeJwt(token)
      const msUntilExpiry = payload ? payload.exp * 1000 - Date.now() : 0
      if (msUntilExpiry < 5 * 60 * 1000 && window.google?.accounts?.id) {
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
          },
        })
        window.google.accounts.id.prompt()
      }
    }, 60_000)
    return () => clearInterval(interval)
  }, [user, login])

  const logout = useCallback(() => {
    localStorage.removeItem('ss_token')
    setUser(null)
    if (window.google?.accounts?.id) {
      window.google.accounts.id.disableAutoSelect()
    }
  }, [])

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
