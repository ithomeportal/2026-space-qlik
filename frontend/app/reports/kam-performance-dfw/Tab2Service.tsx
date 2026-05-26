"use client"

import { useMemo, useState } from "react"
import { ArrowDown, ArrowUp, CheckCircle2, Loader2 } from "lucide-react"
import {
  useDfwServiceFailures,
  useDfwServiceKpi,
  type ServiceFailureRow,
} from "@/lib/kam-performance-dfw-api"
import { DateRangeControl, useKamDateRange } from "./DateRangeControl"
import { fmtCount, fmtDate, fmtPct } from "./format"

type Side = "pu" | "del"

export function Tab2Service() {
  const { value, setValue, bounds } = useKamDateRange("wtd")
  const { data: puKpi, isLoading: loadingPu } = useDfwServiceKpi("pu", bounds)
  const { data: delKpi, isLoading: loadingDel } = useDfwServiceKpi("del", bounds)
  const [side, setSide] = useState<Side>("pu")

  const otp = puKpi?.data?.kpi
  const otd = delKpi?.data?.kpi

  return (
    <div className="space-y-4">
      <DateRangeControl value={value} onChange={setValue} />

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <KpiCard
          label="OTP (Pickup On-Time)"
          value={otp?.pct_on_time}
          orders={otp?.orders}
          fails={otp?.fail}
          loading={loadingPu}
        />
        <KpiCard
          label="OTD (Delivery On-Time)"
          value={otd?.pct_on_time}
          orders={otd?.orders}
          fails={otd?.fail}
          loading={loadingDel}
        />
      </div>
      <div className="text-[10px] text-[#6B7280]">
        {bounds.start} → {bounds.end} · scope: TEAM-DFW · source:
        ops-customer-score
      </div>

      <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
        <div className="flex items-center gap-2 border-b border-[#E5E7EB] px-4 py-2">
          <button
            onClick={() => setSide("pu")}
            className={`rounded-md px-3 py-1.5 text-xs ${
              side === "pu"
                ? "bg-[#1B3A5C] text-white shadow-sm"
                : "border border-[#E5E7EB] text-[#374151] hover:bg-[#F9FAFB]"
            }`}
          >
            OTP failures
          </button>
          <button
            onClick={() => setSide("del")}
            className={`rounded-md px-3 py-1.5 text-xs ${
              side === "del"
                ? "bg-[#1B3A5C] text-white shadow-sm"
                : "border border-[#E5E7EB] text-[#374151] hover:bg-[#F9FAFB]"
            }`}
          >
            OTD failures
          </button>
          <span className="ml-auto text-[10px] text-[#6B7280]">
            Click any column to sort
          </span>
        </div>
        <FailuresTable side={side} bounds={bounds} />
      </div>
    </div>
  )
}

