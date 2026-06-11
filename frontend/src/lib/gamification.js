// localStorage-backed gamification: XP, levels, streaks, achievements.
// All reads survive corrupt/missing data; writes swallow quota errors.
// IMPORTANT: call awardXP from event handlers only — never from useEffect.
// StrictMode double-invokes effects in dev and would double-award.

const KEY = 'ss_gamify_v1'
const GEN_PREFIX = 'ss_gen_'
const CHAT_DAILY_CAP = 6
const ACTIVITY_DAYS_KEPT = 60

export const XP_VALUES = {
  mcq_correct: 10,
  mcq_incorrect: 2,
  quiz_complete: 25,
  quiz_perfect: 25,
  card_rated: 2,
  deck_complete: 20,
  deck_all_known: 15,
  gen_mcq: 5,
  gen_flashcards: 5,
  gen_notes: 15,
  eval_submitted: 15,
  eval_high: 10,
  chat_question: 5,
}

// Ethiopian traditional-school progression, from student to chief of scholars.
export const LEVELS = [
  { geez: 'ተማሪ', name: 'Temari', translation: 'Student', threshold: 0 },
  { geez: 'አንባቢ', name: 'Anbabi', translation: 'Reader', threshold: 150 },
  { geez: 'ጸሐፊ', name: 'Tsehafi', translation: 'Scribe', threshold: 400 },
  { geez: 'ባለቅኔ', name: 'Baleqine', translation: 'Poet of Qiné', threshold: 800 },
  { geez: 'ዘማሪ', name: 'Zemari', translation: 'Cantor', threshold: 1400 },
  { geez: 'መምህር', name: 'Memhir', translation: 'Teacher', threshold: 2200 },
  { geez: 'ሊቅ', name: 'Liq', translation: 'Scholar', threshold: 3400 },
  { geez: 'ሊቀ ሊቃውንት', name: 'Liqe Liqawnt', translation: 'Scholar of Scholars', threshold: 5000 },
]

export const ACHIEVEMENTS = [
  { id: 'first_steps', name: 'First Steps', geez: 'ጅማሮ', desc: 'Earn your first XP', icon: 'sparkle' },
  { id: 'first_quiz', name: 'Quiz Taker', desc: 'Complete your first quiz', icon: 'quiz' },
  { id: 'perfect_quiz', name: 'Flawless', geez: 'ጎበዝ', desc: 'Score 100% on a quiz', icon: 'star' },
  { id: 'sharp_mind', name: 'Sharp Mind', desc: 'Answer 50 questions correctly', icon: 'check' },
  { id: 'century', name: 'Century', desc: 'Answer 100 questions', icon: 'trophy' },
  { id: 'deck_master', name: 'Deck Master', desc: 'Complete a flashcard deck', icon: 'cards' },
  { id: 'total_recall', name: 'Total Recall', desc: 'Know every card in a deck of 5+', icon: 'cards' },
  { id: 'note_taker', name: 'Note Taker', desc: 'Generate your first study notes', icon: 'notes' },
  { id: 'deep_thinker', name: 'Deep Thinker', desc: 'Submit 10 written answers', icon: 'notes' },
  { id: 'curious', name: 'Curious Mind', desc: 'Ask the tutor 25 questions', icon: 'tutor' },
  { id: 'streak_3', name: 'Kindling', desc: 'Study 3 days in a row', icon: 'flame' },
  { id: 'streak_7', name: 'Week of Fire', desc: 'Study 7 days in a row', icon: 'flame' },
  { id: 'streak_30', name: 'Unbroken', desc: 'Study 30 days in a row', icon: 'flame' },
  { id: 'explorer', name: 'Explorer', desc: 'Study 5 different subjects', icon: 'geography' },
  { id: 'night_owl', name: 'Night Owl', desc: 'Study after 10pm', icon: 'history' },
]

export const STUDY_TIPS = [
  'Active recall beats re-reading — test yourself, don’t just review.',
  'በርታ! (Berta — keep going!) Small daily sessions beat cramming.',
  'Teach a concept to a friend — if you can explain it, you know it.',
  'EUEE rewards timing: practice answering in under 90 seconds per question.',
  'Mix subjects in one sitting — interleaving strengthens memory.',
  'Wrong answers are data. Read every explanation, even when you guess right.',
  'Sleep is study time: your brain consolidates what you learned today.',
  'ትዕግስቲ! (Patience!) Mastery is built one unit at a time.',
  'Past EUEE papers are gold — patterns repeat across years.',
  'Write formulas by hand — motor memory makes them stick.',
  'Stuck? Ask the tutor to explain it simply, then build back up.',
  'A 7-day streak grows your brain more than a 7-hour Sunday.',
]

