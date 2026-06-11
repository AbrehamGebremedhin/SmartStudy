import { useNavigate } from 'react-router-dom'
import Stele from '../components/ui/Stele'

export default function NotFound() {
  const navigate = useNavigate()
  return (
    <div className="notfound">
      <Stele mono height={64} className="notfound-mark" title="SmartStudy" />
      <div className="notfound-code">404</div>
      <h2>Page not found</h2>
      <p>The page you’re looking for doesn’t exist or may have moved.</p>
      <button className="btn btn-ochre notfound-cta" onClick={() => navigate('/')}>
        Back to Home
      </button>
    </div>
  )
}
