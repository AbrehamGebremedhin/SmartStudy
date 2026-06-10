export const ALL_SUBJECTS = [
  { id: 'biology', label: 'Biology', icon: 'biology', color: '#4a7c59' },
  { id: 'chemistry', label: 'Chemistry', icon: 'chemistry', color: '#8b6914' },
  { id: 'physics', label: 'Physics', icon: 'physics', color: '#6b3a5c' },
  { id: 'maths', label: 'Mathematics', icon: 'maths', color: '#4a5a8b' },
  { id: 'english', label: 'English', icon: 'english', color: '#7c4a2d' },
  { id: 'civics', label: 'Civics', icon: 'civics', color: '#6b5b73' },
  { id: 'economics', label: 'Economics', icon: 'economics', color: '#2d6a4f' },
  { id: 'geography', label: 'Geography', icon: 'geography', color: '#3a6b8c' },
  { id: 'history', label: 'History', icon: 'history-subject', color: '#8b5e3c' },
  { id: 'general_business', label: 'Business', icon: 'business', color: '#5a5a3c' },
  { id: 'sat', label: 'SAT', icon: 'target', color: '#8b3a3a' },
]

export const GRADES = [9, 10, 11, 12]

export const VALID_UNITS = {
  12: { biology: 6, chemistry: 5, civics: 10, economics: 8, english: 10, general_business: 4, geography: 8, history: 9, maths: 9, physics: 5 },
  11: { biology: 6, chemistry: 6, civics: 11, economics: 6, english: 10, general_business: 4, geography: 8, history: 9, maths: 8, physics: 7 },
  10: { biology: 5, chemistry: 6, civics: 8, economics: 8, english: 10, geography: 8, history: 9, maths: 7, physics: 6 },
  9:  { biology: 6, chemistry: 5, civics: 8, economics: 7, english: 12, geography: 8, history: 9, maths: 9, physics: 7 },
}

export const DIFFICULTIES = ['easy', 'medium', 'hard', 'challenging']

export function getUnitCount(grade, subject) {
  return VALID_UNITS[grade]?.[subject] ?? 5
}

/** Returns null if valid, or an error string describing the problem. */
export function validateCurriculumParams(grade, subject, unit) {
  const CROSS_GRADE = ['sat', 'english']
  if (CROSS_GRADE.includes(subject)) return null
  if (grade == null) return null

  const gradeData = VALID_UNITS[grade]
  if (!gradeData) return `Grade ${grade} is not available. Valid grades are 9–12.`

  if (!(subject in gradeData)) {
    const available = Object.keys(gradeData).join(', ')
    return `'${subject}' is not offered in Grade ${grade}. Available: ${available}.`
  }

  if (unit != null) {
    const unitNum = Number(unit)
    const max = gradeData[subject]
    if (!Number.isInteger(unitNum) || unitNum < 1 || unitNum > max) {
      return `Unit ${unit} doesn't exist for ${subject} Grade ${grade}. Valid units are 1–${max}.`
    }
  }

  return null
}

export function getDaysUntilEUEE() {
  const d = new Date('2027-05-15')
  return Math.max(0, Math.ceil((d - new Date()) / 86400000))
}

export function subjectLabel(id) {
  return ALL_SUBJECTS.find(s => s.id === id)?.label ?? id
}

export function typeIcon(type) {
  switch (type) {
    case 'mcq': return 'quiz'
    case 'flashcard': return 'cards'
    case 'notes': return 'notes'
    default: return 'sparkle'
  }
}
