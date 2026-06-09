import { NavLink } from 'react-router-dom'

const TABS = [
  { to: '/', icon: '◆', label: 'Home', end: true },
  { to: '/mcq', icon: '✦', label: 'Quiz' },
  { to: '/flashcards', icon: '▣', label: 'Cards' },
  { to: '/chat', icon: '◉', label: 'Tutor' },
  { to: '/history', icon: '↻', label: 'History' },
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
          <span className="bn-i">{icon}</span>
          {label}
        </NavLink>
      ))}
    </div>
  )
}
