"use client"

import { useState } from "react"
import { ArrowDown, ArrowUp, Loader2 } from "lucide-react"
import {
  fmtPct,
  fmtUsd,
  useOppByOrder,
  type OppFilters,
  type OppOrderRow,
  type OppOrderTotals,
} from "@/lib/ops-portal-overview-api"

interface Props {
  filters: OppFilters
}

// Bruno R4 (2026-05-27): load-level Production table. Server-side sort on every
// column (the set is load-level, so sorting only the fetched page would mis-rank).
type ColumnKey = "order" | "team" | "departure" | "customer" | "lane" | "revenue" | "profit" | "margin"

const COLUMNS: {
  k: ColumnKey
  label: string
  align: "left" | "right"
}[] = [
  { k: "order",     label: "Order",     align: "left" },
  { k: "team",      label: "Team",      align: "left" },
  { k: "departure", label: "Departure", align: "left" },
  { k: "customer",  label: "Customer",  align: "left" },
  { k: "lane",      label: "Lane",      align: "left" },
  { k: "revenue",   label: "Revenue",   align: "right" },
  { k: "profit",    label: "Profit",    align: "right" },
  { k: "margin",    label: "Margin",    align: "right" },
]

const LIMIT = 500

export function ByOrder({ filters }: Props) {
  const [sortKey, setSortKey] = useState<ColumnKey>("revenue")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
  const sort = `${sortKey}_${sortDir}`

  const { data, isLoading, error } = useOppByOrder(filters, { sort, limit: LIMIT })
  const rows: OppOrderRow[] = data?.data ?? []
  const totals = data?.meta?.totals as OppOrderTotals | undefined
  const returned = (data?.meta?.returned as number | undefined) ?? rows.length
  const total = totals?.n_orders ?? returned

  const onSort = (k: ColumnKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(k)
      // Numeric columns default desc, text columns asc.
      setSortDir(k === "revenue" || k === "profit" || k === "margin" ? "desc" : "asc")
    }
  }

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
        <span className="rounded-md bg-[#1B3A5C] px-2 py-0.5 text-xs font-semibold uppercase text-white">
          By Order
        </span>
        <span className="text-[10px] uppercase tracking-wider text-[#6B7280]">
          Production data · load-level
        </span>
        <div className="ml-auto flex items-center gap-2 text-[10px] text-[#6B7280]">
          {isLoading && <Loader2 className="h-3 w-3 animate-spin" />}
          {total > returned ? (
            <span>Showing top {returned} of {total.toLocaleString()} · click a header to sort</span>
          ) : (
            <span>Click any column header to sort</span>
          )}
        </div>
      </div>

      {error ? (
        <div className="px-3 py-4 text-sm text-[#DC2626]">Failed to load orders</div>
      ) : (
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                {COLUMNS.map((c) => (
                  <SortableTh
                    key={c.k}
                    align={c.align}
                    active={sortKey === c.k}
                    dir={sortDir}
                    onClick={() => onSort(c.k)}
                  >
                    {c.label}
                  </SortableTh>
                ))}
              </tr>
              {totals && (
                <tr className="border-b border-[#E5E7EB] bg-[#EFF6FF] font-semibold text-[#1B3A5C]">
                  <td className="px-2 py-1.5" colSpan={5}>
                    TOTAL · {total.toLocaleString()} orders
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(totals.revenue)}</td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${totals.profit < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtUsd(totals.profit)}
                  </td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${totals.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtPct(totals.margin_pct)}
                  </td>
                </tr>
              )}
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-[#9CA3AF]">
                    No orders in scope
                  </td>
                </tr>
              ) : rows.map((r) => (
                <tr key={r.order_id} className="border-b border-[#F3F4F6] hover:bg-[#FAFBFC]">
                  <td className="px-2 py-1.5 font-medium text-[#1B3A5C]">{r.order_id}</td>
                  <td className="px-2 py-1.5 text-[#374151]">{r.team_id}</td>
                  <td className="px-2 py-1.5 tabular-nums text-[#6B7280]">{r.departure}</td>
                  <td className="px-2 py-1.5 text-[#374151]">{r.customer_name}</td>
                  <td className="px-2 py-1.5 text-[#374151]">{r.lane}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(r.revenue)}</td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${r.profit < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtUsd(r.profit)}
                  </td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${r.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtPct(r.margin_pct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function SortableTh({
  children,
  align = "left",
  active,
  dir,
  onClick,
}: {
  children: React.ReactNode
  align?: "left" | "right"
  active: boolean
  dir: "asc" | "desc"
  onClick: () => void
}) {
  const cls = align === "right" ? "text-right" : "text-left"
  const justify = align === "right" ? "justify-end" : "justify-start"
  return (
    <th className={`px-2 py-2 ${cls}`}>
      <button
        type="button"
        onClick={onClick}
        className={`inline-flex w-full items-center gap-1 ${justify} ${
          active ? "font-bold text-[#1B3A5C]" : "hover:text-[#374151]"
        }`}
      >
        {children}
        {active && (dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  )
}
