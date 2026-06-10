import Icon from './Icon'

export default function EmptyState({ icon, title, description, actionLabel, onAction }) {
  return (
    <div className="empty">
      <div className="empty-i"><Icon name={icon} size={44} stroke={1.25} /></div>
      <h3>{title}</h3>
      <p>{description}</p>
      {actionLabel && onAction && (
        <button className="btn btn-ochre btn-sm empty-cta" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  )
}
