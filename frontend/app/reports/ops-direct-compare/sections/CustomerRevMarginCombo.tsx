"use client"

import { Loader2 } from "lucide-react"
import { fmtPct, fmtUsd } from "../../ops-margins/format"
import { DCErrorBanner } from "../ErrorBanner"
import {
  useDCCustomerRevMargin,
  type DCPanelFilters,
} from "@/lib/ops-direct-compare-api"

interface Props {
  filters: DCPanelFilters
  title: string
}

export function CustomerRevMarginCombo({ filters, title }: Props) {
  const { data, isLoading, error } = useDCCustomerRevMargin(filters, 20)
  const rows = data?.data ?? []

  if (isLoading) {
    return (
      <div className="flex h-56 items-center justify-center rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
        <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
      </div>
    )
  }
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 text-xs text-[#6B7280] shadow-sm">
        <h3 className="mb-2 text-sm font-semibold text-[#1B3A5C]">{title}</h3>
        No data in window.
      </div>
    )
  }

  const maxRev = Math.max(...rows.map((r) => r.revenue), 1)
  const margins = rows.map((r) => r.margin_pct).filter((v): v is number => v !== null)
  const marginMax = Math.max(0, ...(margins.length ? margins : [0]))
  const marginMin = Math.min(0, ...(margins.length ? margins : [0]))
  const marginSpan = Math.max(1e-6, marginMax - marginMin)

  const W = 50
  const H = 200
  const padTop = 12
  const padBottom = 60
  const innerH = H - padTop - padBottom

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <DCErrorBanner errors={[error]} label={title} />
      <div className="mb-2 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-[#1B3A5C]">{title}</h3>
          <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            Top 20 customers by revenue · bars = $Revenue · line = % Margin
          </div>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-[#6B7280]">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 bg-[#3B82F6]" /> $Revenue
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-1 w-3 bg-[#C026D3]" /> % Margin
          </span>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W * rows.length} ${H}`}
        preserveAspectRatio="none"
        className="h-56 w-full"
      >
        {rows.map((r, idx) => {
          const x = idx * W
          const h = (r.revenue / maxRev) * innerH
          return (
            <rect
              key={`b-${idx}`}
              x={x + 6}
              y={padTop + (innerH - h)}
              width={W - 12}
              height={h}
              fill="#3B82F6"
              opacity={0.85}
            >
              <title>
                {r.customer}: {fmtUsd(r.revenue)} · {fmtPct(r.margin_pct)}
              </title>
            </rect>
          )
        })}
        <polyline
          points={rows
            .map((r, idx) => {
              const x = idx * W + W / 2
              const m = r.margin_pct ?? 0
              const y = padTop + innerH - ((m - marginMin) / marginSpan) * innerH
              return `${x},${y}`
            })
            .join(" ")}
          fill="none"
          stroke="#C026D3"
          strokeWidth={2}
        />
        {rows.map((r, idx) => {
          const x = idx * W + W / 2
          const m = r.margin_pct ?? 0
          const y = padTop + innerH - ((m - marginMin) / marginSpan) * innerH
          return (
            <g key={`p-${idx}`}>
              <circle cx={x} cy={y} r={2.5} fill="#C026D3" />
              <text
                x={x}
                y={y - 6}
                textAnchor="middle"
                className="fill-[#9333EA] text-[8px]"
              >
                {r.margin_pct === null ? "—" : `${r.margin_pct.toFixed(1)}%`}
              </text>
              <text
                x={x}
                y={H - 38}
                textAnchor="end"
                transform={`rotate(-60 ${x},${H - 38})`}
                className="fill-[#374151] text-[8px]"
              >
                {r.customer.length > 14 ? r.customer.slice(0, 14) + "…" : r.customer}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
