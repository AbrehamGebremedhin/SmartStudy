import { api } from './apiClient'

// Normalize either question shape into what the review deck renders.
// MCQ generated: options are "A text" strings, letter = opt[0].
// Exam: options are { letter, text, image_url } objects.
export function normalize(q) {
  const options = (q.options ?? []).map(o =>
    typeof o === 'string'
      ? { letter: o[0], text: o.slice(3) }
      : { letter: o.letter, text: o.text, image_url: o.image_url }
  )
  return {
    question: q.question,
    passage: q.passage ?? null,
    topic: q.topic ?? null,
    question_image_url: q.question_image_url ?? null,
    options,
    correct_answer: q.correct_answer,
    correct_explanations: q.correct_explanations ?? [],
    incorrect_explanations: q.incorrect_explanations ?? {},
  }
}

// Fire-and-forget: a failed record must never disrupt practice.
export function recordMistake(source, subject, question) {
  const payload = normalize(question)
  api.post('/mistakes/', { source, subject, topic: payload.topic, question: payload })
    .catch(() => {})
}

export function getMistakes(subject) {
  return api.get(`/mistakes/${subject ? `?subject=${encodeURIComponent(subject)}` : ''}`)
}

export function getMistakeCount() {
  return api.get('/mistakes/count')
}

export function resolveMistake(front) {
  return api.post('/mistakes/resolve', { front })
}
