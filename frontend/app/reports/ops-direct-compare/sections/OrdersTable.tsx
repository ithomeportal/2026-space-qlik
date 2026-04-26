"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import { fmtUsd, marginBgColor } from "../../ops-margins/format"
import { DCErrorBanner } from "../ErrorBanner"
import {
  useDCOrdersWindow,
  type DCPanelFilters,
} from "@/lib/ops-direct-compare-api"

interface Props {
  filters: DCPanelFilters
  title: string
}

export function OrdersTable({ filters, title }: Props) {
  const [sort, setSort] = useState<string>("date_desc")
  const [page, setPage] = useState(1)
  const limit = 200
  const { data, isLoading, error } = useDCOrdersWindow(filters, { sort, page, limit })
  const rows = data?.data ?? []
  const total = data?.meta?.total ?? 0
  const window = data?.meta?.window

  const headerSort = (key: string) => {
    setPage(1)
    if (sort === `${key}_desc`) setSort(`${key}_asc`)
    else setSort(`${key}_desc`)
  }
  const arrow = (key: string) =>
    sort === `${key}_desc` ? "↓" : sort === `${key}_asc` ? "↑" : ""

  const lastPage = Math.max(1, Math.ceil(total / limit))

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <DCErrorBanner errors={[error]} label={title} />
      <div className="mb-2 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-[#1B3A5C]">{title}</h3>
          <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            {window
              ? `Window: ${window.start} → ${window.end} · ignores Panel 2 date filter`
              : "This year + last year · ignores Panel 2 date filter"}
          </div>
        </div>
        <span className="text-[10px] text-[#6B7280]">
          {total.toLocaleString()} orders · page {page}/{lastPage}
        </span>
      </div>
      {isLoading ? (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <>
          <div className="max-h-[480px] overflow-auto">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-white">
                <tr className="border-b border-[#E5E7EB] text-[10px] uppercase tracking-wider text-[#6B7280]">
                  <th className="px-2 py-2 text-left">Order</th>
                  <th
                    className="cursor-pointer px-2 py-2 text-left hover:text-[#111827]"
                    onClick={() => headerSort("date")}
                  >
                    Actual Date {arrow("date")}
                  </th>
                  <th className="px-2 py-2 text-left">Cust ID</th>
                  <th className="px-2 py-2 text-left">Customer</th>
                  <th className="px-2 py-2 text-left">Team</th>
                  <th className="px-2 py-2 text-left">Lane</th>
                  <th
                    className="cursor-pointer px-2 py-2 text-right hover:text-[#111827]"
                    onClick={() => headerSort("revenue")}
                  >
                    $ Revenue {arrow("revenue")}
                  </th>
                  <th
                    className="cursor-pointer px-2 py-2 text-right hover:text-[#111827]"
                    onClick={() => headerSort("profit")}
                  >
                    $ Profit {arrow("profit")}
                  </th>
                  <th
                    className="cursor-pointer px-2 py-2 text-right hover:text-[#111827]"
                    onClick={() => headerSort("margin")}
                  >
                    % Margin {arrow("margin")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, idx) => (
                  <tr
                    key={`${r.id}-${idx}`}
                    className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]"
                  >
                    <td className="px-2 py-1.5 font-mono text-[10px] text-[#111827]">
                      {r.id}
                    </td>
                    <td className="px-2 py-1.5 text-[#374151]">
                      {r.actual_day
                        ? new Date(r.actual_day).toLocaleString("en-US", {
                            month: "short",
                            day: "numeric",
                            year: "numeric",
                            hour: "numeric",
                            minute: "2-digit",
                          })
                        : "—"}
                    </td>
                    <td className="px-2 py-1.5 text-[#374151]">{r.cust_id ?? "—"}</td>
                    <td className="px-2 py-1.5 text-[#374151]" title={r.customer ?? ""}>
                      {r.customer ?? "—"}
                    </td>
                    <td className="px-2 py-1.5 text-[#374151]">{r.team ?? "—"}</td>
                    <td className="px-2 py-1.5 text-[#374151]" title={r.lane ?? ""}>
                      {r.lane ?? "—"}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-[#374151]">
                      {fmtUsd(r.revenue)}
                    </td>
                    <td
                      className={`px-2 py-1.5 text-right tabular-nums ${r.profit < 0 ? "text-[#DC2626]" : "text-[#374151]"}`}
                    >
                      {fmtUsd(r.profit)}
                    </td>
                    <td
                      className={`px-2 py-1.5 text-right tabular-nums ${marginBgColor(r.margin_pct)}`}
                    >
                      {r.margin_pct === null ? "—" : `${r.margin_pct.toFixed(2)}%`}
                    </td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-2 py-4 text-center text-[#6B7280]">
                      No orders in window.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {lastPage > 1 && (
            <div className="mt-2 flex items-center justify-end gap-2 text-xs">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-[#374151] hover:bg-[#F9FAFB] disabled:cursor-not-allowed disabled:opacity-40"
              >
                ← Prev
              </button>
              <span className="text-[#6B7280]">
                {page} / {lastPage}
              </span>
              <button
                disabled={page >= lastPage}
                onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
                className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-[#374151] hover:bg-[#F9FAFB] disabled:cursor-not-allowed disabled:opacity-40"
              >
                Next →
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
