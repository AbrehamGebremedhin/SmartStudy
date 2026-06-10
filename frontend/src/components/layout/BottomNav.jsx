import { NavLink } from 'react-router-dom'
import Icon from '../ui/Icon'

const TABS = [
  { to: '/', icon: 'home', label: 'Home', end: true },
  { to: '/mcq', icon: 'quiz', label: 'Quiz' },
  { to: '/flashcards', icon: 'cards', label: 'Cards' },
  { to: '/chat', icon: 'tutor', label: 'Tutor' },
  { to: '/history', icon: 'history', label: 'Progress' },
]

export default function BottomNav() {
  return (
    <div className="b-nav">
      {TABS.map(({ to, icon, label, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) => `bn-btn${isActive ? ' on' : ''}`}
        >
          <span className="bn-i"><Icon name={icon} size={21} /></span>
          {label}
        </NavLink>
      ))}
    </div>
  )
}
