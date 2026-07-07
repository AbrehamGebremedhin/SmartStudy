import { api } from './apiClient'

/**
 * grade/unit/topic tag the attempt row the backend logs for analytics.
 * @param {{ subject: string, question: object, student_answer: string, note: object|null,
 *           grade: number|null, unit: string|null, topic: string|null }} params
 * @returns {Promise<EvaluateAnswerResponse>}
 */
export function evaluateAnswer({ subject, question, student_answer, note = null, grade = null, unit = null, topic = null }) {
  return api.post('/evaluate', { subject, question, student_answer, note, grade, unit, topic })
}
