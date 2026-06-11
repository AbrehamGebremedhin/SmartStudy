import Icon from './Icon'

/**
 * Reusable inline error state with an optional retry action.
 * Pass the caught `error` (Error or string) and we pick a sensible icon,
 * heading, and message; any of those can be overridden via props.
 *
 *   <ErrorState error={err} onRetry={handleGenerate} />
 *   <ErrorState title="Couldn't load history" error={err} onRetry={reload} />
 */
export default function ErrorState({ title, description, error, onRetry, retryLabel = 'Try again', icon }) {
  const isNetwork = Boolean(error?.isNetwork)
  const ico = icon ?? (isNetwork ? 'wifi-off' : 'alert')
  const heading = title ?? (isNetwork ? 'Connection problem' : "That didn't work")
  const message =
    description ??
    error?.message ??
    (typeof error === 'string' ? error : 'An unexpected error occurred. Please try again.')

  return (
    <div className="error-state" role="alert">
      <div className="error-state-i"><Icon name={ico} size={36} stroke={1.5} /></div>
      <h3>{heading}</h3>
      <p>{message}</p>
      {onRetry && (
        <button className="btn btn-ochre btn-sm error-state-cta" onClick={onRetry}>
          <Icon name="retry" size={15} /> {retryLabel}
        </button>
      )}
    </div>
  )
}
