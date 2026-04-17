"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import type { SavingsMonthlyTotals } from "@/lib/api"

interface MonthlyTotalsChartProps {
  rows: SavingsMonthlyTotals[]
  loading?: boolean
}

type SeriesKey = "total_savings" | "total_overpay" | "net_variance" | "volume"

interface Series {
  key: SeriesKey
  label: string
  color: string
  axis: "left" | "right"
}

const SERIES: Series[] = [
  { key: "total_savings", label: "Total Savings", color: "#0F766E", axis: "left" },
  { key: "total_overpay", label: "Total Overpay", color: "#D4A373", axis: "left" },
  { key: "net_variance", label: "Net Variance", color: "#9333EA", axis: "left" },
  { key: "volume", label: "Volume", color: "#DC2626", axis: "right" },
]

// SVG geometry — legend lives as HTML below the plot so we can keep the plot flat.
const WIDTH = 720
const HEIGHT = 200
const MARGIN = { top: 14, right: 56, bottom: 26, left: 56 }
const INNER_WIDTH = WIDTH - MARGIN.left - MARGIN.right
const INNER_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom

// All SVG labels share the same size so the chart reads at one density.
const FS_TICK = 7.5
const FS_TOOLTIP = 7.5
const FS_POINT = 7.5

const CURRENCY = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const COUNT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 })

function niceStep(range: number, ticks = 5): number {
  if (range <= 0) return 1
  const raw = range / ticks
  const pow = Math.pow(10, Math.floor(Math.log10(raw)))
  const n = raw / pow
  if (n < 1.5) return 1 * pow
  if (n < 3) return 2 * pow
  if (n < 7) return 5 * pow
  return 10 * pow
}

function niceDomain(min: number, max: number, ticks = 5): [number, number, number] {
  if (min === max) {
    const pad = Math.abs(min) || 1
    min -= pad
    max += pad
  }
  const step = niceStep(max - min, ticks)
  const niceMin = Math.floor(min / step) * step
  const niceMax = Math.ceil(max / step) * step
  return [niceMin, niceMax, step]
}

