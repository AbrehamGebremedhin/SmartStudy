import { NavLink } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'

const NAV_ITEMS = [
  { to: '/', label: 'Home', icon: '◆', end: true },
  { to: '/mcq', label: 'MCQ Quiz', icon: '✦' },
  { to: '/flashcards', label: 'Flashcards', icon: '▣' },
  { to: '/notes', label: 'Study Notes', icon: '≡' },
  { to: '/chat', label: 'AI Tutor', icon: '◉' },
]

export default function Sidebar() {
  const { user } = useAuth()
  const initial = user?.name?.[0]?.toUpperCase() ?? 'S'

  return (
    <div className="d-side">
      <div className="ds-brand">
        <div className="ds-title">SmartStudy</div>
        <div className="ds-geez">ብልሃት ትምህርቲ</div>
      </div>

      <div className="ds-nav">
        <div className="ds-label">Learn</div>
        {NAV_ITEMS.map(({ to, label, icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) => `ds-btn${isActive ? ' on' : ''}`}
          >
            <span className="ds-ico">{icon}</span>
            {label}
          </NavLink>
        ))}

        <div className="ds-label" style={{ marginTop: 8 }}>Account</div>
        <NavLink
          to="/history"
          className={({ isActive }) => `ds-btn${isActive ? ' on' : ''}`}
        >
          <span className="ds-ico">↻</span>
          History
        </NavLink>
      </div>

      <div className="ds-foot">
        <div className="ds-user">
          <div className="ds-av">
            {user?.picture ? <img src={user.picture} alt={user.name} /> : initial}
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 500, color: 'rgba(246,240,228,0.8)' }}>
              {user?.name ?? 'Student'}
            </div>
            <div style={{ fontSize: 11, color: 'rgba(246,240,228,0.3)' }}>
              {user?.email ?? ''}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
