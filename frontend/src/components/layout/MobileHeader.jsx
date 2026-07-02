import { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import Icon from '../ui/Icon'
import Stele from '../ui/Stele'
import { getTheme, setTheme } from '../../lib/theme'

export default function MobileHeader() {
  const { user, logout } = useAuth()
  const initial = user?.name?.[0]?.toUpperCase() ?? 'S'
  const [theme, setThemeState] = useState(() => getTheme())

  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    setThemeState(next)
  }

  return (
    <div className="m-head">
      <div className="mh-brand">
        <Stele height={26} title="SmartStudy" />
        <div className="mh-name">SmartStudy</div>
      </div>
      <div className="mh-right">
        <div className="mh-av">
          {user?.picture ? <img src={user.picture} alt={user.name} /> : initial}
        </div>
        <button className="mh-logout" onClick={toggleTheme} aria-label="Toggle dark mode">
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={18} />
        </button>
        <button className="mh-logout" onClick={logout} aria-label="Sign out">
          <Icon name="logout" size={18} />
        </button>
      </div>
    </div>
  )
}
