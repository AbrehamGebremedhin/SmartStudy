const PREFIX = 'ss_gen_'

export function saveGeneration(generationId, data) {
  try {
    localStorage.setItem(`${PREFIX}${generationId}`, JSON.stringify(data))
  } catch {
    // localStorage full — silently skip
  }
}

export function loadGeneration(generationId) {
  if (!generationId) return null
  try {
    const raw = localStorage.getItem(`${PREFIX}${generationId}`)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function updateGeneration(generationId, updates) {
  const existing = loadGeneration(generationId)
  if (existing) saveGeneration(generationId, { ...existing, ...updates })
}

export function routeForType(type) {
  if (type === 'flashcard') return '/flashcards'
  if (type === 'notes') return '/notes'
  return '/mcq'
}
