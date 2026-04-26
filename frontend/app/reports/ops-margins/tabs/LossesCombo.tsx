"use client"

import { Loader2 } from "lucide-react"
import {
  useOpsLossesByMonth,
  useOpsLossesByWeek,
  type OpsFilters,
  type OpsLossesByBucket,
} from "@/lib/ops-margins-api"
import { OpsErrorBanner } from "../ErrorBanner"
import { fmtCount, fmtUsd } from "../format"

export function LossesCombo({ filters }: { filters: OpsFilters }) {
  const month = useOpsLossesByMonth(filters, 8)
  const week = useOpsLossesByWeek(filters, 8)

  return (
    <div className="space-y-3">
      <OpsErrorBanner errors={[month.error, week.error]} label="Losses combo" />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <ComboCard
          title="Losses by Month"
          subtitle="last 8 months including this month"
          loading={month.isLoading}
          rows={month.data?.data ?? []}
          fmtLabel={(b) => (b ?? "").slice(0, 7)}
        />
        <ComboCard
          title="Losses by Week"
          subtitle="last 8 weeks including this week"
          loading={week.isLoading}
          rows={week.data?.data ?? []}
          fmtLabel={(b) => (b ?? "").slice(5)}
        />
      </div>
    </div>
  )
}

function ComboCard({
  title,
  subtitle,
  loading,
  rows,
  fmtLabel,
}: {
  title: string
  subtitle: string
  loading: boolean
  rows: OpsLossesByBucket[]
  fmtLabel: (b: string | null) => string
}) {
  const profits = rows.map((r) => r.profit)
  const loads = rows.map((r) => r.loads)
  const minP = Math.min(0, ...profits)
  const maxL = Math.max(1, ...loads)
  const W = Math.max(rows.length * 60, 320)

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-[#1B3A5C]">{title}</h3>
          <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">{subtitle}</div>
        </div>
      </div>
      {loading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : rows.length === 0 ? (
        <div className="text-xs text-[#6B7280]">No losses in window.</div>
      ) : (
        <svg viewBox={`0 0 ${W} 200`} className="h-48 w-full">
          {/* zero baseline */}
          <line x1={0} y1={150} x2={W} y2={150} stroke="#E5E7EB" />
          {rows.map((r, i) => {
            const barW = Math.max(20, W / rows.length - 12)
            const x = i * (W / rows.length) + (W / rows.length - barW) / 2
            // bars (negative profit, draw downward from baseline 150)
            const range = Math.max(1, Math.abs(minP))
            const barH = (Math.abs(r.profit) / range) * 110
            return (
              <g key={i}>
                <rect
                  x={x}
                  y={150}
                  width={barW}
                  height={barH}
                  fill="#DC2626"
                  fillOpacity={0.85}
                />
                <text
                  x={x + barW / 2}
                  y={150 + barH + 12}
                  textAnchor="middle"
                  className="text-[9px] fill-[#7F1D1D]"
                >
                  {fmtUsd(r.profit)}
                </text>
                <text
                  x={x + barW / 2}
                  y={195}
                  textAnchor="middle"
                  className="text-[9px] fill-[#6B7280]"
                >
                  {fmtLabel(r.bucket)}
                </text>
              </g>
            )
          })}
          {/* loads line */}
          <polyline
            fill="none"
            stroke="#1B3A5C"
            strokeWidth={1.8}
            points={rows
              .map((r, i) => {
                const x = i * (W / rows.length) + W / rows.length / 2
                const y = 145 - (r.loads / maxL) * 130
                return `${x},${y}`
              })
              .join(" ")}
          />
          {rows.map((r, i) => {
            const x = i * (W / rows.length) + W / rows.length / 2
            const y = 145 - (r.loads / maxL) * 130
            return (
              <g key={`l${i}`}>
                <circle cx={x} cy={y} r={3} fill="#1B3A5C" />
                <text
                  x={x}
                  y={y - 6}
                  textAnchor="middle"
                  className="text-[9px] fill-[#1B3A5C]"
                >
                  {fmtCount(r.loads)}
                </text>
              </g>
            )
          })}
        </svg>
      )}
    </div>
  )
}
