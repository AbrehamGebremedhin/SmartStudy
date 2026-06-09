import { useAuth } from '../../context/AuthContext'

export default function MobileHeader() {
  const { user } = useAuth()
  const initial = user?.name?.[0]?.toUpperCase() ?? 'S'

  return (
    <div className="m-head">
      <div className="mh-name">SmartStudy</div>
      <div className="mh-av">
        {user?.picture ? <img src={user.picture} alt={user.name} /> : initial}
      </div>
    </div>
  )
}
