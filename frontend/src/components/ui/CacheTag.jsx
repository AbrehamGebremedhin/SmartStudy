export default function CacheTag({ hit }) {
  return (
    <span className={`c-tag ${hit ? 'c-cache' : 'c-new'}`}>
      {hit ? 'Cached' : 'New'}
    </span>
  )
}
