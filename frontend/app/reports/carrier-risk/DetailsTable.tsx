"use client"

import { ChevronDown, ChevronsUpDown, ChevronUp, Loader2 } from "lucide-react"
import {
  useCarrierRiskDetails,
  type CarrierRiskFilters,
} from "@/lib/carrier-risk-api"
import { fmtCount, fmtDate, fmtPct, fmtUsd } from "./format"

type SortKey =
  | "departure_desc"
  | "departure_asc"
  | "revenue_desc"
  | "revenue_asc"
  | "profit_desc"
  | "profit_asc"
  | "margin_desc"
  | "margin_asc"

interface Props {
  filters: CarrierRiskFilters
  sort: SortKey
  page: number
  pageSize: number
  onSortChange: (s: SortKey) => void
  onPageChange: (p: number) => void
}

const COLS: { key: string; label: string; align: "left" | "right"; sort?: { asc: SortKey; desc: SortKey } }[] = [
  { key: "id", label: "ID", align: "left" },
  { key: "actual_departure", label: "Actual Departure", align: "left", sort: { asc: "departure_asc", desc: "departure_desc" } },
  { key: "customer", label: "Customer", align: "left" },
  { key: "carrier_name", label: "Carrier", align: "left" },
  { key: "lane", label: "Lane", align: "left" },
  { key: "revenue", label: "$ Revenue", align: "right", sort: { asc: "revenue_asc", desc: "revenue_desc" } },
  { key: "profit", label: "Profit", align: "right", sort: { asc: "profit_asc", desc: "profit_desc" } },
  { key: "margin_pct", label: "% Margin", align: "right", sort: { asc: "margin_asc", desc: "margin_desc" } },
]

export function DetailsTable({
  filters,
  sort,
  page,
  pageSize,
  onSortChange,
  onPageChange,
}: Props) {
  const { data, isLoading, isFetching, error } = useCarrierRiskDetails(
    filters,
    sort,
    page,
    pageSize,
  )
  const rows = data?.data ?? []
  const total = data?.meta?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const sortIcon = (col: { key: string; sort?: { asc: SortKey; desc: SortKey } }) => {
    if (!col.sort) return null
    if (sort === col.sort.desc) return <ChevronDown className="ml-1 inline h-3 w-3" />
    if (sort === col.sort.asc) return <ChevronUp className="ml-1 inline h-3 w-3" />
    return <ChevronsUpDown className="ml-1 inline h-3 w-3 opacity-40" />
  }

  const handleHeaderClick = (col: { sort?: { asc: SortKey; desc: SortKey } }) => {
    if (!col.sort) return
    onSortChange(sort === col.sort.desc ? col.sort.asc : col.sort.desc)
    onPageChange(1)
  }

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-[#E5E7EB] px-4 py-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-[#1B3A5C]">Order Details</h3>
          <span className="text-xs text-[#6B7280]">
            {fmtCount(total)} orders · revenue / profit / margin from v4
          </span>
        </div>
        {isFetching && !isLoading && (
          <Loader2 className="h-3 w-3 animate-spin text-[#6B7280]" />
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-[#F9FAFB] text-[11px] uppercase tracking-wider text-[#6B7280]">
            <tr>
              {COLS.map((c) => (
                <th
                  key={c.key}
                  onClick={() => handleHeaderClick(c)}
                  className={`px-3 py-2 ${c.align === "right" ? "text-right" : "text-left"} ${
                    c.sort ? "cursor-pointer select-none hover:text-[#1B3A5C]" : ""
                  }`}
                >
                  {c.label}
                  {sortIcon(c)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {isLoading ? (
              <tr>
                <td colSpan={COLS.length} className="px-3 py-6 text-center text-[#6B7280]">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                </td>
              </tr>
            ) : error ? (
              <tr>
                <td colSpan={COLS.length} className="px-3 py-6 text-center text-[#991B1B]">
                  Failed to load order details.
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={COLS.length} className="px-3 py-6 text-center text-[#6B7280]">
                  No orders match the current filters.
                </td>
              </tr>
            ) : (
              rows.map((r, i) => (
                <tr key={`${r.id}-${i}`} className="hover:bg-[#F9FAFB]">
                  <td className="px-3 py-1.5 text-[12px] text-[#374151]">{r.id ?? "—"}</td>
                  <td className="px-3 py-1.5 text-[12px] text-[#374151]">
                    {fmtDate(r.actual_departure)}
                  </td>
                  <td className="px-3 py-1.5 text-[12px]">{r.customer ?? "—"}</td>
                  <td className="px-3 py-1.5 text-[12px]">{r.carrier_name ?? "—"}</td>
                  <td className="px-3 py-1.5 text-[12px]">{r.lane ?? "—"}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.revenue)}</td>
                  <td
                    className={`px-3 py-1.5 text-right tabular-nums ${
                      r.profit !== null && r.profit < 0 ? "text-[#991B1B]" : ""
                    }`}
                  >
                    {fmtUsd(r.profit)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {r.margin_pct !== null ? fmtPct(r.margin_pct) : "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-[#E5E7EB] px-4 py-2 text-xs text-[#6B7280]">
        <span>
          Page {page} of {totalPages}
        </span>
        <div className="flex gap-1">
          <button
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
            className="rounded-md border border-[#E5E7EB] px-2 py-1 disabled:opacity-50 hover:bg-[#F9FAFB]"
          >
            Prev
          </button>
          <button
            disabled={page >= totalPages}
            onClick={() => onPageChange(page + 1)}
            className="rounded-md border border-[#E5E7EB] px-2 py-1 disabled:opacity-50 hover:bg-[#F9FAFB]"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}
