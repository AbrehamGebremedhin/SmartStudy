import { api } from './apiClient'

/**
 * @param {{ subject: string, topic: string, grade: number|null, unit: string|null }} params
 * @returns {Promise<NotesResponse>}
 */
export function generateNotes({ subject, topic, grade, unit, chat_session_id }) {
  return api.post('/notes/generate', { subject, topic, grade, unit, chat_session_id, version: '1.0' })
}

export function chatWithNote(generationId, question, chatHistory) {
  return api.post(`/notes/${generationId}/chat`, { question, chat_history: chatHistory })
}
