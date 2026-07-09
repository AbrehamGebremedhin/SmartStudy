import { api } from './apiClient'

// Fire-and-forget: attempt logging must never disrupt practice.
export function recordAttempts(attempts) {
  if (!attempts?.length) return
  api.post('/analytics/attempts', { attempts }).catch(() => {})
}

export function getMastery(subject, { bySource = false } = {}) {
  const params = new URLSearchParams()
  if (subject) params.set('subject', subject)
  if (bySource) params.set('by_source', 'true')
  const qs = params.toString()
  return api.get(`/analytics/mastery${qs ? `?${qs}` : ''}`)
}

export function getTrends(days = 30, subject) {
  return api.get(`/analytics/trends?days=${days}${subject ? `&subject=${encodeURIComponent(subject)}` : ''}`)
}

export function getRetention() {
  return api.get('/analytics/retention')
}

// Tutor-chat volume per subject — secondary signal, only shown as context on
// weak areas the accuracy data already flagged.
export function getChatContext(days = 7) {
  return api.get(`/analytics/chat-context?days=${days}`)
}
