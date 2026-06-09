export default function DifficultyTag({ difficulty }) {
  return (
    <span className={`diff-tag dt-${difficulty}`}>{difficulty}</span>
  )
}
