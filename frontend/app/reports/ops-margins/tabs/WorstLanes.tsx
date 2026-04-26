"use client"

import { useState } from "react"
import { Loader2, ArrowUpDown } from "lucide-react"
import { useOpsByLane, type OpsFilters } from "@/lib/ops-margins-api"
import { OpsErrorBanner } from "../ErrorBanner"
import { fmtCount, fmtPct, fmtUsd } from "../format"

interface Props {
  filters: OpsFilters
  thresholdsPct: [number, number, number]
  onChangeThresholdPct: (idx: 0 | 1 | 2, pct: number) => void
}

export function WorstLanes({ filters, thresholdsPct, onChangeThresholdPct }: Props) {
  const [sort, setSort] = useState("profit_asc")
  const [page, setPage] = useState(1)
  const limit = 100

  const thresholds: [number, number, number] = [
    thresholdsPct[0] / 100,
    thresholdsPct[1] / 100,
    thresholdsPct[2] / 100,
  ]
  const { data, isLoading, error } = useOpsByLane(filters, sort, page, limit, thresholds)
  const rows = data?.data ?? []
  const total = data?.meta?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / limit))

  const setSortKey = (key: string) => {
    setSort((prev) => {
      if (prev === `${key}_asc`) return `${key}_desc`
      if (prev === `${key}_desc`) return `${key}_asc`
      return `${key}_asc`
    })
    setPage(1)
  }

  return (
    <div className="space-y-3">
      <OpsErrorBanner errors={[error]} label="Worst Margins by Lane" />
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-[#6B7280]">
        <div>
          {total.toLocaleString()} loss-lanes (margin &lt; 0)
        </div>
        <div className="flex items-center gap-2">
          <span className="font-semibold uppercase tracking-wider">Targets:</span>
          {([0, 1, 2] as const).map((i) => (
            <label key={i} className="flex items-center gap-1">
              <span className="text-[#374151]">T{i + 1}</span>
              <input
                type="number"
                min={0}
                max={100}
                value={thresholdsPct[i]}
                onChange={(e) => onChangeThresholdPct(i, Number(e.target.value))}
                className="w-14 rounded border border-[#E5E7EB] px-1 py-0.5 text-right"
              />
              <span>%</span>
            </label>
          ))}
          <span>· Page {page} / {pageCount}</span>
          <button
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="rounded border border-[#E5E7EB] bg-white px-2 py-0.5 text-[#374151] disabled:opacity-50"
          >
            ‹
          </button>
          <button
            disabled={page >= pageCount}
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            className="rounded border border-[#E5E7EB] bg-white px-2 py-0.5 text-[#374151] disabled:opacity-50"
          >
            ›
          </button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
        <table className="min-w-full text-xs">
          <thead className="bg-[#FEF2F2] text-[#7F1D1D]">
            <tr>
              <Th>Customer</Th>
              <Th>Origin</Th>
              <Th>Destination</Th>
              <Th onClick={() => setSortKey("loads")} sortable>Loads <ArrowUpDown className="inline h-3 w-3" /></Th>
              <Th onClick={() => setSortKey("revenue")} sortable>Revenue <ArrowUpDown className="inline h-3 w-3" /></Th>
              <Th onClick={() => setSortKey("profit")} sortable>$ Profit <ArrowUpDown className="inline h-3 w-3" /></Th>
              <Th onClick={() => setSortKey("margin")} sortable>Margin <ArrowUpDown className="inline h-3 w-3" /></Th>
              <Th>{thresholdsPct[0]}% Profit</Th>
              <Th>{thresholdsPct[0]}% Diff+</Th>
              <Th>{thresholdsPct[1]}% Profit</Th>
              <Th>{thresholdsPct[1]}% Diff+</Th>
              <Th>{thresholdsPct[2]}% Profit</Th>
              <Th>{thresholdsPct[2]}% Diff+</Th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={13} className="px-3 py-8 text-center text-[#6B7280]">
                  <Loader2 className="inline h-4 w-4 animate-spin" />
                </td>
              </tr>
            )}
            {!isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={13} className="px-3 py-6 text-center text-[#6B7280]">
                  No loss lanes in window.
                </td>
              </tr>
            )}
            {rows.map((r, i) => {
              const sub20 = (r.margin_pct ?? 0) < -20
              return (
                <tr
                  key={i}
                  className={`border-t border-[#F3F4F6] ${sub20 ? "bg-[#FEE2E2]" : ""}`}
                >
                  <td className="max-w-xs truncate px-3 py-2 font-medium text-[#111827]">{r.customer ?? "—"}</td>
                  <td className="px-3 py-2 text-[#374151]">{r.origin ?? "—"}</td>
                  <td className="px-3 py-2 text-[#374151]">{r.destination ?? "—"}</td>
                  <td className="px-3 py-2 text-right">{fmtCount(r.loads)}</td>
                  <td className="px-3 py-2 text-right">{fmtUsd(r.revenue)}</td>
                  <td className="px-3 py-2 text-right text-[#B91C1C]">{fmtUsd(r.profit)}</td>
                  <td className="px-3 py-2 text-right font-semibold text-[#B91C1C]">{fmtPct(r.margin_pct)}</td>
                  <td className="px-3 py-2 text-right">{fmtUsd(r.profit_1)}</td>
                  <td className="px-3 py-2 text-right">{fmtUsd(r.diff_1)}</td>
                  <td className="px-3 py-2 text-right">{fmtUsd(r.profit_2)}</td>
                  <td className="px-3 py-2 text-right">{fmtUsd(r.diff_2)}</td>
                  <td className="px-3 py-2 text-right">{fmtUsd(r.profit_3)}</td>
                  <td className="px-3 py-2 text-right">{fmtUsd(r.diff_3)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Th({
  children,
  onClick,
  sortable,
}: {
  children: React.ReactNode
  onClick?: () => void
  sortable?: boolean
}) {
  return (
    <th
      className={`px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider ${
        sortable ? "cursor-pointer hover:text-[#111827]" : ""
      }`}
      onClick={onClick}
    >
      {children}
    </th>
  )
}
