import { api } from './apiClient'

/**
 * Generate MCQ questions.
 * @param {{ subject: string, grade: number|null, unit: string|null, num_questions: number, difficulty: string }} params
 * @returns {Promise<MCQResponse>}
 */
export function generateMCQ({ subject, grade, unit, num_questions, difficulty }) {
  return api.post('/mcq/generate', { subject, grade, unit, num_questions, difficulty })
}
