import { createContext, useContext, useEffect, useState, useCallback } from 'react'

const AuthContext = createContext(null)

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
