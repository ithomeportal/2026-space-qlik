"use client"

import { ChevronDown, ChevronsUpDown, ChevronUp, Loader2 } from "lucide-react"
import {
  useCarrierRiskByLane,
  type CarrierRiskFilters,
} from "@/lib/carrier-risk-api"
import { RiskBadge } from "./RiskBadge"
import { fmtCount, fmtNum, fmtPct, fmtUsd } from "./format"

type SortKey =
  | "n_mov_desc"
  | "n_mov_asc"
  | "n_carrier_desc"
  | "n_carrier_asc"
  | "avg_cost_desc"
  | "avg_cost_asc"
  | "top1_share_desc"
  | "hhi_desc"
  | "margin_pct_asc"
  | "margin_pct_desc"
  | "lane_asc"

interface Props {
  filters: CarrierRiskFilters
  sort: SortKey
  page: number
  pageSize: number
  onSortChange: (s: SortKey) => void
  onPageChange: (p: number) => void
  onLaneClick: (lane: string) => void
}

const COLS: { key: string; label: string; align: "left" | "right"; sort?: { asc: SortKey; desc: SortKey } }[] = [
  { key: "lane", label: "Lane", align: "left", sort: { asc: "lane_asc", desc: "lane_asc" } },
  { key: "n_mov", label: "# Mov", align: "right", sort: { asc: "n_mov_asc", desc: "n_mov_desc" } },
  { key: "n_carrier", label: "# Carrier", align: "right", sort: { asc: "n_carrier_asc", desc: "n_carrier_desc" } },
  { key: "avg_cost", label: "Avg Carrier Cost", align: "right", sort: { asc: "avg_cost_asc", desc: "avg_cost_desc" } },
  { key: "top1_share", label: "Top 1", align: "right", sort: { asc: "top1_share_desc", desc: "top1_share_desc" } },
  { key: "hhi", label: "HHI", align: "right", sort: { asc: "hhi_desc", desc: "hhi_desc" } },
  { key: "cv_cost", label: "Cost CV", align: "right" },
  { key: "margin_pct", label: "% Margin", align: "right", sort: { asc: "margin_pct_asc", desc: "margin_pct_desc" } },
  { key: "risk_band", label: "Risk", align: "left" },
]

export function LaneTable({
  filters,
  sort,
  page,
  pageSize,
  onSortChange,
  onPageChange,
  onLaneClick,
}: Props) {
  const { data, isLoading, isFetching, error } = useCarrierRiskByLane(
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
    // Click cycles desc → asc → desc (defaults to desc on first click)
    onSortChange(sort === col.sort.desc ? col.sort.asc : col.sort.desc)
    onPageChange(1)
  }

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-[#E5E7EB] px-4 py-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-[#1B3A5C]">Details by Lane</h3>
          <span className="text-xs text-[#6B7280]">
            {fmtCount(total)} lanes · # Carrier, # Mov, Avg Carrier Cost + concentration
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
                  Failed to load lanes.
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={COLS.length} className="px-3 py-6 text-center text-[#6B7280]">
                  No lanes match the current filters.
                </td>
              </tr>
            ) : (
              rows.map((r, i) => (
                <tr key={`${r.lane}-${i}`} className="hover:bg-[#F9FAFB]">
                  <td className="px-3 py-1.5 text-[13px]">
                    <button
                      type="button"
                      className="text-left text-[#1B3A5C] hover:underline"
                      onClick={() => r.lane && onLaneClick(r.lane)}
                      title={r.lane ?? ""}
                    >
                      {r.lane ?? "—"}
                    </button>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.n_mov)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmtCount(r.n_carrier)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{fmtUsd(r.avg_cost)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {r.top1_share !== null ? fmtPct(r.top1_share * 100) : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {fmtNum(r.hhi)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {r.cv_cost !== null ? fmtNum(r.cv_cost) : "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {r.margin_pct !== null ? fmtPct(r.margin_pct) : "—"}
                  </td>
                  <td className="px-3 py-1.5"><RiskBadge band={r.risk_band} /></td>
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
