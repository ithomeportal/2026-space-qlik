"use client"

import { useState } from "react"
import { ChevronDown, ChevronUp, Loader2, Users } from "lucide-react"
import {
  useTopDelayedCustomers,
  type AdminCashflowFilters,
  type TopDelayedCustomerRow,
} from "@/lib/admin-cashflow-api"
import { fmtCount, fmtNum1, fmtUsd } from "./format"

interface Props {
  filters: AdminCashflowFilters
}

// Bruno R4 PDF 2026-05-26: sort every column. The list is ≤10 pre-fetched
// rows (top-N by revenue), so re-ordering happens client-side.
type SortKey = "customer_name" | "n_late" | "late_revenue" | "avg_days"
type SortDir = "asc" | "desc"

export function TopDelayedCustomers({ filters }: Props) {
  const { data, isLoading } = useTopDelayedCustomers(filters, 10)
  const [sortKey, setSortKey] = useState<SortKey>("late_revenue")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir(key === "customer_name" ? "asc" : "desc")
    }
  }

  const rows = [...(data?.data ?? [])].sort(
    (a: TopDelayedCustomerRow, b: TopDelayedCustomerRow) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      let cmp: number
      if (typeof av === "string" || typeof bv === "string") {
        cmp = String(av).localeCompare(String(bv))
      } else {
        cmp = (av as number) - (bv as number)
      }
      return sortDir === "asc" ? cmp : -cmp
    },
  )

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center gap-2">
        <Users className="h-4 w-4 text-[#1B3A5C]" />
        <div className="text-sm font-semibold text-[#1B3A5C]">
          Top customers contributing to delays
        </div>
      </div>
      <div className="text-[11px] text-[#6B7280]">
        Late = bill_date − dest_actual_departure &gt; 2 days · ranked by $
        revenue at risk
      </div>
      <div className="mt-3 max-h-52 overflow-auto">
        {isLoading ? (
          <div className="flex h-32 items-center justify-center text-[#6B7280]">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        ) : rows.length === 0 ? (
          <div className="py-8 text-center text-xs text-[#9CA3AF]">
            No customers with &gt;2-day delays in current filters
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                <SortTh label="Customer" col="customer_name" current={sortKey} dir={sortDir} onSort={onSort} />
                <SortTh label="Late" col="n_late" current={sortKey} dir={sortDir} onSort={onSort} align="right" />
                <SortTh label="Revenue" col="late_revenue" current={sortKey} dir={sortDir} onSort={onSort} align="right" />
                <SortTh label="Avg d" col="avg_days" current={sortKey} dir={sortDir} onSort={onSort} align="right" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.customer_name}
                  className="border-b border-[#F3F4F6] last:border-0"
                >
                  <td className="px-1.5 py-1.5 truncate" title={r.customer_name}>
                    {r.customer_name}
                  </td>
                  <td className="px-1.5 py-1.5 text-right tabular-nums">
                    {fmtCount(r.n_late)}
                  </td>
                  <td className="px-1.5 py-1.5 text-right tabular-nums font-semibold text-[#991B1B]">
                    {fmtUsd(r.late_revenue)}
                  </td>
                  <td className="px-1.5 py-1.5 text-right tabular-nums">
                    {fmtNum1(r.avg_days)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

interface SortThProps {
  label: string
  col: SortKey
  current: SortKey
  dir: SortDir
  onSort: (key: SortKey) => void
  align?: "left" | "right"
}

function SortTh({ label, col, current, dir, onSort, align = "left" }: SortThProps) {
  const active = current === col
  return (
    <th className={`px-1.5 py-1.5 ${align === "right" ? "text-right" : "text-left"}`}>
      <button
        onClick={() => onSort(col)}
        className={`inline-flex items-center gap-1 ${
          active ? "text-[#1B3A5C]" : "text-[#6B7280]"
        }`}
      >
        {label}
        {active &&
          (dir === "desc" ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronUp className="h-3 w-3" />
          ))}
      </button>
    </th>
  )
}
