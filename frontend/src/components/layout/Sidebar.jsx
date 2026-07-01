import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import Icon from '../ui/Icon'
import Stele from '../ui/Stele'
import { getLevelInfo } from '../../lib/gamification'

const NAV_ITEMS = [
  { to: '/', label: 'Home', icon: 'home', end: true },
  { to: '/mcq', label: 'MCQ Quiz', icon: 'quiz' },
  { to: '/mock-exam', label: 'Mock Exam', icon: 'file-text' },
  { to: '/flashcards', label: 'Flashcards', icon: 'cards' },
  { to: '/review', label: 'Review Mistakes', icon: 'target' },
  { to: '/notes', label: 'Study Notes', icon: 'notes' },
  { to: '/chat', label: 'AI Tutor', icon: 'tutor' },
]

export default function Sidebar() {
  const { user, logout } = useAuth()
  const initial = user?.name?.[0]?.toUpperCase() ?? 'S'
  const [level] = useState(() => getLevelInfo())

  return (
    <div className="d-side">
      <div className="ds-brand">
        <Stele height={48} className="ds-mark" title="SmartStudy" />
        <div className="ds-brand-text">
          <div className="ds-title">SmartStudy</div>
          <div className="ds-geez">ብልሃት ትምህርቲ</div>
        </div>
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
            <span className="ds-ico"><Icon name={icon} size={17} /></span>
            {label}
          </NavLink>
        ))}

        <div className="ds-label" style={{ marginTop: 8 }}>Account</div>
        <NavLink
          to="/history"
          className={({ isActive }) => `ds-btn${isActive ? ' on' : ''}`}
        >
          <span className="ds-ico"><Icon name="history" size={17} /></span>
          Progress
        </NavLink>
      </div>

      <div className="ds-foot">
        <div className="ds-user">
          <div className="ds-av">
            {user?.picture ? <img src={user.picture} alt={user.name} /> : initial}
          </div>
          <div className="ds-user-info">
            <div className="ds-user-name">{user?.name ?? 'Student'}</div>
            <div className="ds-user-level">{level.geez} · {level.translation}</div>
          </div>
        </div>
        <button className="ds-btn ds-logout" onClick={logout}>
          <span className="ds-ico"><Icon name="logout" size={17} /></span>
          Sign out
        </button>
      </div>
    </div>
  )
}