function formatDollarTick(v: number): string {
  const abs = Math.abs(v)
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`
  if (abs >= 1_000) return `${(v / 1_000).toFixed(0)}k`
  return `${v.toFixed(0)}`
}

function formatCountTick(v: number): string {
  const abs = Math.abs(v)
  if (abs >= 1_000) return `${(v / 1_000).toFixed(1).replace(/\.0$/, "")}k`
  return `${v.toFixed(0)}`
}

function formatMonthLabel(iso: string): string {
  const d = new Date(`${iso.slice(0, 10)}T00:00:00Z`)
  return d.toLocaleDateString("en-US", {
    month: "short",
    year: "2-digit",
    timeZone: "UTC",
  })
}

function formatSeriesValue(key: SeriesKey, v: number): string {
  if (key === "volume") return COUNT.format(v)
  return CURRENCY.format(v)
}

export function MonthlyTotalsChart({ rows, loading }: MonthlyTotalsChartProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)
  const hasData = rows.length > 0

  const leftValues = rows.flatMap((r) => [
    r.total_savings,
    r.total_overpay,
    r.net_variance,
  ])
  const rightValues = rows.map((r) => r.volume)

  const [leftMin, leftMax, leftStep] = hasData
    ? niceDomain(Math.min(0, ...leftValues), Math.max(0, ...leftValues))
    : [-1, 1, 1]
  const [rightMin, rightMax, rightStep] = hasData
    ? niceDomain(0, Math.max(1, ...rightValues))
    : [0, 1, 1]

  const n = rows.length
  const xAt = (i: number): number =>
    n <= 1
      ? MARGIN.left + INNER_WIDTH / 2
      : MARGIN.left + (i / (n - 1)) * INNER_WIDTH
  const yLeft = (v: number): number =>
    MARGIN.top + INNER_HEIGHT * (1 - (v - leftMin) / (leftMax - leftMin))
  const yRight = (v: number): number =>
    MARGIN.top + INNER_HEIGHT * (1 - (v - rightMin) / (rightMax - rightMin))

  const seriesPath = (s: Series): string => {
    const pts = rows.map((r, i) => {
      const x = xAt(i)
      const y = s.axis === "left" ? yLeft(r[s.key]) : yRight(r[s.key])
      return `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`
    })
    return pts.join(" ")
  }

  const leftTicks: number[] = []
  for (let v = leftMin; v <= leftMax + leftStep * 0.001; v += leftStep) {
    leftTicks.push(Math.round(v * 1e6) / 1e6)
  }
  const rightTicks: number[] = []
  for (let v = rightMin; v <= rightMax + rightStep * 0.001; v += rightStep) {
    rightTicks.push(Math.round(v * 1e6) / 1e6)
  }

  const zeroY = leftMin <= 0 && leftMax >= 0 ? yLeft(0) : null

  // Tooltip geometry — computed only when hovering a point.
  const TOOLTIP_WIDTH = 150
  const TOOLTIP_HEIGHT = 12 + SERIES.length * 12
  let tooltipX = 0
  let tooltipY = 0
  if (hoverIdx !== null && rows[hoverIdx]) {
    const px = xAt(hoverIdx)
    tooltipX =
      px + 10 + TOOLTIP_WIDTH > WIDTH - MARGIN.right
        ? px - 10 - TOOLTIP_WIDTH
        : px + 10
    tooltipY = Math.max(MARGIN.top, MARGIN.top + 4)
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-1.5 text-xs font-semibold text-[#1B3A5C]">
        Totals by Month
        <span className="ml-2 text-[10px] font-normal text-[#6B7280]">
          Last {rows.length || 9} months
        </span>
      </div>
      <div className="relative p-3">
        {loading && !hasData && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        )}
        {!loading && !hasData && (
          <div className="flex h-[160px] items-center justify-center text-[10px] text-[#9CA3AF]">
            No trend data for the current filters
          </div>
        )}
        {hasData && (
          <>
            <div className="mb-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 px-1 text-[9px] text-[#374151]">
              {SERIES.map((s) => (
                <div key={`lg-${s.key}`} className="flex items-center gap-1">
                  <span
                    className="inline-block h-[2px] w-3 rounded-full"
                    style={{ backgroundColor: s.color }}
                  />
                  <span
                    className="inline-block h-1.5 w-1.5 rounded-full border"
                    style={{ borderColor: s.color, backgroundColor: "#FFFFFF" }}
                  />
                  <span>
                    {s.label}
                    {s.axis === "right" && (
                      <span className="ml-0.5 text-[8px] text-[#9CA3AF]">(right)</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
            <svg
              viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
              role="img"
              aria-label="Monthly savings, overpay, net variance and volume trend"
              className="w-full"
              onMouseLeave={() => setHoverIdx(null)}
            >
              {/* Fine background grid — horizontals at each left-axis tick, verticals at each month */}
              {leftTicks.map((t) => (
                <line
                  key={`h-${t}`}
                  x1={MARGIN.left}
                  x2={WIDTH - MARGIN.right}
                  y1={yLeft(t)}
                  y2={yLeft(t)}
                  stroke="#F3F4F6"
                  strokeWidth={1}
                />
              ))}
              {rows.map((r, i) => (
                <line
                  key={`v-${r.month_date}`}
                  x1={xAt(i)}
                  x2={xAt(i)}
                  y1={MARGIN.top}
                  y2={HEIGHT - MARGIN.bottom}
                  stroke="#F3F4F6"
                  strokeWidth={1}
                  strokeDasharray="1 3"
                />
              ))}

              {/* Left-axis tick labels */}
              {leftTicks.map((t) => (
                <text
                  key={`ltl-${t}`}
                  x={MARGIN.left - 5}
                  y={yLeft(t)}
                  textAnchor="end"
                  dominantBaseline="central"
                  fontSize={FS_TICK}
                  fill="#6B7280"
                >
                  ${formatDollarTick(t)}
                </text>
              ))}
              {/* Right-axis tick labels (colored to match Volume) */}
              {rightTicks.map((t) => (
                <text
                  key={`rtl-${t}`}
                  x={WIDTH - MARGIN.right + 5}
                  y={yRight(t)}
                  textAnchor="start"
                  dominantBaseline="central"
                  fontSize={FS_TICK}
                  fill="#DC2626"
                >
                  {formatCountTick(t)}
                </text>
              ))}

              {/* Zero baseline on left axis */}
              {zeroY !== null && (
                <line
                  x1={MARGIN.left}
                  x2={WIDTH - MARGIN.right}
                  y1={zeroY}
                  y2={zeroY}
                  stroke="#D1D5DB"
                  strokeWidth={1}
                />
              )}

              {/* Left + right axes */}
              <line
                x1={MARGIN.left}
                x2={MARGIN.left}
                y1={MARGIN.top}
                y2={HEIGHT - MARGIN.bottom}
                stroke="#E5E7EB"
                strokeWidth={1}
              />
              <line
                x1={WIDTH - MARGIN.right}
                x2={WIDTH - MARGIN.right}
                y1={MARGIN.top}
                y2={HEIGHT - MARGIN.bottom}
                stroke="#E5E7EB"
                strokeWidth={1}
              />

              {/* Month labels on X */}
              {rows.map((r, i) => (
                <text
                  key={`x-${r.month_date}`}
                  x={xAt(i)}
                  y={HEIGHT - MARGIN.bottom + 12}
                  textAnchor="middle"
                  fontSize={FS_TICK}
                  fill="#6B7280"
                >
                  {formatMonthLabel(r.month_date)}
                </text>
              ))}

              {/* Series paths */}
              {SERIES.map((s) => (
                <path
                  key={`path-${s.key}`}
                  d={seriesPath(s)}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={1.6}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ))}

              {/* Series points + value labels (tiny, above for positive / below for negative) */}
              {SERIES.map((s) =>
                rows.map((r, i) => {
                  const x = xAt(i)
                  const raw = r[s.key]
                  const y = s.axis === "left" ? yLeft(raw) : yRight(raw)
                  const label =
                    s.key === "volume" ? formatCountTick(raw) : formatDollarTick(raw)
                  const above = raw >= 0
                  const labelY = above ? y - 5 : y + 11
                  return (
                    <g key={`pt-${s.key}-${i}`}>
                      <circle
                        cx={x}
                        cy={y}
                        r={hoverIdx === i ? 3.5 : 2.5}
                        fill="#FFFFFF"
                        stroke={s.color}
                        strokeWidth={1.5}
                      />
                      <text
                        x={x}
                        y={labelY}
                        textAnchor="middle"
                        fontSize={FS_POINT}
                        fontWeight={500}
                        fill={s.color}
                      >
                        {label}
                      </text>
                    </g>
                  )
                }),
              )}

              {/* Hover crosshair + invisible hit zones per month column */}
              {hoverIdx !== null && rows[hoverIdx] && (
                <line
                  x1={xAt(hoverIdx)}
                  x2={xAt(hoverIdx)}
                  y1={MARGIN.top}
                  y2={HEIGHT - MARGIN.bottom}
                  stroke="#9CA3AF"
                  strokeWidth={1}
                  strokeDasharray="2 2"
                />
              )}
              {rows.map((_, i) => {
                const step = n > 1 ? INNER_WIDTH / (n - 1) : INNER_WIDTH
                return (
                  <rect
                    key={`hz-${i}`}
                    x={xAt(i) - step / 2}
                    y={MARGIN.top}
                    width={step}
                    height={INNER_HEIGHT}
                    fill="transparent"
                    onMouseEnter={() => setHoverIdx(i)}
                  />
                )
              })}

              {/* Tooltip */}
              {hoverIdx !== null && rows[hoverIdx] && (
                <g pointerEvents="none">
                  <rect
                    x={tooltipX}
                    y={tooltipY}
                    width={TOOLTIP_WIDTH}
                    height={TOOLTIP_HEIGHT}
                    rx={4}
                    ry={4}
                    fill="#FFFFFF"
                    stroke="#E5E7EB"
                    strokeWidth={1}
                  />
                  <text
                    x={tooltipX + 8}
                    y={tooltipY + 11}
                    fontSize={FS_TOOLTIP}
                    fontWeight={600}
                    fill="#111827"
                  >
                    {formatMonthLabel(rows[hoverIdx].month_date)}
                  </text>
                  {SERIES.map((s, i) => {
                    const textY = tooltipY + 11 + (i + 1) * 12
                    return (
                      <g key={`tip-${s.key}`}>
                        <circle
                          cx={tooltipX + 10}
                          cy={textY - 3}
                          r={2.5}
                          fill="#FFFFFF"
                          stroke={s.color}
                          strokeWidth={1.3}
                        />
                        <text
                          x={tooltipX + 18}
                          y={textY}
                          fontSize={FS_TOOLTIP}
                          fill="#374151"
                        >
                          {s.label}
                        </text>
                        <text
                          x={tooltipX + TOOLTIP_WIDTH - 8}
                          y={textY}
                          textAnchor="end"
                          fontSize={FS_TOOLTIP}
                          fontWeight={500}
                          fill="#111827"
                        >
                          {formatSeriesValue(s.key, rows[hoverIdx][s.key])}
                        </text>
                      </g>
                    )
                  })}
                </g>
              )}
            </svg>
          </>
        )}
      </div>
    </div>
  )
}
