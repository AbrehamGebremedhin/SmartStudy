import { api } from './apiClient'

/**
 * @param {{ subject: string, grade: number|null, unit: string|null, topic: string|null, num_cards: number, difficulty: string }} params
 * @returns {Promise<FlashcardResponse>}
 */
export function generateFlashcards({ subject, grade, unit, topic, num_cards, difficulty }) {
  return api.post('/flashcards/generate', { subject, grade, unit, topic, num_cards, difficulty })
}
