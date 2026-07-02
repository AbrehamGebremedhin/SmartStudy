import Icon from './Icon'

export default function BookmarkButton({ active, onToggle }) {
  return (
    <button
      type="button"
      className={`bmk-btn${active ? ' on' : ''}`}
      onClick={onToggle}
      aria-label={active ? 'Remove bookmark' : 'Save question'}
      aria-pressed={active}
      title={active ? 'Saved — tap to remove' : 'Save for later'}
    >
      <Icon name="bookmark" size={16} />
    </button>
  )
}
