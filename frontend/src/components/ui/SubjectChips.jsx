import { ALL_SUBJECTS } from '../../lib/curriculum'
import Icon from './Icon'

export default function SubjectChips({ selected, onSelect, exclude = [] }) {
  const subjects = ALL_SUBJECTS.filter(s => !exclude.includes(s.id))
  return (
    <div className="subj-scroll">
      {subjects.map(s => (
        <button
          key={s.id}
          className={`subj-chip${selected === s.id ? ' sel' : ''}`}
          onClick={() => onSelect(s.id)}
        >
          <span className={`s-ico s-ico-${s.id}`}><Icon name={s.icon} size={17} /></span>
          {s.label}
        </button>
      ))}
    </div>
  )
}
