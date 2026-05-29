"use client"

import { ChevronDown, ChevronsUpDown, ChevronUp, Loader2 } from "lucide-react"
import type { CarrierSmsRow } from "@/lib/carrier-sms-api"
import {
  basicBadgeClass,
  fmtDate,
  fmtMeasure,
  fmtPct1,
  mcpBadgeClass,
  oosClass,
} from "./format"

interface ColSort {
  asc: string
  desc: string
  firstDesc?: boolean
}

interface Col {
  key: string
  label: string
  sub?: string
  align: "left" | "right" | "center"
  sort?: ColSort
}

const COLS: Col[] = [
  { key: "name", label: "Carrier", align: "left", sort: { asc: "name_asc", desc: "name_desc" } },
  { key: "location", label: "Location", align: "left", sort: { asc: "state_asc", desc: "state_desc" } },
  { key: "dot", label: "DOT #", align: "left" },
  { key: "vehicle", label: "Vehicle OOS", sub: "Nat'l 23.2%", align: "right", sort: { asc: "vehicle_oos_asc", desc: "vehicle_oos_desc", firstDesc: true } },
  { key: "driver", label: "Driver OOS", sub: "Nat'l 6.4%", align: "right", sort: { asc: "driver_oos_asc", desc: "driver_oos_desc", firstDesc: true } },
  { key: "unsafe", label: "Unsafe", align: "center", sort: { asc: "basic_unsafe_asc", desc: "basic_unsafe_desc", firstDesc: true } },
  { key: "hos", label: "HOS", align: "center", sort: { asc: "basic_hos_asc", desc: "basic_hos_desc", firstDesc: true } },
  { key: "fitness", label: "Fitness", align: "center", sort: { asc: "basic_fitness_asc", desc: "basic_fitness_desc", firstDesc: true } },
  { key: "drugalc", label: "Drug/Alc", align: "center", sort: { asc: "basic_drugalc_asc", desc: "basic_drugalc_desc", firstDesc: true } },
  { key: "vehmaint", label: "Veh Maint", align: "center", sort: { asc: "basic_vehmaint_asc", desc: "basic_vehmaint_desc", firstDesc: true } },
  { key: "mcp", label: "MCP Risk", align: "left", sort: { asc: "mcp_risk_asc", desc: "mcp_risk_desc" } },
  { key: "sms_date", label: "SMS as of", align: "right", sort: { asc: "data_date_asc", desc: "data_date_desc", firstDesc: true } },
]

interface Props {
  rows: CarrierSmsRow[]
  total: number
  isLoading: boolean
  isFetching: boolean
  error: unknown
  sort: string
  page: number
  pageSize: number
  selected: Set<string>
  onSortChange: (s: string) => void
  onPageChange: (p: number) => void
  onToggleRow: (id: string) => void
  onTogglePage: (ids: string[], allSelected: boolean) => void
}

function BasicBadge({ value, alert }: { value: number | null; alert?: boolean }) {
  return (
    <span
      className={`inline-flex min-w-[2.75rem] items-center justify-center gap-0.5 rounded px-1.5 py-0.5 text-[12px] tabular-nums ${basicBadgeClass(value)}`}
      title={alert ? "FMCSA alert flag set" : undefined}
    >
      {fmtMeasure(value)}
      {alert ? <span className="text-[10px]">▲</span> : null}
    </span>
  )
}

