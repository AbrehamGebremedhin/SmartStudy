import { api } from './apiClient'

/**
 * @param {{ subject: string, question: object, student_answer: string, note: object|null }} params
 * @returns {Promise<EvaluateAnswerResponse>}
 */
export function evaluateAnswer({ subject, question, student_answer, note = null }) {
  return api.post('/evaluate', { subject, question, student_answer, note })
}
