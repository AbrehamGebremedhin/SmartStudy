import { Component } from 'react'
import Stele from './Stele'

// Catches render-time crashes anywhere below it and shows a branded
// fallback instead of a blank white screen. Reload/Go home both reset
// the React tree via a full navigation.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  componentDidCatch(error, info) {
    console.error('Uncaught render error:', error, info)
  }

  render() {
    if (!this.state.hasError) return this.props.children

    return (
      <div className="crash-page">
        <div className="crash-card">
          <Stele mono height={64} className="crash-mark" title="SmartStudy" />
          <h1>Something went wrong</h1>
          <p>An unexpected error interrupted the app. Reloading usually fixes it — your progress is saved.</p>
          <div className="crash-actions">
            <button className="btn btn-ochre" onClick={() => window.location.reload()}>Reload</button>
            <button className="btn btn-ghost" onClick={() => window.location.assign('/')}>Go home</button>
          </div>
        </div>
      </div>
    )
  }
}
