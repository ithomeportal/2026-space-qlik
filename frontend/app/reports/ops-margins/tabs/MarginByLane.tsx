"use client"

import { useState } from "react"
import { Loader2, ArrowUpDown } from "lucide-react"
import { useOpsLanesMargin, type OpsFilters } from "@/lib/ops-margins-api"
import { OpsErrorBanner } from "../ErrorBanner"
import { fmtCount, fmtPct, fmtUsd, marginBgColor, marginColor } from "../format"

export function MarginByLane({ filters }: { filters: OpsFilters }) {
  const [sort, setSort] = useState("margin_desc")
  const [page, setPage] = useState(1)
  const limit = 100

  const { data, isLoading, error } = useOpsLanesMargin(filters, sort, page, limit)
  const rows = data?.data ?? []
  const total = data?.meta?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / limit))

  const setSortKey = (key: string) => {
    setSort((prev) => {
      if (prev === `${key}_desc`) return `${key}_asc`
      if (prev === `${key}_asc`) return `${key}_desc`
      return `${key}_desc`
    })
    setPage(1)
  }

  return (
    <div className="space-y-3">
      <OpsErrorBanner errors={[error]} label="Margin by Lane" />
      <div className="flex items-center justify-between text-xs text-[#6B7280]">
        <div>{total.toLocaleString()} lanes · sorted by best margin first</div>
        <div className="flex items-center gap-2">
          <span>Page {page} / {pageCount}</span>
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
          <thead className="bg-[#F9FAFB] text-[#374151]">
            <tr>
              <Th>Customer</Th>
              <Th>Origin</Th>
              <Th>Destination</Th>
              <Th onClick={() => setSortKey("loads")} sortable>
                Loads <ArrowUpDown className="inline h-3 w-3" />
              </Th>
              <Th onClick={() => setSortKey("profit")} sortable>
                $ Profit <ArrowUpDown className="inline h-3 w-3" />
              </Th>
              <Th onClick={() => setSortKey("margin")} sortable>
                Margin % <ArrowUpDown className="inline h-3 w-3" />
              </Th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-[#6B7280]">
                  <Loader2 className="inline h-4 w-4 animate-spin" />
                </td>
              </tr>
            )}
            {!isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-[#6B7280]">
                  No data in window.
                </td>
              </tr>
            )}
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-[#F3F4F6]">
                <td className="max-w-xs truncate px-3 py-2 font-medium text-[#111827]">
                  {r.customer ?? "—"}
                </td>
                <td className="px-3 py-2 text-[#374151]">{r.origin ?? "—"}</td>
                <td className="px-3 py-2 text-[#374151]">{r.destination ?? "—"}</td>
                <td className="px-3 py-2 text-right">{fmtCount(r.loads)}</td>
                <td className="px-3 py-2 text-right">{fmtUsd(r.profit)}</td>
                <td
                  className={`px-3 py-2 text-right font-semibold ${marginColor(
                    r.margin_pct,
                  )} ${marginBgColor(r.margin_pct)}`}
                >
                  {fmtPct(r.margin_pct)}
                </td>
              </tr>
            ))}
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
