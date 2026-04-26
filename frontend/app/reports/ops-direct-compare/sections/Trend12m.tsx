"use client"

import { Loader2 } from "lucide-react"
import { fmtPct, fmtUsd } from "../../ops-margins/format"
import { DCErrorBanner } from "../ErrorBanner"
import { useDCTrend12m, type DCTrendPoint } from "@/lib/ops-direct-compare-api"

interface Props {
  variant: "full" | "profit-only"  // panel1 view = full (revenue + profit + margin); panel2 view = profit + margin only
  title: string
}

export function Trend12m({ variant, title }: Props) {
  const { data, isLoading, error } = useDCTrend12m()
  const points: DCTrendPoint[] = data?.data ?? []

  if (isLoading) {
    return (
      <div className="flex h-44 items-center justify-center rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
        <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
      </div>
    )
  }
  if (points.length === 0) {
    return (
      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 text-xs text-[#6B7280] shadow-sm">
        <h3 className="mb-2 text-sm font-semibold text-[#1B3A5C]">{title}</h3>
        No trend data.
      </div>
    )
  }

  const maxRev = Math.max(...points.map((p) => p.revenue), 1)
  const maxProf = Math.max(...points.map((p) => p.profit), 1)
  const yMax = variant === "full" ? maxRev : maxProf
  const margins = points.map((p) => p.margin_pct).filter((v): v is number => v !== null)
  const marginMax = margins.length ? Math.max(...margins) : 0
  const marginMin = Math.min(0, margins.length ? Math.min(...margins) : 0)
  const marginSpan = Math.max(1e-6, marginMax - marginMin)

  const W = 60
  const H = 180
  const padTop = 16
  const padBottom = 36
  const innerH = H - padTop - padBottom

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <DCErrorBanner errors={[error]} label={title} />
      <div className="mb-2 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-[#1B3A5C]">{title}</h3>
          <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            Last 12 months · all teams · ignores both panels' filters
          </div>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-[#6B7280]">
          {variant === "full" && (
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 bg-[#3B82F6]" /> $Revenue
            </span>
          )}
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 bg-[#FACC15]" /> $Profit
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-1 w-3 bg-[#C026D3]" /> % Margin
          </span>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W * points.length} ${H}`}
        preserveAspectRatio="none"
        className="h-44 w-full"
      >
        {/* Bars */}
        {points.map((p, idx) => {
          const x = idx * W
          const profH = (p.profit / yMax) * innerH
          const revH = (p.revenue / yMax) * innerH
          return (
            <g key={`bar-${idx}`}>
              {variant === "full" && (
                <rect
                  x={x + 8}
                  y={padTop + (innerH - revH)}
                  width={W * 0.4}
                  height={revH}
                  fill="#3B82F6"
                  opacity={0.85}
                />
              )}
              <rect
                x={
                  variant === "full"
                    ? x + 8 + W * 0.4 + 2
                    : x + W * 0.2
                }
                y={padTop + (innerH - profH)}
                width={variant === "full" ? W * 0.35 : W * 0.6}
                height={profH}
                fill="#FACC15"
              />
            </g>
          )
        })}
        {/* Margin polyline */}
        <polyline
          points={points
            .map((p, idx) => {
              const x = idx * W + W / 2
              const m = p.margin_pct ?? 0
              const y = padTop + innerH - ((m - marginMin) / marginSpan) * innerH
              return `${x},${y}`
            })
            .join(" ")}
          fill="none"
          stroke="#C026D3"
          strokeWidth={2}
        />
        {/* Margin dots + labels */}
        {points.map((p, idx) => {
          const x = idx * W + W / 2
          const m = p.margin_pct ?? 0
          const y = padTop + innerH - ((m - marginMin) / marginSpan) * innerH
          return (
            <g key={`m-${idx}`}>
              <circle cx={x} cy={y} r={2.5} fill="#C026D3" />
              <text
                x={x}
                y={y - 6}
                textAnchor="middle"
                className="fill-[#9333EA] text-[9px]"
              >
                {p.margin_pct === null ? "—" : `${p.margin_pct.toFixed(1)}%`}
              </text>
            </g>
          )
        })}
        {/* X labels */}
        {points.map((p, idx) => {
          if (!p.bucket) return null
          const d = new Date(p.bucket)
          const label = d.toLocaleDateString("en-US", {
            month: "short",
            year: "2-digit",
          })
          return (
            <text
              key={`x-${idx}`}
              x={idx * W + W / 2}
              y={H - 4}
              textAnchor="middle"
              className="fill-[#6B7280] text-[9px]"
            >
              {label}
            </text>
          )
        })}
      </svg>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-[#6B7280]">
        {points.map((p) => (
          <span key={`leg-${p.bucket}`} className="tabular-nums">
            {p.bucket?.slice(0, 7)}: {fmtUsd(p.profit)}
            {p.margin_pct !== null && ` · ${fmtPct(p.margin_pct)}`}
          </span>
        ))}
      </div>
    </div>
  )
}
