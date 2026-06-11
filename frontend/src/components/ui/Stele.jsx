// SmartStudy brand mark — the Obelisk of Aksum, rendered faithfully from the
// brand SVGs in /icons. One source of geometry, three presentations:
//   <Stele />            bare mark, for dark surfaces (sidebar, header, hero)
//   <Stele mono />       single-colour silhouette, for faint watermarks
//   <Stele tile />       app-icon lockup (mark on an ink rounded tile), for light surfaces
//
// Sized by `height` (px); width follows the mark's natural aspect ratio.

const C = { gold: '#C4841D', deep: '#A06B10', parch: '#F6F0E4', red: '#BE2528' }

// Inner obelisk geometry, authored in the original 48×202 brand coordinate space.
// `mono` collapses the palette to currentColor for watermark / loading use.
function Mark({ mono, tibeb = true }) {
  const gold = mono ? 'currentColor' : C.gold
  const deep = mono ? 'currentColor' : C.deep
  const parch = mono ? 'currentColor' : C.parch
  const red = mono ? 'currentColor' : C.red

  return (
    <>
      {/* Half-moon cap + tapered body */}
      <ellipse cx="18" cy="6" rx="10" ry="5" fill={deep} />
      <rect x="15" y="8" width="6" height="4" fill={gold} />
      <polygon points="3,12 33,12 36,190 0,190" fill={gold} />

      {/* Beam projections (floor dividers) */}
      <rect x="-4" y="34" width="44" height="3" rx="1" fill={deep} />
      <rect x="-3" y="62" width="42" height="3" rx="1" fill={deep} />
      <rect x="-2" y="90" width="40" height="3" rx="1" fill={deep} />
      <rect x="-1" y="118" width="39" height="3" rx="1" fill={deep} />
      <rect x="-1" y="146" width="39" height="3" rx="1" fill={deep} />

      {/* False windows → book pages */}
      <rect x="7" y="17" width="8" height="13" rx="1" fill={parch} opacity="0.9" />
      <rect x="21" y="17" width="8" height="13" rx="1" fill={parch} opacity="0.9" />
      <rect x="7" y="39" width="8" height="19" rx="1" fill={parch} opacity="0.85" />
      <rect x="21" y="39" width="8" height="19" rx="1" fill={parch} opacity="0.85" />
      <rect x="6" y="67" width="9" height="19" rx="1" fill={parch} opacity="0.82" />
      <rect x="21" y="67" width="9" height="19" rx="1" fill={parch} opacity="0.82" />
      <rect x="6" y="95" width="9" height="19" rx="1" fill={parch} opacity="0.8" />
      <rect x="22" y="95" width="9" height="19" rx="1" fill={parch} opacity="0.8" />
      <rect x="5" y="123" width="10" height="19" rx="1" fill={parch} opacity="0.78" />
      <rect x="22" y="123" width="10" height="19" rx="1" fill={parch} opacity="0.78" />

      {/* Centre spine = book-page metaphor + false door at base */}
      <line x1="18" y1="14" x2="18" y2="144" stroke={deep} strokeWidth="1.2" />
      <rect x="8" y="152" width="21" height="34" rx="2" fill={parch} opacity="0.72" />
      <rect x="6" y="150" width="25" height="3" rx="1" fill={deep} />

      {/* Base plate + tibeb strip (red–gold–red) */}
      <rect x="-6" y="190" width="48" height="8" rx="2" fill={deep} />
      {tibeb && (
        <>
          <rect x="-6" y="200" width="12" height="3" rx="1" fill={red} />
          <rect x="12" y="200" width="12" height="3" rx="1" fill={gold} />
          <rect x="30" y="200" width="12" height="3" rx="1" fill={red} />
        </>
      )}
    </>
  )
}

export default function Stele({
  height = 44,
  mono = false,
  tibeb = true,
  tile = false,
  className = '',
  title,
}) {
  const a11y = title
    ? { role: 'img', 'aria-label': title }
    : { 'aria-hidden': true }

  if (tile) {
    // App-icon lockup: mark centred on an ink rounded tile. For light surfaces.
    return (
      <svg
        width={height}
        height={height}
        viewBox="0 0 64 64"
        className={className}
        {...a11y}
      >
        <rect width="64" height="64" rx="14" fill="#1E1610" />
        <g transform="translate(22, 5) scale(0.28)">
          <Mark mono={mono} tibeb={false} />
        </g>
      </svg>
    )
  }

  // Bare mark. viewBox padded around the natural content bounds.
  const aspect = 58 / 209
  return (
    <svg
      width={height * aspect}
      height={height}
      viewBox="-9 -3 58 209"
      className={className}
      {...a11y}
    >
      <Mark mono={mono} tibeb={tibeb} />
    </svg>
  )
}
