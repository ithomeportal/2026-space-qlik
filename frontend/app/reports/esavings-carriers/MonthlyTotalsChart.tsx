"use client"

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
  { key: "volume", label: "Volume", color: "#06B6D4", axis: "right" },
]

// SVG geometry.
const WIDTH = 640
const HEIGHT = 320
const MARGIN = { top: 24, right: 118, bottom: 40, left: 64 }
const INNER_WIDTH = WIDTH - MARGIN.left - MARGIN.right
const INNER_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom

// "Nice" round number rounded up/down to a power of 10 multiple.
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

export function MonthlyTotalsChart({ rows, loading }: MonthlyTotalsChartProps) {
  const hasData = rows.length > 0

  // Domains
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

  // Build left-axis ticks.
  const leftTicks: number[] = []
  for (let v = leftMin; v <= leftMax + leftStep * 0.001; v += leftStep) {
    leftTicks.push(Math.round(v * 1e6) / 1e6)
  }
  const rightTicks: number[] = []
  for (let v = rightMin; v <= rightMax + rightStep * 0.001; v += rightStep) {
    rightTicks.push(Math.round(v * 1e6) / 1e6)
  }

  // Zero line (baseline) on the left axis.
  const zeroY = leftMin <= 0 && leftMax >= 0 ? yLeft(0) : null

  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="border-b border-[#E5E7EB] bg-[#F9FAFB] px-4 py-2 text-sm font-semibold text-[#1B3A5C]">
        Totals by Month
        <span className="ml-2 text-xs font-normal text-[#6B7280]">
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
          <div className="flex h-[260px] items-center justify-center text-xs text-[#9CA3AF]">
            No trend data for the current filters
          </div>
        )}
        {hasData && (
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            role="img"
            aria-label="Monthly savings, overpay, net variance and volume trend"
            className="w-full"
          >
            {/* Grid + left-axis ticks */}
            {leftTicks.map((t) => {
              const y = yLeft(t)
              return (
                <g key={`lt-${t}`}>
                  <line
                    x1={MARGIN.left}
                    x2={WIDTH - MARGIN.right}
                    y1={y}
                    y2={y}
                    stroke="#F3F4F6"
                    strokeWidth={1}
                  />
                  <text
                    x={MARGIN.left - 6}
                    y={y}
                    textAnchor="end"
                    dominantBaseline="central"
                    fontSize={10}
                    fill="#6B7280"
                  >
                    ${formatDollarTick(t)}
                  </text>
                </g>
              )
            })}
            {/* Right-axis ticks */}
            {rightTicks.map((t) => {
              const y = yRight(t)
              return (
                <text
                  key={`rt-${t}`}
                  x={WIDTH - MARGIN.right + 6}
                  y={y}
                  textAnchor="start"
                  dominantBaseline="central"
                  fontSize={10}
                  fill="#06B6D4"
                >
                  {formatCountTick(t)}
                </text>
              )
            })}

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
                y={HEIGHT - MARGIN.bottom + 16}
                textAnchor="middle"
                fontSize={10}
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
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}

            {/* Series points */}
            {SERIES.map((s) =>
              rows.map((r, i) => {
                const x = xAt(i)
                const y = s.axis === "left" ? yLeft(r[s.key]) : yRight(r[s.key])
                return (
                  <circle
                    key={`pt-${s.key}-${i}`}
                    cx={x}
                    cy={y}
                    r={3}
                    fill="#FFFFFF"
                    stroke={s.color}
                    strokeWidth={1.5}
                  />
                )
              }),
            )}

            {/* Legend on the right */}
            {SERIES.map((s, i) => {
              const legendX = WIDTH - MARGIN.right + 28
              const legendY = MARGIN.top + 8 + i * 18
              return (
                <g key={`legend-${s.key}`}>
                  <line
                    x1={legendX}
                    x2={legendX + 18}
                    y1={legendY}
                    y2={legendY}
                    stroke={s.color}
                    strokeWidth={2}
                  />
                  <circle
                    cx={legendX + 9}
                    cy={legendY}
                    r={3}
                    fill="#FFFFFF"
                    stroke={s.color}
                    strokeWidth={1.5}
                  />
                  <text
                    x={legendX + 24}
                    y={legendY}
                    dominantBaseline="central"
                    fontSize={10}
                    fill="#374151"
                  >
                    {s.label}
                  </text>
                </g>
              )
            })}

            {/* Axis titles */}
            <text
              transform={`rotate(-90)`}
              x={-(MARGIN.top + INNER_HEIGHT / 2)}
              y={14}
              textAnchor="middle"
              fontSize={10}
              fill="#6B7280"
            >
              USD
            </text>
            <text
              transform={`rotate(-90)`}
              x={-(MARGIN.top + INNER_HEIGHT / 2)}
              y={WIDTH - 4}
              textAnchor="middle"
              fontSize={10}
              fill="#06B6D4"
            >
              Volume (loads)
            </text>
          </svg>
        )}
      </div>
    </div>
  )
}
