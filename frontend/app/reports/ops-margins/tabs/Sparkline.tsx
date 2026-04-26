"use client"

interface Props {
  values: Array<number | null>
  width?: number
  height?: number
  stroke?: string
}

export function Sparkline({
  values,
  width = 80,
  height = 22,
  stroke = "#1B3A5C",
}: Props) {
  const finite = values.filter((v) => v !== null && Number.isFinite(v as number)) as number[]
  if (finite.length < 2) {
    return <span className="inline-block text-[10px] text-[#9CA3AF]">—</span>
  }
  const min = Math.min(...finite, 0)
  const max = Math.max(...finite, 0)
  const span = Math.max(1e-6, max - min)
  const xStep = values.length > 1 ? width / (values.length - 1) : 0
  const points = values.map((v, i) => {
    const y =
      v === null || !Number.isFinite(v)
        ? height / 2
        : height - ((v - min) / span) * height
    return `${i * xStep},${y}`
  })
  // zero baseline
  const zeroY = height - ((0 - min) / span) * height
  return (
    <svg
      width={width}
      height={height}
      className="inline-block"
      role="img"
      aria-label={`trend ${finite.length} points`}
    >
      <line
        x1={0}
        y1={zeroY}
        x2={width}
        y2={zeroY}
        stroke="#E5E7EB"
        strokeWidth={1}
        strokeDasharray="2 2"
      />
      <polyline
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        points={points.join(" ")}
      />
    </svg>
  )
}
