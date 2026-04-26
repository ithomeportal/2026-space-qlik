"use client"

import { Loader2 } from "lucide-react"
import { fmtPct, fmtUsd } from "../../ops-margins/format"
import { DCErrorBanner } from "../ErrorBanner"
import {
  useDCConcentration,
  type DCPanelFilters,
} from "@/lib/ops-direct-compare-api"

const SLICE_COLORS = [
  "#1E3A5F",
  "#B69768",
  "#7C3AED",
  "#0891B2",
  "#16A34A",
  "#9CA3AF",
]

interface Props {
  panel: "p1" | "p2"
  filters: DCPanelFilters
  title: string
}

export function ConcentrationPie({ panel, filters, title }: Props) {
  const { data, isLoading, error } = useDCConcentration(panel, filters, 5)
  const slices = data?.data ?? []
  const total = data?.meta?.total_profit ?? 0

  // SVG donut math
  const radius = 70
  const innerR = 42
  const cx = 100
  const cy = 100
  let cursor = -Math.PI / 2 // start at 12 o'clock
  const arcs = slices.map((s, idx) => {
    const pct = (s.profit / Math.max(total, 1e-6)) || 0
    const angle = pct * Math.PI * 2
    const start = cursor
    const end = cursor + angle
    cursor = end
    const x1 = cx + radius * Math.cos(start)
    const y1 = cy + radius * Math.sin(start)
    const x2 = cx + radius * Math.cos(end)
    const y2 = cy + radius * Math.sin(end)
    const ix1 = cx + innerR * Math.cos(start)
    const iy1 = cy + innerR * Math.sin(start)
    const ix2 = cx + innerR * Math.cos(end)
    const iy2 = cy + innerR * Math.sin(end)
    const large = angle > Math.PI ? 1 : 0
    const path = `M ${x1} ${y1} A ${radius} ${radius} 0 ${large} 1 ${x2} ${y2} L ${ix2} ${iy2} A ${innerR} ${innerR} 0 ${large} 0 ${ix1} ${iy1} Z`
    return {
      key: `${s.customer}-${idx}`,
      d: path,
      color: SLICE_COLORS[idx % SLICE_COLORS.length],
      label: s.customer,
      pct: (s.concentration_pct ?? pct * 100) || 0,
      profit: s.profit,
    }
  })

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <DCErrorBanner errors={[error]} label={title} />
      <h3 className="mb-2 text-sm font-semibold text-[#1B3A5C]">{title}</h3>
      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : slices.length === 0 ? (
        <div className="text-xs text-[#6B7280]">No data in window.</div>
      ) : (
        <div className="flex items-start gap-4">
          <svg viewBox="0 0 200 200" className="h-44 w-44 shrink-0">
            {arcs.map((a) =>
              a.pct === 100 ? (
                <circle
                  key={a.key}
                  cx={cx}
                  cy={cy}
                  r={(radius + innerR) / 2}
                  fill="none"
                  stroke={a.color}
                  strokeWidth={radius - innerR}
                />
              ) : (
                <path key={a.key} d={a.d} fill={a.color} />
              ),
            )}
            <text
              x={cx}
              y={cy + 4}
              textAnchor="middle"
              className="fill-[#374151] text-[11px] font-semibold"
            >
              {fmtUsd(total)}
            </text>
          </svg>
          <div className="flex-1 min-w-0 space-y-1.5">
            {arcs.map((a) => (
              <div key={a.key} className="flex items-center gap-2 text-xs">
                <span
                  className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ background: a.color }}
                />
                <span className="flex-1 truncate text-[#374151]" title={a.label}>
                  {a.label}
                </span>
                <span className="tabular-nums text-[#6B7280]">{fmtPct(a.pct)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
