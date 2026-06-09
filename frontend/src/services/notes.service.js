import { api } from './apiClient'

/**
 * @param {{ subject: string, topic: string, grade: number|null, unit: string|null }} params
 * @returns {Promise<NotesResponse>}
 */
export function generateNotes({ subject, topic, grade, unit }) {
  return api.post('/notes/generate', { subject, topic, grade, unit, version: '1.0' })
}