function KpiCard({
  label,
  value,
  orders,
  fails,
  loading,
}: {
  label: string
  value: number | null | undefined
  orders: number | undefined
  fails: number | undefined
  loading: boolean
}) {
  let tone = "border-[#E5E7EB] bg-white"
  let valueColor = "text-[#1B3A5C]"
  if (typeof value === "number") {
    if (value >= 95) {
      tone = "border-[#A7F3D0] bg-[#ECFDF5]"
      valueColor = "text-[#065F46]"
    } else if (value >= 85) {
      tone = "border-[#FCD34D] bg-[#FFFBEB]"
      valueColor = "text-[#92400E]"
    } else {
      tone = "border-[#FCA5A5] bg-[#FEF2F2]"
      valueColor = "text-[#991B1B]"
    }
  }
  return (
    <div className={`rounded-xl border p-4 shadow-sm ${tone}`}>
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-[#6B7280]">
        <CheckCircle2 className="h-3.5 w-3.5" />
        {label}
      </div>
      <div className={`mt-1 text-3xl font-semibold tabular-nums ${valueColor}`}>
        {loading ? "…" : fmtPct(value)}
      </div>
      <div className="mt-1 text-[11px] text-[#6B7280]">
        {fmtCount(orders)} orders · {fmtCount(fails)} fails
      </div>
    </div>
  )
}

interface FailRow extends ServiceFailureRow {
  counted: boolean
}

type SortKey =
  | "counted"
  | "id"
  | "team_dfw"
  | "customer_name"
  | "edi_standard_code"
  | "edi_code_descr"
  | "dsp_comment"
  | "entered_user_id"
  | "actual_arrival"

const COLUMNS: { key: SortKey; label: string; align?: "right" }[] = [
  { key: "counted", label: "Counted" },
  { key: "id", label: "Order" },
  { key: "team_dfw", label: "Team" },
  { key: "customer_name", label: "Customer" },
  { key: "edi_standard_code", label: "Code" },
  { key: "edi_code_descr", label: "Delay Descr" },
  { key: "dsp_comment", label: "Comment" },
  { key: "entered_user_id", label: "Entered by" },
  { key: "actual_arrival", label: "When" },
]

function cmpVal(row: FailRow, key: SortKey): string | number {
  if (key === "counted") return row.counted ? 1 : 0
  if (key === "actual_arrival") return row.actual_arrival ?? ""
  const v = (row as unknown as Record<string, unknown>)[key]
  return typeof v === "string" ? v.toLowerCase() : ""
}

function FailuresTable({ side, bounds }: { side: Side; bounds: { start: string; end: string } }) {
  // Pull both buckets in parallel; merge into one sortable list.
  const our = useDfwServiceFailures(side, "our", bounds, 1, 200)
  const not = useDfwServiceFailures(side, "not", bounds, 1, 200)

  const [sortKey, setSortKey] = useState<SortKey>("counted")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  const loading = our.isLoading || not.isLoading

  const rows: FailRow[] = useMemo(() => {
    const merged: FailRow[] = [
      ...(our.data?.data ?? []).map((r) => ({ ...r, counted: true })),
      ...(not.data?.data ?? []).map((r) => ({ ...r, counted: false })),
    ]
    const dir = sortDir === "asc" ? 1 : -1
    return merged.sort((a, b) => {
      const av = cmpVal(a, sortKey)
      const bv = cmpVal(b, sortKey)
      if (av < bv) return -1 * dir
      if (av > bv) return 1 * dir
      // tiebreak: counted first, then most recent
      if (a.counted !== b.counted) return a.counted ? -1 : 1
      return (b.actual_arrival ?? "").localeCompare(a.actual_arrival ?? "")
    })
  }, [our.data, not.data, sortKey, sortDir])

  const onSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(key)
      setSortDir(key === "counted" ? "desc" : "asc")
    }
  }

  return (
    <div className="overflow-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
          <tr className="border-b border-[#E5E7EB]">
            {COLUMNS.map((c) => (
              <th
                key={c.key}
                onClick={() => onSort(c.key)}
                className="cursor-pointer select-none px-2 py-1.5 text-left hover:text-[#111827]"
              >
                <span className="inline-flex items-center gap-1">
                  {c.label}
                  {sortKey === c.key &&
                    (sortDir === "asc" ? (
                      <ArrowUp className="h-3 w-3" />
                    ) : (
                      <ArrowDown className="h-3 w-3" />
                    ))}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={COLUMNS.length} className="py-10 text-center">
                <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
              </td>
            </tr>
          ) : rows.length === 0 ? (
            <tr>
              <td colSpan={COLUMNS.length} className="py-10 text-center text-[#9CA3AF]">
                No service failures in this window
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <FailureRow key={`${r.counted ? "our" : "not"}-${r.id}`} row={r} />
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

function FailureRow({ row }: { row: FailRow }) {
  return (
    <tr className={`border-b border-[#F3F4F6] ${row.counted ? "" : "opacity-70"}`}>
      <td className="px-2 py-1.5">
        {row.counted ? (
          <span className="rounded bg-[#FEE2E2] px-1.5 py-0.5 text-[10px] text-[#991B1B]">
            Counted
          </span>
        ) : (
          <span className="rounded bg-[#F3F4F6] px-1.5 py-0.5 text-[10px] text-[#6B7280]">
            Not counted
          </span>
        )}
      </td>
      <td className="px-2 py-1.5 font-mono text-[11px]">{row.id}</td>
      <td className="px-2 py-1.5">{row.team_dfw ?? "—"}</td>
      <td
        className="max-w-[180px] truncate px-2 py-1.5"
        title={row.customer_name ?? undefined}
      >
        {row.customer_name ?? "—"}
      </td>
      <td className="px-2 py-1.5">
        <span className="rounded bg-[#F3F4F6] px-1.5 py-0.5 font-mono text-[10px]">
          {row.edi_standard_code ?? "—"}
        </span>
      </td>
      <td
        className="max-w-[160px] truncate px-2 py-1.5"
        title={row.edi_code_descr ?? undefined}
      >
        {row.edi_code_descr ?? "—"}
      </td>
      <td
        className="max-w-[260px] truncate px-2 py-1.5"
        title={row.dsp_comment ?? undefined}
      >
        {row.dsp_comment ?? "—"}
      </td>
      <td className="px-2 py-1.5 font-mono text-[11px]">
        {row.entered_user_id ?? "—"}
      </td>
      <td className="px-2 py-1.5 text-[#6B7280]">
        {fmtDate(row.actual_arrival)}
      </td>
    </tr>
  )
}
