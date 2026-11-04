// Inline 8-week #Loads mini chart.
export function Sparkline({ values }: { values: number[] }) {
  if (!values || values.length === 0) {
    return <span className="text-[10px] text-[#6B7280]">—</span>
  }
  const max = Math.max(1, ...values)
  const w = 80
  const h = 18
  const step = w / Math.max(1, values.length)
  const points = values
    .map((v, i) => {
      const x = i * step + step / 2
      const y = h - (v / max) * h
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(" ")
  const last = values[values.length - 1]
  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      className="inline-block"
      role="img"
      aria-label={`8-week loads sparkline, latest ${last}`}
    >
      <polyline
        points={points}
        fill="none"
        stroke="#1B3A5C"
        strokeWidth={1.4}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={(values.length - 1) * step + step / 2}
        cy={h - (last / max) * h}
        r={1.8}
        fill="#1B3A5C"
      />
    </svg>
  )
}