const RESULT_MESSAGES = {
  high: [
    'ጎበዝ! (Gobez!) Outstanding work — you own this topic.',
    'ጎበዝ! Excellence like this passes exams.',
    'ምርጥ! (Mirt!) That was sharp — keep this level up.',
  ],
  mid: [
    'Solid effort — review the missed ones and go again.',
    'Good push. The explanations below are your next win.',
    'Almost there — one more round and this band turns green.',
  ],
  low: [
    'Every master was once a beginner. Read the explanations and retry.',
    'This topic is still settling — read the notes, then try again.',
    'Don’t worry — wrong answers teach faster than right ones.',
  ],
}

/** Stable encouraging message for a score band; seed keeps it fixed across re-renders. */
export function resultMessage(pct, seed = '') {
  const band = pct >= 80 ? 'high' : pct >= 50 ? 'mid' : 'low'
  const list = RESULT_MESSAGES[band]
  let sum = 0
  for (const ch of String(seed)) sum += ch.charCodeAt(0)
  return list[sum % list.length]
}

// ─── Profile storage ─────────────────────────────────────────────────────────

function num(v, d = 0) {
  return Number.isFinite(v) ? v : d
}

function defaultProfile() {
  return {
    v: 1,
    xp: 0,
    streak: { current: 0, best: 0, lastActive: '' },
    counters: {
      questionsAnswered: 0,
      questionsCorrect: 0,
      quizzesCompleted: 0,
      perfectQuizzes: 0,
      cardsRated: 0,
      cardsKnown: 0,
      decksCompleted: 0,
      perfectDecks: 0,
      notesGenerated: 0,
      evaluationsSubmitted: 0,
      chatQuestions: 0,
    },
    day: { date: '', chat: 0 },
    subjects: {},
    achievements: {},
    activity: {},
    lastGen: null,
    migrated: false,
  }
}

function sanitize(raw) {
  const p = raw && typeof raw === 'object' ? raw : {}
  const out = defaultProfile()
  out.xp = num(p.xp)
  const s = p.streak ?? {}
  out.streak = {
    current: num(s.current),
    best: num(s.best),
    lastActive: typeof s.lastActive === 'string' ? s.lastActive : '',
  }
  if (p.counters && typeof p.counters === 'object') {
    for (const k of Object.keys(out.counters)) out.counters[k] = num(p.counters[k])
  }
  const day = p.day ?? {}
  out.day = { date: typeof day.date === 'string' ? day.date : '', chat: num(day.chat) }
  if (p.subjects && typeof p.subjects === 'object') {
    for (const [k, v] of Object.entries(p.subjects)) {
      if (v && typeof v === 'object') out.subjects[k] = { answered: num(v.answered), correct: num(v.correct) }
    }
  }
  if (p.achievements && typeof p.achievements === 'object') {
    for (const [k, v] of Object.entries(p.achievements)) {
      if (typeof v === 'string') out.achievements[k] = v
    }
  }
  if (p.activity && typeof p.activity === 'object') {
    for (const [k, v] of Object.entries(p.activity)) {
      if (Number.isFinite(v)) out.activity[k] = v
    }
  }
  out.lastGen = p.lastGen && typeof p.lastGen === 'object' ? p.lastGen : null
  out.migrated = p.migrated === true
  return out
}

function save(profile) {
  try {
    localStorage.setItem(KEY, JSON.stringify(profile))
  } catch {
    // localStorage full or unavailable — silently skip
  }
}

function load() {
  let raw = null
  try {
    raw = JSON.parse(localStorage.getItem(KEY))
  } catch {
    // corrupt JSON — start fresh
  }
  const profile = sanitize(raw)
  if (!profile.migrated) migrate(profile)
  return profile
}

