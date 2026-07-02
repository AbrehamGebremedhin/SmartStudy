import { api } from './apiClient'
import { normalize } from './mistakes.service'

// Fire-and-forget: a failed save must never disrupt practice.
export function addBookmark(source, subject, question) {
  const payload = normalize(question)
  api.post('/bookmarks/', { source, subject, topic: payload.topic, question: payload })
    .catch(() => {})
}

export function removeBookmark(front) {
  return api.post('/bookmarks/remove', { front }).catch(() => {})
}

export function getBookmarks(subject) {
  return api.get(`/bookmarks/${subject ? `?subject=${encodeURIComponent(subject)}` : ''}`)
}
