"use client"

import { ChevronDown, ChevronsUpDown, ChevronUp, Loader2 } from "lucide-react"
import {
  useCarrierRiskByCarrierLane,
  type CarrierRiskFilters,
} from "@/lib/carrier-risk-api"
import { fmtCount, fmtUsd } from "./format"

type SortKey =
  | "mov_desc"
  | "mov_asc"
  | "avg_cost_desc"
  | "avg_cost_asc"
  | "carrier_asc"
  | "lane_asc"

interface Props {
  filters: CarrierRiskFilters
  sort: SortKey
  page: number
  pageSize: number
  onSortChange: (s: SortKey) => void
  onPageChange: (p: number) => void
}

const COLS: { key: string; label: string; align: "left" | "right"; sort?: { asc: SortKey; desc: SortKey } }[] = [
  { key: "carrier_name", label: "Carrier", align: "left", sort: { asc: "carrier_asc", desc: "carrier_asc" } },
  { key: "lane", label: "Lane", align: "left", sort: { asc: "lane_asc", desc: "lane_asc" } },
  { key: "mov", label: "# Mov", align: "right", sort: { asc: "mov_asc", desc: "mov_desc" } },
  { key: "avg_cost", label: "Avg Carrier Cost", align: "right", sort: { asc: "avg_cost_asc", desc: "avg_cost_desc" } },
]

export function CarrierLaneTable({
  filters,
  sort,
  page,
  pageSize,
  onSortChange,
  onPageChange,
}: Props) {
  const { data, isLoading, isFetching, error } = useCarrierRiskByCarrierLane(
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
          <h3 className="text-sm font-semibold text-[#1B3A5C]">Details by Carrier and Lane</h3>
          <span className="text-xs text-[#6B7280]">
            {fmtCount(total)} (carrier × lane) pairs
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
                  Failed to load carrier-lane pivot.
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={COLS.length} className="px-3 py-6 text-center text-[#6B7280]">
                  No (carrier × lane) pairs match the current filters.
                </td>
              </tr>
            ) : (
              rows.map((r, i) => (
                <tr key={`${r.carrier_name}-${r.lane}-${i}`} className="hover:bg-[#F9FAFB]">
                  <td className="px-3 py-1.5 text-[13px] text-[#1B3A5C]">
                    {r.carrier_name ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 text-[13px]">{r.lane ?? "—"}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.mov)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.avg_cost)}</td>
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
