"use client"

import { useState } from "react"
import { Loader2, ArrowUpDown, ListChecks, LineChart } from "lucide-react"
import { useLossesByLane, type LossesFilters } from "@/lib/losses-lanes-api"
import { LossesErrorBanner } from "../ErrorBanner"

const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const PCT2 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
})

const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))
const fmtPct = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${PCT2.format(Number(v))}%`

interface Props {
  filters: LossesFilters
  thresholds: [number, number, number]          // fraction form (0.15, 0.18, 0.20)
  thresholdsPct: [number, number, number]       // percent form (15, 18, 20)
  onChangeThresholdPct: (idx: 0 | 1 | 2, pct: number) => void
  onDrillOrders: (lane: string) => void
  onShowTrend: (lane: string) => void
}

export function WorstLanes({
  filters,
  thresholds,
  thresholdsPct,
  onChangeThresholdPct,
  onDrillOrders,
  onShowTrend,
}: Props) {
  const [sort, setSort] = useState<string>("profit_asc")
  const [page, setPage] = useState(1)
  const limit = 100

  const { data, isLoading, error } = useLossesByLane(
    filters,
    sort,
    page,
    limit,
    thresholds,
  )
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
      <LossesErrorBanner errors={[error]} label="Worst Margins by Lane" />
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-xs text-[#6B7280]">
          {total.toLocaleString()} lane rows · Rows with &lt;−20% margin highlighted red
        </div>
        <div className="flex items-center gap-2 text-xs text-[#6B7280]">
          <span className="font-semibold uppercase tracking-wider">Target % sliders:</span>
          {([0, 1, 2] as const).map((i) => (
            <label key={i} className="flex items-center gap-1">
              <span className="text-[#374151]">T{i + 1}</span>
              <input
                type="number"
                min={0}
                max={100}
                step={1}
                value={Number.isFinite(thresholdsPct[i]) ? thresholdsPct[i] : ""}
                onChange={(e) => {
                  const n = Number(e.target.value)
                  onChangeThresholdPct(i, n)
                  setPage(1)
                }}
                className="w-14 rounded border border-[#E5E7EB] bg-white px-1 py-0.5 text-right"
              />
              <span>%</span>
            </label>
          ))}
          {isLoading && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
        </div>
      </div>
      <div className="overflow-auto rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-[#7F1D1D] text-white">
            <tr>
              <Th label="Customer" onClick={() => setSortKey("customer")} />
              <Th label="Lane" onClick={() => setSortKey("lane")} />
              <Th label="Revenue" onClick={() => setSortKey("revenue")} right />
              <Th label="$ Profit" onClick={() => setSortKey("profit")} right />
              <Th label="% Margin" onClick={() => setSortKey("margin")} right />
              <th className="px-2 py-2 text-right font-semibold">{thresholdsPct[0]}% Profit</th>
              <th className="px-2 py-2 text-right font-semibold">{thresholdsPct[0]}% Diff+</th>
              <th className="px-2 py-2 text-right font-semibold">{thresholdsPct[1]}% Profit</th>
              <th className="px-2 py-2 text-right font-semibold">{thresholdsPct[1]}% Diff+</th>
              <th className="px-2 py-2 text-right font-semibold">{thresholdsPct[2]}% Profit</th>
              <th className="px-2 py-2 text-right font-semibold">{thresholdsPct[2]}% Diff+</th>
              <th className="px-2 py-2 text-right font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !isLoading && (
              <tr>
                <td colSpan={12} className="px-4 py-8 text-center text-[#6B7280]">
                  No losing lanes in this window.
                </td>
              </tr>
            )}
            {rows.map((r, i) => {
              const pct = r.margin_pct ?? 0
              const bgShade =
                pct <= -20 ? "bg-[#FEE2E2]" : pct <= -10 ? "bg-[#FEF3C7]" : ""
              return (
                <tr
                  key={`${r.customer ?? ""}-${r.lane ?? ""}-${i}`}
                  className={`border-b border-[#F3F4F6] hover:bg-[#F9FAFB] ${bgShade}`}
                >
                  <td className="px-2 py-1.5 font-medium text-[#111827]">{r.customer ?? "—"}</td>
                  <td className="px-2 py-1.5 text-[#374151]">{r.lane ?? "—"}</td>
                  <td className="px-2 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                  <td className="px-2 py-1.5 text-right font-semibold text-[#B91C1C]">
                    {fmtUsd(r.profit)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-semibold text-[#7C3AED]">
                    {fmtPct(r.margin_pct)}
                  </td>
                  <td className="px-2 py-1.5 text-right text-[#6B7280]">
                    {fmtUsd(r.profit_1)}
                  </td>
                  <td className="px-2 py-1.5 text-right text-[#047857]">{fmtUsd(r.diff_1)}</td>
                  <td className="px-2 py-1.5 text-right text-[#6B7280]">
                    {fmtUsd(r.profit_2)}
                  </td>
                  <td className="px-2 py-1.5 text-right text-[#047857]">{fmtUsd(r.diff_2)}</td>
                  <td className="px-2 py-1.5 text-right text-[#6B7280]">
                    {fmtUsd(r.profit_3)}
                  </td>
                  <td className="px-2 py-1.5 text-right text-[#047857]">{fmtUsd(r.diff_3)}</td>
                  <td className="px-2 py-1.5 text-right">
                    {r.lane && (
                      <div className="flex justify-end gap-1">
                        <button
                          onClick={() => onShowTrend(r.lane!)}
                          className="inline-flex items-center gap-1 rounded border border-[#E5E7EB] bg-white px-1.5 py-0.5 text-[10px] text-[#1B3A5C] hover:bg-[#F3F4F6]"
                          title="60-day lane trend"
                        >
                          <LineChart className="h-3 w-3" />
                          Trend
                        </button>
                        <button
                          onClick={() => onDrillOrders(r.lane!)}
                          className="inline-flex items-center gap-1 rounded border border-[#E5E7EB] bg-white px-1.5 py-0.5 text-[10px] text-[#1B3A5C] hover:bg-[#F3F4F6]"
                          title="Drill into Order Details"
                        >
                          <ListChecks className="h-3 w-3" />
                          Orders
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {total > limit && (
        <div className="flex items-center justify-between text-xs">
          <div className="text-[#6B7280]">
            Page {page} of {pageCount} · {total.toLocaleString()} lanes
          </div>
          <div className="flex gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="rounded border border-[#E5E7EB] bg-white px-3 py-1 disabled:opacity-40"
            >
              Prev
            </button>
            <button
              onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
              disabled={page === pageCount}
              className="rounded border border-[#E5E7EB] bg-white px-3 py-1 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function Th({
  label,
  onClick,
  right,
}: {
  label: string
  onClick?: () => void
  right?: boolean
}) {
  return (
    <th
      onClick={onClick}
      className={`cursor-pointer px-2 py-2 font-semibold hover:bg-[#991B1B] ${right ? "text-right" : "text-left"}`}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {onClick && <ArrowUpDown className="h-3 w-3 opacity-60" />}
      </span>
    </th>
  )
}