/** One-time: seed counters from pre-gamification MCQ scores so existing users don't start at zero. */
function migrate(profile) {
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (!key?.startsWith(GEN_PREFIX)) continue
      let gen = null
      try {
        gen = JSON.parse(localStorage.getItem(key))
      } catch {
        continue
      }
      if (gen?.type !== 'mcq' || !gen.score) continue
      const total = num(gen.score.total)
      const correct = num(gen.score.correct)
      if (total <= 0) continue
      profile.counters.questionsAnswered += total
      profile.counters.questionsCorrect += correct
      profile.counters.quizzesCompleted += 1
      if (correct === total) profile.counters.perfectQuizzes += 1
      const subj = gen.config?.subject
      if (subj) {
        const st = profile.subjects[subj] ?? { answered: 0, correct: 0 }
        st.answered += total
        st.correct += correct
        profile.subjects[subj] = st
      }
    }
  } catch {
    // localStorage unavailable
  }
  profile.migrated = true
  save(profile)
}

function dateStr(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function todayStr() {
  return dateStr(new Date())
}

function yesterdayStr() {
  return dateStr(new Date(Date.now() - 86400000))
}

function levelIndex(xp) {
  let idx = 0
  for (let i = 0; i < LEVELS.length; i++) {
    if (xp >= LEVELS[i].threshold) idx = i
  }
  return idx
}

function dispatch(name, detail) {
  try {
    window.dispatchEvent(new CustomEvent(name, { detail }))
  } catch {
    // non-browser environment
  }
}

// ─── Public API ──────────────────────────────────────────────────────────────

export function getProfile() {
  return load()
}

export function getLevelInfo(xp) {
  const points = xp ?? load().xp
  const index = levelIndex(points)
  const level = LEVELS[index]
  const next = LEVELS[index + 1] ?? null
  const pct = next
    ? Math.min(100, Math.round(((points - level.threshold) / (next.threshold - level.threshold)) * 100))
    : 100
  return { index, ...level, xp: points, next, pct, isMax: !next }
}

export function getStreak() {
  const p = load()
  const activeToday = p.streak.lastActive === todayStr()
  const alive = activeToday || p.streak.lastActive === yesterdayStr()
  return { current: alive ? p.streak.current : 0, best: p.streak.best, activeToday }
}

export function getStats() {
  const p = load()
  const { questionsAnswered, questionsCorrect } = p.counters
  const perSubject = Object.entries(p.subjects)
    .map(([id, s]) => ({
      id,
      answered: s.answered,
      correct: s.correct,
      pct: s.answered > 0 ? Math.round((s.correct / s.answered) * 100) : null,
    }))
    .filter(s => s.answered > 0)
    .sort((a, b) => b.answered - a.answered)
  return {
    questionsAnswered,
    questionsCorrect,
    accuracyPct: questionsAnswered > 0 ? Math.round((questionsCorrect / questionsAnswered) * 100) : null,
    perSubject,
    counters: p.counters,
  }
}

export function getAchievements() {
  const p = load()
  return ACHIEVEMENTS.map(a => ({ ...a, unlockedAt: p.achievements[a.id] ?? null }))
}

export function getLastActivity() {
  return load().lastGen
}

/**
 * Build a GitHub-style activity calendar from daily XP totals.
 * Returns whole weeks (Sun→Sat columns) covering the last `weeks` weeks up to
 * today, each day carrying its XP and a 0–4 intensity level for colouring.
 */
export function getActivityCalendar(weeks = 10) {
  const activity = load().activity
  const today = new Date()
  today.setHours(0, 0, 0, 0)

  // End on the Saturday of the current week so the final column is complete.
  const end = new Date(today)
  end.setDate(end.getDate() + (6 - end.getDay()))
  const totalDays = weeks * 7
  const start = new Date(end)
  start.setDate(start.getDate() - (totalDays - 1))

  const todayKey = dateStr(today)
  const cols = []
  let max = 0
  for (const k of Object.keys(activity)) max = Math.max(max, num(activity[k]))

  for (let w = 0; w < weeks; w++) {
    const col = []
    for (let d = 0; d < 7; d++) {
      const date = new Date(start)
      date.setDate(date.getDate() + w * 7 + d)
      const key = dateStr(date)
      const xp = num(activity[key])
      const future = date > today
      let level = 0
      if (xp > 0) level = max > 0 ? Math.min(4, 1 + Math.floor((xp / max) * 3)) : 1
      col.push({ key, xp, level, future, isToday: key === todayKey })
    }
    cols.push(col)
  }
  return { cols, max }
}

/** Remember the most recent generation so Home can offer "continue studying". */
export function recordLastGen(meta) {
  const p = load()
  p.lastGen = { ...meta, at: new Date().toISOString() }
  save(p)
}

/**
 * Award XP for a study action. Updates streak, counters, per-subject stats and
 * achievements, persists, and dispatches ss:xp / ss:levelup / ss:achievement
 * window events for GamifyLayer toasts.
 *
 * meta: { subject?, correct?, total?, known?, allKnown?, size?, score? }
 */
export function awardXP(action, meta = {}) {
  const profile = load()
  let gained = XP_VALUES[action] ?? 0

  const perfectQuiz = action === 'quiz_complete' && num(meta.total) > 0 && meta.correct === meta.total
  if (perfectQuiz) gained += XP_VALUES.quiz_perfect
  if (action === 'deck_complete' && meta.allKnown) gained += XP_VALUES.deck_all_known
  if (action === 'eval_submitted' && num(meta.score) >= 0.8) gained += XP_VALUES.eval_high

  if (action === 'chat_question') {
    const today = todayStr()
    if (profile.day.date !== today) profile.day = { date: today, chat: 0 }
    if (profile.day.chat >= CHAT_DAILY_CAP) gained = 0
    profile.day.chat += 1
  }

  const c = profile.counters
  switch (action) {
    case 'mcq_correct':
      c.questionsAnswered += 1
      c.questionsCorrect += 1
      break
    case 'mcq_incorrect':
      c.questionsAnswered += 1
      break
    case 'quiz_complete':
      c.quizzesCompleted += 1
      if (perfectQuiz) c.perfectQuizzes += 1
      break
    case 'card_rated':
      c.cardsRated += 1
      if (meta.known) c.cardsKnown += 1
      break
    case 'deck_complete':
      c.decksCompleted += 1
      if (meta.allKnown && num(meta.size) >= 5) c.perfectDecks += 1
      break
    case 'gen_notes':
      c.notesGenerated += 1
      break
    case 'eval_submitted':
      c.evaluationsSubmitted += 1
      break
    case 'chat_question':
      c.chatQuestions += 1
      break
    default:
      break
  }

  if (meta.subject) {
    const s = profile.subjects[meta.subject] ?? { answered: 0, correct: 0 }
    if (action === 'mcq_correct') {
      s.answered += 1
      s.correct += 1
    } else if (action === 'mcq_incorrect') {
      s.answered += 1
    }
    profile.subjects[meta.subject] = s
  }

  const today = todayStr()
  const st = profile.streak
  if (st.lastActive !== today) {
    st.current = st.lastActive === yesterdayStr() ? st.current + 1 : 1
    st.lastActive = today
    if (st.current > st.best) st.best = st.current
  }

  const before = levelIndex(profile.xp)
  profile.xp += gained
  const after = levelIndex(profile.xp)
  const leveledUp = after > before

  profile.activity[today] = num(profile.activity[today]) + gained
  const days = Object.keys(profile.activity).sort()
  while (days.length > ACTIVITY_DAYS_KEPT) delete profile.activity[days.shift()]

  const unlocked = checkAchievements(profile)

  save(profile)

  if (gained > 0) dispatch('ss:xp', { gained, total: profile.xp })
  if (leveledUp) dispatch('ss:levelup', { level: { ...LEVELS[after], index: after } })
  for (const a of unlocked) dispatch('ss:achievement', { achievement: a })

  return { gained, total: profile.xp, leveledUp, unlocked }
}

function checkAchievements(profile) {
  const c = profile.counters
  const hour = new Date().getHours()
  const conditions = {
    first_steps: profile.xp > 0,
    first_quiz: c.quizzesCompleted >= 1,
    perfect_quiz: c.perfectQuizzes >= 1,
    sharp_mind: c.questionsCorrect >= 50,
    century: c.questionsAnswered >= 100,
    deck_master: c.decksCompleted >= 1,
    total_recall: c.perfectDecks >= 1,
    note_taker: c.notesGenerated >= 1,
    deep_thinker: c.evaluationsSubmitted >= 10,
    curious: c.chatQuestions >= 25,
    streak_3: profile.streak.current >= 3,
    streak_7: profile.streak.current >= 7,
    streak_30: profile.streak.current >= 30,
    explorer: Object.keys(profile.subjects).length >= 5,
    night_owl: hour >= 22 || hour < 4,
  }
  const unlocked = []
  for (const a of ACHIEVEMENTS) {
    if (!profile.achievements[a.id] && conditions[a.id]) {
      profile.achievements[a.id] = new Date().toISOString()
      unlocked.push(a)
    }
  }
  return unlocked
}
