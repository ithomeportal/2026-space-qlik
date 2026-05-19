"use client"

import { useMemo, useState } from "react"
import { ArrowDown, ArrowUp, Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useOppActualsByLane,
  type OppFilters,
  type OppLaneRow,
} from "@/lib/ops-portal-overview-api"

interface Props {
  filters: OppFilters
}

// Bruno round 3 (2026-05-19): second table below Actuals — Production-only,
// grouped by lane (city-pair).
type ColumnKey =
  | "lane" | "vol" | "rev" | "prof" | "margin"
  | "loss_loads" | "loss_profit"
  | "otp" | "otd" | "rev_x_l" | "prof_x_l"

const COLUMNS: {
  k: ColumnKey
  label: string
  align: "left" | "center" | "right"
  numeric: boolean
  accessor: (r: OppLaneRow) => number | string
}[] = [
  { k: "lane",        label: "Lane",         align: "left",   numeric: false, accessor: (r) => (r.lane || "").toUpperCase() },
  { k: "vol",         label: "Volume",       align: "right",  numeric: true,  accessor: (r) => r.vol },
  { k: "rev",         label: "Revenue",      align: "right",  numeric: true,  accessor: (r) => r.rev },
  { k: "prof",        label: "Profit",       align: "right",  numeric: true,  accessor: (r) => r.prof },
  { k: "margin",      label: "Margin %",     align: "right",  numeric: true,  accessor: (r) => r.margin_pct },
  { k: "loss_loads",  label: "Loss Loads",   align: "right",  numeric: true,  accessor: (r) => r.loss_loads },
  { k: "loss_profit", label: "Loss Profit",  align: "right",  numeric: true,  accessor: (r) => r.loss_profit },
  { k: "otp",         label: "OTP %",        align: "right",  numeric: true,  accessor: (r) => r.otp_pct },
  { k: "otd",         label: "OTD %",        align: "right",  numeric: true,  accessor: (r) => r.otd_pct },
  { k: "rev_x_l",     label: "Rev. x L",     align: "right",  numeric: true,  accessor: (r) => r.rev_x_l },
  { k: "prof_x_l",    label: "Prof. x L",    align: "right",  numeric: true,  accessor: (r) => r.prof_x_l },
]

export function ActualsByLane({ filters }: Props) {
  const [sortKey, setSortKey] = useState<ColumnKey>("rev")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
  const { data, isLoading, error } = useOppActualsByLane(filters, { sort: "revenue_desc", limit: 200 })
  const raw: OppLaneRow[] = useMemo(() => data?.data ?? [], [data])

  const rows = useMemo(() => {
    const col = COLUMNS.find((c) => c.k === sortKey)
    if (!col) return raw
    const mult = sortDir === "asc" ? 1 : -1
    return [...raw].sort((a, b) => {
      const va = col.accessor(a)
      const vb = col.accessor(b)
      if (typeof va === "string" || typeof vb === "string") {
        return String(va).localeCompare(String(vb)) * mult
      }
      return ((va as number) - (vb as number)) * mult
    })
  }, [raw, sortKey, sortDir])

  const onSort = (k: ColumnKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(k)
      const col = COLUMNS.find((c) => c.k === k)
      setSortDir(col?.numeric ? "desc" : "asc")
    }
  }

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
        <span className="rounded-md bg-[#0E7490] px-2 py-0.5 text-xs font-semibold uppercase text-white">
          By Lane
        </span>
        <span className="text-[10px] uppercase tracking-wider text-[#6B7280]">
          Production data · grouped by Origin → Destination
        </span>
        <div className="ml-auto flex items-center gap-2 text-[10px] text-[#6B7280]">
          {isLoading && <Loader2 className="h-3 w-3 animate-spin" />}
          <span>Click any column header to sort</span>
        </div>
      </div>

      {error ? (
        <div className="px-3 py-4 text-sm text-[#DC2626]">Failed to load lane roll-up</div>
      ) : (
        <div className="max-h-[420px] overflow-auto">
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
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-[#9CA3AF]">
                    No lanes in scope
                  </td>
                </tr>
              ) : rows.map((r) => (
                <tr key={r.lane} className="border-b border-[#F3F4F6] hover:bg-[#FAFBFC]">
                  <td className="px-2 py-1.5 font-semibold text-[#1B3A5C]">{r.lane}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtCount(r.vol)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(r.rev)}</td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${r.prof < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtUsd(r.prof)}
                  </td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${r.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtPct(r.margin_pct)}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtCount(r.loss_loads)}</td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${r.loss_profit < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtUsd(r.loss_profit)}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtPct(r.otp_pct)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtPct(r.otd_pct)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(r.rev_x_l)}</td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${r.prof_x_l < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtUsd(r.prof_x_l)}
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
  align?: "left" | "right" | "center"
  active: boolean
  dir: "asc" | "desc"
  onClick: () => void
}) {
  const cls =
    align === "right" ? "text-right"
    : align === "center" ? "text-center"
    : "text-left"
  const justify =
    align === "right" ? "justify-end"
    : align === "center" ? "justify-center"
    : "justify-start"
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
