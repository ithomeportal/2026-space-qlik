"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import { useOpsTrend, type OpsFilters } from "@/lib/ops-margins-api"
import { OpsErrorBanner } from "../ErrorBanner"
import { fmtPct, fmtCount } from "../format"

type Bucket = "day" | "week" | "month"

export function Trend({ filters }: { filters: OpsFilters }) {
  const [bucket, setBucket] = useState<Bucket>("day")
  const { data, isLoading, error } = useOpsTrend(filters, bucket)
  const points = data?.data ?? []

  const margins = points.map((p) => p.margin_pct).filter((v): v is number => v !== null)
  const max = margins.length ? Math.max(...margins, 0) : 0
  const min = margins.length ? Math.min(...margins, 0) : 0
  const span = Math.max(1e-6, max - min)

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <OpsErrorBanner errors={[error]} label="Trend" />
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-[#1B3A5C]">Margin % trend</h3>
          <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            All loads in window · margin = SUM(profit) / SUM(revenue)
          </div>
        </div>
        <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
          {(["day", "week", "month"] as const).map((b) => (
            <button
              key={b}
              onClick={() => setBucket(b)}
              className={`px-3 py-1.5 capitalize ${
                bucket === b
                  ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                  : "text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              by {b}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : points.length === 0 ? (
        <div className="text-xs text-[#6B7280]">No data in window.</div>
      ) : (
        <>
          <svg viewBox={`0 0 ${Math.max(points.length * 30, 320)} 180`} className="h-48 w-full">
            {/* zero line */}
            {(() => {
              const zeroY = 160 - ((0 - min) / span) * 140
              return (
                <line
                  x1={0}
                  y1={zeroY}
                  x2={Math.max(points.length * 30, 320)}
                  y2={zeroY}
                  stroke="#E5E7EB"
                  strokeDasharray="3 3"
                />
              )
            })()}
            <polyline
              fill="none"
              stroke="#1B3A5C"
              strokeWidth={2}
              points={points
                .map((p, i) => {
                  const x = i * 30 + 16
                  const v = p.margin_pct ?? 0
                  const y = 160 - ((v - min) / span) * 140
                  return `${x},${y}`
                })
                .join(" ")}
            />
            {points.map((p, i) => {
              const x = i * 30 + 16
              const v = p.margin_pct ?? 0
              const y = 160 - ((v - min) / span) * 140
              const color = v < 0 ? "#DC2626" : v < 10 ? "#B45309" : "#15803D"
              return (
                <g key={i}>
                  <circle cx={x} cy={y} r={3.5} fill={color} />
                  <text
                    x={x}
                    y={y - 8}
                    textAnchor="middle"
                    className="text-[9px] fill-[#374151]"
                  >
                    {fmtPct(v)}
                  </text>
                  <text
                    x={x}
                    y={175}
                    textAnchor="middle"
                    className="text-[9px] fill-[#6B7280]"
                  >
                    {p.bucket?.slice(5) ?? ""}
                  </text>
                </g>
              )
            })}
          </svg>

          <div className="mt-3 grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
            <Stat label="Best" value={fmtPct(margins.length ? Math.max(...margins) : null)} />
            <Stat label="Worst" value={fmtPct(margins.length ? Math.min(...margins) : null)} />
            <Stat label="Buckets" value={fmtCount(points.length)} />
            <Stat
              label="Total loads"
              value={fmtCount(points.reduce((s, p) => s + p.loads, 0))}
            />
          </div>
        </>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-[#E5E7EB] px-2 py-1">
      <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">{label}</div>
      <div className="text-sm font-semibold text-[#111827]">{value}</div>
    </div>
  )
}
