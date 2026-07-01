import { api } from './apiClient'

// Fire-and-forget: attempt logging must never disrupt practice.
export function recordAttempts(attempts) {
  if (!attempts?.length) return
  api.post('/analytics/attempts', { attempts }).catch(() => {})
}

export function getMastery(subject) {
  return api.get(`/analytics/mastery${subject ? `?subject=${encodeURIComponent(subject)}` : ''}`)
}
