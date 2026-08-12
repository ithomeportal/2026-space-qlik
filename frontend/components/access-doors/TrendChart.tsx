"use client"

import { useState } from "react"
import type { ScopedAccessTrendPoint } from "@/lib/scoped-access-api"
import { fmtDate } from "@/lib/scoped-access-api"

interface Props {
  points: ScopedAccessTrendPoint[]
  /** Scope name shown in the caption, e.g. "Operations" / "Pricing". */
  scopeLabel: string
}

const W = 720
const H = 200
const PAD_L = 36
const PAD_R = 16
const PAD_T = 16
const PAD_B = 32
const FS = 9

const GREEN = "#16A34A"
const RED = "#DC2626"
const GRID = "#E5E7EB"
const TEXT = "#6B7280"

/** Rolling 30-day On-Time vs Out-of-Time line. Same visual as the DFW/Admin
 *  charts; the scope caption is the only thing that varies. */
export function AccessTrendChart({ points, scopeLabel }: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null)

  if (points.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-lg border border-dashed border-[#E5E7EB] bg-white text-xs text-[#6B7280]">
        No events in the last 30 days.
      </div>
    )
  }

  const maxY = Math.max(
    1,
    ...points.map((p) => Math.max(p.on_time, p.out_of_time)),
  )
  const niceStep = niceTickStep(maxY)
  const yMax = Math.ceil(maxY / niceStep) * niceStep
  const ticks: number[] = []
  for (let v = 0; v <= yMax; v += niceStep) ticks.push(v)

  const plotW = W - PAD_L - PAD_R
  const plotH = H - PAD_T - PAD_B

  const xOf = (i: number) =>
    points.length === 1
      ? PAD_L + plotW / 2
      : PAD_L + (i * plotW) / (points.length - 1)
  const yOf = (v: number) => PAD_T + plotH - (v / yMax) * plotH

  const onTimePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${xOf(i).toFixed(1)} ${yOf(p.on_time).toFixed(1)}`)
    .join(" ")
  const outPath = points
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"} ${xOf(i).toFixed(1)} ${yOf(p.out_of_time).toFixed(1)}`,
    )
    .join(" ")

  const hovered = hoverIdx !== null ? points[hoverIdx] : null

  return (
    <div className="relative">
      <div className="mb-1 flex items-center gap-4 text-[10px] text-[#374151]">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-3 rounded-sm" style={{ background: GREEN }} />
          On Time
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-3 rounded-sm" style={{ background: RED }} />
          Out of Time
        </span>
        <span className="ml-auto text-[#9CA3AF]">
          {scopeLabel} · rolling 30 days · ignores date filter
        </span>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} width="100%" className="block">
        {ticks.map((t, i) => (
          <g key={`y-${i}`}>
            <line
              x1={PAD_L}
              x2={W - PAD_R}
              y1={yOf(t)}
              y2={yOf(t)}
              stroke={GRID}
              strokeWidth={0.5}
            />
            <text
              x={PAD_L - 4}
              y={yOf(t) + FS / 3}
              fontSize={FS}
              textAnchor="end"
              fill={TEXT}
            >
              {t}
            </text>
          </g>
        ))}

        {points.map((p, i) => {
          if (i % 3 !== 0 && i !== points.length - 1) return null
          const x = xOf(i)
          return (
            <text
              key={`x-${i}`}
              x={x}
              y={H - 10}
              fontSize={FS}
              textAnchor="middle"
              fill={TEXT}
            >
              {fmtShort(p.event_date)}
            </text>
          )
        })}

        <path d={onTimePath} fill="none" stroke={GREEN} strokeWidth={1.4} />
        <path d={outPath} fill="none" stroke={RED} strokeWidth={1.4} />

        {points.map((p, i) => (
          <g key={`pts-${i}`}>
            <circle cx={xOf(i)} cy={yOf(p.on_time)} r={1.8} fill={GREEN} />
            <circle cx={xOf(i)} cy={yOf(p.out_of_time)} r={1.8} fill={RED} />
          </g>
        ))}

        {hoverIdx !== null && (
          <line
            x1={xOf(hoverIdx)}
            x2={xOf(hoverIdx)}
            y1={PAD_T}
            y2={H - PAD_B}
            stroke="#9CA3AF"
            strokeWidth={0.5}
            strokeDasharray="2 2"
          />
        )}

        {points.map((_p, i) => {
          const prev = i === 0 ? xOf(i) : (xOf(i - 1) + xOf(i)) / 2
          const next =
            i === points.length - 1 ? xOf(i) : (xOf(i) + xOf(i + 1)) / 2
          return (
            <rect
              key={`hit-${i}`}
              x={prev}
              y={PAD_T}
              width={Math.max(2, next - prev)}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setHoverIdx(i)}
              onMouseLeave={() => setHoverIdx((h) => (h === i ? null : h))}
            />
          )
        })}
      </svg>

      {hovered && hoverIdx !== null && (
        <div
          className="pointer-events-none absolute top-6 rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-[10px] shadow-md"
          style={{
            left: `${(xOf(hoverIdx) / W) * 100}%`,
            transform: "translateX(-50%)",
          }}
        >
          <div className="mb-0.5 font-semibold text-[#111827]">
            {fmtDate(hovered.event_date)}
          </div>
          <div style={{ color: GREEN }}>On Time: {hovered.on_time}</div>
          <div style={{ color: RED }}>Out of Time: {hovered.out_of_time}</div>
        </div>
      )}
    </div>
  )
}

function niceTickStep(maxY: number): number {
  if (maxY <= 5) return 1
  if (maxY <= 10) return 2
  if (maxY <= 30) return 5
  if (maxY <= 60) return 10
  if (maxY <= 120) return 20
  if (maxY <= 300) return 50
  return Math.pow(10, Math.floor(Math.log10(maxY)))
}

function fmtShort(iso: string): string {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return iso
  const month = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ][parseInt(m[2], 10) - 1]
  return `${parseInt(m[3], 10)} ${month}`
}
