// One-shot falling "tibeb fragments" in the Tigrayan palette.
// All positioning/color/timing lives in static .cfx nth-child CSS rules;
// the global prefers-reduced-motion rule disables it entirely.
export default function Confetti() {
  return (
    <div className="cfx" aria-hidden="true">
      {Array.from({ length: 24 }, (_, i) => <i key={i} />)}
    </div>
  )
}