export function CarrierTable({
  rows,
  total,
  isLoading,
  isFetching,
  error,
  sort,
  page,
  pageSize,
  selected,
  onSortChange,
  onPageChange,
  onToggleRow,
  onTogglePage,
}: Props) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const pageIds = rows.map((r) => r.id)
  const allPageSelected = pageIds.length > 0 && pageIds.every((id) => selected.has(id))
  const colCount = COLS.length + 1

  const sortIcon = (col: Col) => {
    if (!col.sort) return null
    if (sort === col.sort.desc) return <ChevronDown className="ml-0.5 inline h-3 w-3" />
    if (sort === col.sort.asc) return <ChevronUp className="ml-0.5 inline h-3 w-3" />
    return <ChevronsUpDown className="ml-0.5 inline h-3 w-3 opacity-40" />
  }

  const handleHeaderClick = (col: Col) => {
    if (!col.sort) return
    let next: string
    if (sort === col.sort.desc) next = col.sort.asc
    else if (sort === col.sort.asc) next = col.sort.desc
    else next = col.sort.firstDesc ? col.sort.desc : col.sort.asc
    onSortChange(next)
    onPageChange(1)
  }

  const alignClass = (a: Col["align"]) =>
    a === "right" ? "text-right" : a === "center" ? "text-center" : "text-left"

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-[#E5E7EB] px-4 py-2">
        <h3 className="text-sm font-semibold text-[#1B3A5C]">Carriers</h3>
        {isFetching && !isLoading && (
          <Loader2 className="h-3 w-3 animate-spin text-[#6B7280]" />
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-[#F9FAFB] text-[11px] uppercase tracking-wider text-[#6B7280]">
            <tr>
              <th className="px-3 py-2 text-center">
                <input
                  type="checkbox"
                  aria-label="Select all on page"
                  checked={allPageSelected}
                  onChange={() => onTogglePage(pageIds, allPageSelected)}
                  className="h-3.5 w-3.5 cursor-pointer accent-[#1B3A5C]"
                />
              </th>
              {COLS.map((c) => (
                <th
                  key={c.key}
                  onClick={() => handleHeaderClick(c)}
                  className={`px-3 py-2 ${alignClass(c.align)} ${
                    c.sort ? "cursor-pointer select-none hover:text-[#1B3A5C]" : ""
                  }`}
                >
                  <span className="whitespace-nowrap">
                    {c.label}
                    {sortIcon(c)}
                  </span>
                  {c.sub && (
                    <span className="block text-[9px] font-normal normal-case text-[#9CA3AF]">
                      {c.sub}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {isLoading ? (
              <tr>
                <td colSpan={colCount} className="px-3 py-6 text-center text-[#6B7280]">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                </td>
              </tr>
            ) : error ? (
              <tr>
                <td colSpan={colCount} className="px-3 py-6 text-center text-[#991B1B]">
                  Failed to load carriers.
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={colCount} className="px-3 py-6 text-center text-[#6B7280]">
                  No carriers match the current filters.
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.id} className={selected.has(r.id) ? "bg-[#EFF6FF]" : "hover:bg-[#F9FAFB]"}>
                  <td className="px-3 py-1.5 text-center">
                    <input
                      type="checkbox"
                      aria-label={`Select ${r.name}`}
                      checked={selected.has(r.id)}
                      onChange={() => onToggleRow(r.id)}
                      className="h-3.5 w-3.5 cursor-pointer accent-[#1B3A5C]"
                    />
                  </td>
                  <td className="px-3 py-1.5 text-[13px] font-medium text-[#1F2937]">
                    {r.name}
                    {!r.is_active && (
                      <span className="ml-1.5 rounded bg-[#F3F4F6] px-1 py-0.5 text-[9px] uppercase text-[#9CA3AF]">
                        inactive
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-[13px] text-[#6B7280]">
                    {[r.city, r.state].filter(Boolean).join(", ") || "—"}
                  </td>
                  <td className="px-3 py-1.5 text-[12px] tabular-nums text-[#6B7280]">
                    {r.dot_number || "—"}
                  </td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${oosClass(r.vehicle_oos_pct, r.nat_avg_vehicle)}`}>
                    {fmtPct1(r.vehicle_oos_pct)}
                  </td>
                  <td className={`px-3 py-1.5 text-right tabular-nums ${oosClass(r.driver_oos_pct, r.nat_avg_driver)}`}>
                    {fmtPct1(r.driver_oos_pct)}
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <BasicBadge value={r.basic_unsafe} alert={r.unsafe_ac === "Y"} />
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <BasicBadge value={r.basic_hos} alert={r.hos_ac === "Y"} />
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <BasicBadge value={r.basic_fitness} alert={r.fitness_ac === "Y"} />
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <BasicBadge value={r.basic_drugalc} alert={r.drugalc_sv === "Y"} />
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <BasicBadge value={r.basic_vehmaint} alert={r.vehmaint_ac === "Y"} />
                  </td>
                  <td className="px-3 py-1.5">
                    {r.mcp_risk_overall ? (
                      <span
                        className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium ${mcpBadgeClass(r.mcp_risk_overall)}`}
                        title={r.mcp_risk_points !== null ? `${r.mcp_risk_points} risk points` : undefined}
                      >
                        {r.mcp_is_blocked ? "⛔ " : ""}
                        {r.mcp_risk_overall}
                      </span>
                    ) : (
                      <span className="text-[12px] text-[#9CA3AF]">—</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-right text-[12px] text-[#6B7280] tabular-nums">
                    {fmtDate(r.data_file_date)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between border-t border-[#E5E7EB] px-4 py-2 text-xs text-[#6B7280]">
        <span>Page {page} of {totalPages}</span>
        <div className="flex gap-1">
          <button
            disabled={page <= 1}
            onClick={() => onPageChange(page - 1)}
            className="rounded-md border border-[#E5E7EB] px-2 py-1 hover:bg-[#F9FAFB] disabled:opacity-50"
          >
            Prev
          </button>
          <button
            disabled={page >= totalPages}
            onClick={() => onPageChange(page + 1)}
            className="rounded-md border border-[#E5E7EB] px-2 py-1 hover:bg-[#F9FAFB] disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}
