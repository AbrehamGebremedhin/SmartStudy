// Seed the AI tutor with a specific question the student is stuck on.
// Handles both option shapes (MCQ "A text" strings; exam {letter,text} objects).
export function buildQuestionPrompt(q) {
  const opts = (q.options ?? [])
    .map(o => (typeof o === 'string' ? o : `${o.letter}. ${o.text ?? ''}`))
    .join('\n')
  const passage = q.passage ? `${q.passage}\n\n` : ''
  return `Help me understand this question.\n\n${passage}${q.question}\n\n${opts}\n\n` +
    `The correct answer is ${q.correct_answer}. Explain why simply, and where I likely went wrong.`
}

// Navigate to the tutor with the question pre-seeded (sent on arrival).
export function askAboutQuestion(navigate, subject, q) {
  navigate('/chat', { state: { ask: buildQuestionPrompt(q), subject: subject || 'biology' } })
}
