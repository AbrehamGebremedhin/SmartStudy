import { api } from './apiClient'

export function listSessions(limit = 50, offset = 0) {
  return api.get(`/chat/sessions?limit=${limit}&offset=${offset}`)
}

export function getSession(sessionId) {
  return api.get(`/chat/sessions/${sessionId}`)
}

export function createSession({ subject, grade, title = 'New Chat' }) {
  return api.post('/chat/sessions', { subject, grade, title })
}

export function updateSessionTitle(sessionId, title) {
  return api.put(`/chat/sessions/${sessionId}/title`, { title })
}

export function sendMessage(sessionId, question) {
  return api.post(`/chat/sessions/${sessionId}/messages`, { question })
}

export function getSessionContext(sessionId) {
  return api.get(`/chat/sessions/${sessionId}/context`)
}
