export default function EmptyState({ icon, title, description }) {
  return (
    <div className="empty">
      <div className="empty-i">{icon}</div>
      <h3>{title}</h3>
      <p>{description}</p>
    </div>
  )
}
