import { ALL_SUBJECTS, GRADES, DIFFICULTIES, getUnitCount } from '../../lib/curriculum'

/**
 * Reusable configuration panel for MCQ, Flashcards, and Notes.
 *
 * Props:
 *   config        – { subject, grade, unit, difficulty, numItems, topic }
 *   onChange      – (key, value) => void
 *   onGenerate    – () => void
 *   loading       – bool
 *   showUnit      – bool (default true)
 *   showDifficulty– bool (default true)
 *   showTopic     – bool (default false)
 *   showNumItems  – bool (default true)
 *   numItemsLabel – string (default 'Questions')
 *   numItemsMax   – number (default 20)
 *   excludeSubjects – string[] (ids to hide)
 *   generateLabel – string
 */
export default function ConfigPanel({
  config,
  onChange,
  onGenerate,
  loading = false,
  showUnit = true,
  showDifficulty = true,
  showTopic = false,
  showNumItems = true,
  numItemsLabel = 'Questions',
  numItemsMax = 20,
  excludeSubjects = [],
  generateLabel = 'Generate',
}) {
  const { subject, grade, unit, difficulty, numItems, topic } = config
  const isCrossGrade = subject === 'sat'
  const maxUnits = getUnitCount(grade, subject)
  const subjects = ALL_SUBJECTS.filter(s => !excludeSubjects.includes(s.id))

  function handleSubjectChange(e) {
    onChange('subject', e.target.value)
    onChange('unit', '1')
  }

  function handleGradeChange(e) {
    onChange('grade', Number(e.target.value))
    onChange('unit', '1')
  }

  return (
    <div className="cfg">
      <div className="cfg-grid">
        <div className="cfg-f">
          <label className="cfg-lbl">Subject</label>
          <select value={subject} onChange={handleSubjectChange}>
            {subjects.map(s => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </div>

        {!isCrossGrade && (
          <div className="cfg-f">
            <label className="cfg-lbl">Grade</label>
            <select value={grade} onChange={handleGradeChange}>
              {GRADES.map(g => (
                <option key={g} value={g}>Grade {g}</option>
              ))}
            </select>
          </div>
        )}

        {showUnit && !isCrossGrade && (
          <div className="cfg-f">
            <label className="cfg-lbl">Unit (1–{maxUnits})</label>
            <select value={unit} onChange={e => onChange('unit', e.target.value)}>
              {Array.from({ length: maxUnits }, (_, i) => (
                <option key={i + 1} value={String(i + 1)}>Unit {i + 1}</option>
              ))}
            </select>
          </div>
        )}

        {showDifficulty && (
          <div className="cfg-f">
            <label className="cfg-lbl">Difficulty</label>
            <select value={difficulty} onChange={e => onChange('difficulty', e.target.value)}>
              {DIFFICULTIES.map(d => (
                <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
              ))}
            </select>
          </div>
        )}

        {showNumItems && (
          <div className="cfg-f">
            <label className="cfg-lbl">{numItemsLabel} (1–{numItemsMax})</label>
            <input
              type="number"
              min={1}
              max={numItemsMax}
              value={numItems}
              onChange={e => onChange('numItems', Math.min(numItemsMax, Math.max(1, Number(e.target.value))))}
            />
          </div>
        )}

        {showTopic && (
          <div className="cfg-f full">
            <label className="cfg-lbl">Topic</label>
            <input
              type="text"
              placeholder="e.g. ATP synthesis in cellular respiration"
              value={topic ?? ''}
              onChange={e => onChange('topic', e.target.value)}
            />
          </div>
        )}
      </div>

      <button
        className="btn btn-ochre btn-block"
        onClick={onGenerate}
        disabled={loading}
      >
        {loading ? <span className="spinner" /> : generateLabel}
      </button>
    </div>
  )
}
