// Hand-drawn stroke icon set on a 24×24 grid — no external icon libraries.
// All glyphs inherit currentColor so CSS controls theming.

const bubble = (
  <>
    <path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5c-1.6 0-3.1-.4-4.4-1.2L3.5 20l1.2-4.6A8.5 8.5 0 1 1 21 11.5z" />
    <path d="M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01" />
  </>
)

const PATHS = {
  // ── Navigation / content types ──
  home: (
    <>
      <path d="M3.5 11 12 4l8.5 7" />
      <path d="M5.5 9.5V20h13V9.5" />
      <path d="M9.5 20v-5.5h5V20" />
    </>
  ),
  quiz: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.3 12.4l2.5 2.5 5-5.3" />
    </>
  ),
  cards: (
    <>
      <rect x="8" y="3.5" width="12.5" height="12.5" rx="2.5" />
      <rect x="3.5" y="8" width="12.5" height="12.5" rx="2.5" />
    </>
  ),
  notes: (
    <>
      <rect x="4.5" y="3.5" width="15" height="17" rx="2.5" />
      <path d="M8.5 9h7M8.5 12.5h7M8.5 16h4.5" />
    </>
  ),
  tutor: bubble,
  chat: bubble,
  history: (
    <>
      <path d="M3.5 12a8.5 8.5 0 1 0 8.5-8.5c-2.4 0-4.6 1-6.2 2.6L3.5 8.5" />
      <path d="M3.5 3.5v5h5" />
      <path d="M12 8.2v4.3l2.7 1.6" />
    </>
  ),
  sparkle: (
    <path d="M12 3.5c.7 4.4 3.4 7 8 8.5-4.6 1.5-7.3 4.1-8 8.5-.7-4.4-3.4-7-8-8.5 4.6-1.5 7.3-4.1 8-8.5z" />
  ),

  // ── Subjects ──
  biology: (
    <>
      <path d="M5 19.5C5 9.5 10.5 4.5 19.5 4.5c0 10-5 15-14.5 15z" />
      <path d="M5 19.5C8 13 11.5 9.5 16 7" />
    </>
  ),
  chemistry: (
    <>
      <path d="M10 3.5v6L4.7 18.6a2 2 0 0 0 1.8 2.9h11a2 2 0 0 0 1.8-2.9L14 9.5v-6" />
      <path d="M8.5 3.5h7" />
      <path d="M7.3 15h9.4" />
    </>
  ),
  physics: (
    <>
      <ellipse cx="12" cy="12" rx="8.5" ry="3.6" />
      <ellipse cx="12" cy="12" rx="8.5" ry="3.6" transform="rotate(62 12 12)" />
      <circle cx="12" cy="12" r="1.1" fill="currentColor" stroke="none" />
    </>
  ),
  maths: (
    <>
      <circle cx="12" cy="4.8" r="1.6" />
      <path d="M11 6.2 5 20.5M13 6.2l6 14.3" />
      <path d="M7 15.7a10.5 10.5 0 0 0 10 0" />
    </>
  ),
  english: (
    <>
      <path d="M12 6.8C10.2 5 7.6 4.2 3.8 4.2v14.6c3.8 0 6.4.8 8.2 2.6 1.8-1.8 4.4-2.6 8.2-2.6V4.2c-3.8 0-6.4.8-8.2 2.6z" />
      <path d="M12 6.8v14.6" />
    </>
  ),
  civics: (
    <>
      <path d="M3.5 9.3 12 4l8.5 5.3" />
      <path d="M6 11v7M12 11v7M18 11v7" />
      <path d="M3.5 20.5h17" />
    </>
  ),
  economics: (
    <>
      <path d="M4.5 20.5v-5.5M10 20.5v-9M15.5 20.5v-6.5" />
      <path d="M4.5 10.5 10 6l4 3 5.5-4.5" />
      <path d="M16 4.5h3.5V8" />
    </>
  ),
  geography: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M3.5 12h17" />
      <ellipse cx="12" cy="12" rx="3.8" ry="8.5" />
    </>
  ),
  'history-subject': (
    <>
      <path d="M6.5 3.5h11M6.5 20.5h11" />
      <path d="M7.5 3.5v2.8L12 12l-4.5 5.7v2.8" />
      <path d="M16.5 3.5v2.8L12 12l4.5 5.7v2.8" />
    </>
  ),
  business: (
    <>
      <rect x="3.5" y="7.5" width="17" height="13" rx="2.2" />
      <path d="M9 7.5V5.7a2.2 2.2 0 0 1 2.2-2.2h1.6A2.2 2.2 0 0 1 15 5.7v1.8" />
      <path d="M3.5 13h17" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4.7" />
      <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
    </>
  ),

  // ── Actions / status ──
  school: (
    <>
      <path d="M2.5 9.7 12 4.5l9.5 5.2L12 14.9z" />
      <path d="M6.3 12.4v4.2c0 1.6 2.6 2.9 5.7 2.9s5.7-1.3 5.7-2.9v-4.2" />
      <path d="M21.5 9.7v5.3" />
    </>
  ),
  send: (
    <>
      <path d="M12 19.5V5" />
      <path d="M6 11 12 5l6 6" />
    </>
  ),
  check: <path d="M4.5 12.5l5 5L19.5 7" />,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  alert: (
    <>
      <path d="M12 3.7 21.3 19.5a1 1 0 0 1-.86 1.5H3.56a1 1 0 0 1-.86-1.5z" />
      <path d="M12 9.5v4.2" />
      <path d="M12 17h.01" />
    </>
  ),
  'wifi-off': (
    <>
      <path d="M3.5 3.5l17 17" />
      <path d="M5 9.5a13 13 0 0 1 4-2.4M2 6.3a17 17 0 0 1 4.8-2.9" />
      <path d="M8.2 12.8a8 8 0 0 1 7.6-.6M19.8 9.5a13 13 0 0 0-3-2" />
      <path d="M11 16.2a3.5 3.5 0 0 1 4 .5" />
      <path d="M12 20h.01" />
    </>
  ),
  flame: (
    <path d="M12 3.5c.5 2.9-.8 4.6-2.3 6.3C8.2 11.5 7 13.1 7 15.1a5 5 0 0 0 10 0c0-1.5-.6-2.9-1.5-4.2-.5.9-1.1 1.5-2 2 .6-3-.2-6.3-1.5-9.4z" />
  ),
  trophy: (
    <>
      <path d="M7 4.5h10v5.3a5 5 0 0 1-10 0z" />
      <path d="M7 6H4a3 3 0 0 0 3.2 3.9M17 6h3a3 3 0 0 1-3.2 3.9" />
      <path d="M12 14.8v3.2M8.3 20.5h7.4" />
    </>
  ),
  star: (
    <path d="M12 3.8l2.4 5 5.4.7-4 3.8 1 5.4L12 16.1l-4.8 2.6 1-5.4-4-3.8 5.4-.7z" />
  ),
  'chevron-left': <path d="M14.5 6l-6 6 6 6" />,
  'chevron-right': <path d="M9.5 6l6 6-6 6" />,
  plus: <path d="M12 5.5v13M5.5 12h13" />,
  retry: (
    <>
      <path d="M20.5 12a8.5 8.5 0 1 1-8.5-8.5c2.4 0 4.6 1 6.2 2.6l2.3 2.4" />
      <path d="M20.5 3.5v5H16" />
    </>
  ),
  'file-text': (
    <>
      <path d="M13.5 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z" />
      <path d="M13.5 3.5V9H19" />
      <path d="M9 13.5h6M9 17h4.5" />
    </>
  ),
  'arrow-right': (
    <>
      <path d="M4.5 12h15" />
      <path d="M13.5 6l6 6-6 6" />
    </>
  ),
  lock: (
    <>
      <rect x="4.5" y="10.5" width="15" height="10" rx="2.2" />
      <path d="M8 10.5V7.7a4 4 0 0 1 8 0v2.8" />
    </>
  ),
  logout: (
    <>
      <path d="M9 20.5H5.5a2 2 0 0 1-2-2V5.5a2 2 0 0 1 2-2H9" />
      <path d="M15.5 17l5-5-5-5" />
      <path d="M20.5 12H9" />
    </>
  ),
}

export default function Icon({ name, size = 20, stroke = 1.75, className = '' }) {
  const paths = PATHS[name]
  if (!paths) return null
  return (
    <svg
      className={className ? `ico ${className}` : 'ico'}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths}
    </svg>
  )
}
