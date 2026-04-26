"use client"

import { useState } from "react"
import {
  useOcsDelDetail,
  useOcsFaultRows,
  useOcsPuDetail,
  type OcsDetail,
  type OcsFilters,
} from "@/lib/ops-customer-score-api"
import { OcsErrorBanner } from "../ErrorBanner"
import { fmtCount, fmtPct, fmtTimestamp, onTimeColor } from "../format"

interface Props {
  filters: OcsFilters
  side: "pu" | "del"
}

const PAGE_SIZE = 200

function FaultBlock({
  filters,
  side,
  fault,
  totals,
  arrivalLabel,
  schedLateLabel,
}: {
  filters: OcsFilters
  side: "pu" | "del"
  fault: "our" | "not"
  totals: { fail: number; pct_on_time: number | null }
  arrivalLabel: string
  schedLateLabel: string
}) {
  const [page, setPage] = useState(1)
  const rowsQuery = useOcsFaultRows(filters, side, fault, page, PAGE_SIZE)
  const rows = rowsQuery.data?.data ?? []
  const total = rowsQuery.data?.meta?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const headerLabel = fault === "our" ? "Our Fault" : "Not our Fault"
  const sideLabel = side === "pu" ? "PU" : "DEL"
  const titleAccent =
    fault === "our"
      ? "border-[#FCA5A5] bg-[#FEF2F2] text-[#991B1B]"
      : "border-[#A7F3D0] bg-[#F0FDF4] text-[#065F46]"
  const failTitle = `${sideLabel} Service Fail`

  return (
    <div className={`rounded-md border ${titleAccent.split(" ")[0]} bg-white`}>
      <div
        className={`px-3 py-2 text-sm font-medium border-b ${titleAccent}`}
      >
        {headerLabel}
      </div>
      <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2">
        <div className="rounded-md border border-[#E5E7EB] bg-white p-3 text-center">
          <div className="text-xs uppercase tracking-wide text-[#6B7280]">
            {failTitle}
          </div>
          <div className="mt-1 text-3xl font-bold text-[#DC2626]">
            {fmtCount(totals.fail)}
          </div>
        </div>
        <div className="rounded-md border border-[#E5E7EB] bg-white p-3 text-center">
          <div className="text-xs uppercase tracking-wide text-[#6B7280]">
            % On Time
          </div>
          <div className={`mt-1 text-3xl font-bold ${onTimeColor(totals.pct_on_time)}`}>
            {fmtPct(totals.pct_on_time)}
          </div>
        </div>
      </div>
      <div className="px-3 pb-3">
        <div className="rounded-md border border-[#E5E7EB] bg-white">
          <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-[#F9FAFB] text-[#6B7280] sticky top-0">
                <tr>
                  <th className="px-2 py-2 text-left">Order</th>
                  <th className="px-2 py-2 text-left">Team</th>
                  <th className="px-2 py-2 text-left">Customer</th>
                  <th className="px-2 py-2 text-left">{arrivalLabel}</th>
                  <th className="px-2 py-2 text-left">{schedLateLabel}</th>
                  <th className="px-2 py-2 text-left">Cod</th>
                  <th className="px-2 py-2 text-left">Delay Descr</th>
                  <th className="px-2 py-2 text-left">Comment</th>
                  <th className="px-2 py-2 text-left">Carrier</th>
                  <th className="px-2 py-2 text-left">Entered by</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="border-t border-[#F3F4F6]">
                    <td className="px-2 py-1.5 font-mono text-[#111827]">
                      {r.id}
                    </td>
                    <td className="px-2 py-1.5">{r.team_id || "—"}</td>
                    <td className="px-2 py-1.5">{r.customer_name || "—"}</td>
                    <td className="px-2 py-1.5">
                      {fmtTimestamp(r.actual_arrival)}
                    </td>
                    <td className="px-2 py-1.5">
                      {fmtTimestamp(r.sched_late)}
                    </td>
                    <td className="px-2 py-1.5 font-mono">
                      {r.edi_standard_code || "—"}
                    </td>
                    <td className="px-2 py-1.5">{r.edi_code_descr || "—"}</td>
                    <td className="px-2 py-1.5 max-w-[280px] truncate" title={r.dsp_comment ?? ""}>
                      {r.dsp_comment || "—"}
                    </td>
                    <td className="px-2 py-1.5">{r.payee_name || "—"}</td>
                    <td className="px-2 py-1.5 font-mono">
                      {r.entered_user_id || "—"}
                    </td>
                  </tr>
                ))}
                {!rows.length && (
                  <tr>
                    <td
                      colSpan={10}
                      className="px-3 py-6 text-center text-[#9CA3AF]"
                    >
                      {rowsQuery.isLoading ? "Loading…" : "No rows in window"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
        <div className="mt-2 flex items-center justify-between text-xs text-[#6B7280]">
          <div>
            {fmtCount(total)} rows · page {page} of {pages}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              className="rounded border border-[#E5E7EB] bg-white px-2 py-1 disabled:opacity-50"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              ← Prev
            </button>
            <button
              type="button"
              className="rounded border border-[#E5E7EB] bg-white px-2 py-1 disabled:opacity-50"
              disabled={page >= pages}
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
            >
              Next →
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function HeaderKpis({ d, side }: { d: OcsDetail | undefined; side: "pu" | "del" }) {
  const sideLabel = side === "pu" ? "PU" : "DEL"
  const orderLabel = `${sideLabel} Order`
  const failLabel = `${sideLabel} Service Fail`
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      <div className="rounded-md border border-[#E5E7EB] bg-white p-4 text-center">
        <div className="text-xs uppercase tracking-wide text-[#6B7280]">
          {orderLabel}
        </div>
        <div className="mt-1 text-3xl font-bold text-[#111827]">
          {fmtCount(d?.kpi.orders ?? 0)}
        </div>
      </div>
      <div className="rounded-md border border-[#E5E7EB] bg-white p-4 text-center">
        <div className="text-xs uppercase tracking-wide text-[#6B7280]">
          {failLabel}
        </div>
        <div className="mt-1 text-3xl font-bold text-[#DC2626]">
          {fmtCount(d?.kpi.fail ?? 0)}
        </div>
      </div>
      <div className="rounded-md border border-[#E5E7EB] bg-white p-4 text-center">
        <div className="text-xs uppercase tracking-wide text-[#6B7280]">
          % On Time
        </div>
        <div className={`mt-1 text-3xl font-bold ${onTimeColor(d?.kpi.pct_on_time ?? null)}`}>
          {fmtPct(d?.kpi.pct_on_time ?? null)}
        </div>
      </div>
    </div>
  )
}

export function Detail({ filters, side }: Props) {
  const detailQuery = side === "pu"
    ? useOcsPuDetail(filters)
    : useOcsDelDetail(filters)
  const d = detailQuery.data?.data
  const sideLabel = side === "pu" ? "PU" : "DEL"
  const orderColumn = `${sideLabel} Order`
  const failColumn = `${sideLabel} Service Fail`
  const arrivalLabel = side === "pu" ? "Orig Actual Arrival" : "Dest Actual Arrival"
  const schedLateLabel = side === "pu" ? "Orig Sched Late" : "Dest Sched Late"

  return (
    <div className="space-y-4">
      <OcsErrorBanner errors={[detailQuery.error]} label={`${sideLabel} Detail`} />

      <HeaderKpis d={d} side={side} />

      {/* Summary by Customer */}
      <div className="rounded-md border border-[#E5E7EB] bg-white">
        <div className="px-3 py-2 text-sm font-medium text-[#374151] border-b border-[#E5E7EB]">
          Summary by Customer ({sideLabel})
        </div>
        <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="bg-[#F9FAFB] text-[#6B7280] sticky top-0">
              <tr>
                <th className="px-3 py-2 text-left">Customer</th>
                <th className="px-3 py-2 text-right">{orderColumn}</th>
                <th className="px-3 py-2 text-right">{failColumn}</th>
                <th className="px-3 py-2 text-right">% On Time</th>
              </tr>
            </thead>
            <tbody>
              {(d?.by_customer ?? []).map((r) => (
                <tr
                  key={r.customer_name ?? "?"}
                  className="border-t border-[#F3F4F6]"
                >
                  <td className="px-3 py-2 text-[#111827]">
                    {r.customer_name || "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {fmtCount(r.orders)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#DC2626]">
                    {fmtCount(r.fail)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums ${onTimeColor(r.pct_on_time)}`}
                  >
                    {fmtPct(r.pct_on_time)}
                  </td>
                </tr>
              ))}
              {!d?.by_customer.length && (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-center text-[#9CA3AF]">
                    {detailQuery.isLoading ? "Loading…" : "No data"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Summary by Lane */}
      <div className="rounded-md border border-[#E5E7EB] bg-white">
        <div className="px-3 py-2 text-sm font-medium text-[#374151] border-b border-[#E5E7EB]">
          Summary by Lane ({sideLabel}) — top 500
        </div>
        <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="bg-[#F9FAFB] text-[#6B7280] sticky top-0">
              <tr>
                <th className="px-3 py-2 text-left">Customer</th>
                <th className="px-3 py-2 text-left">Origin</th>
                <th className="px-3 py-2 text-left">Destination</th>
                <th className="px-3 py-2 text-right">{orderColumn}</th>
                <th className="px-3 py-2 text-right">{failColumn}</th>
                <th className="px-3 py-2 text-right">% On Time</th>
              </tr>
            </thead>
            <tbody>
              {(d?.by_lane ?? []).map((r, i) => (
                <tr key={i} className="border-t border-[#F3F4F6]">
                  <td className="px-3 py-2 text-[#111827]">
                    {r.customer_name || "—"}
                  </td>
                  <td className="px-3 py-2">{r.origin || "—"}</td>
                  <td className="px-3 py-2">{r.destination || "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {fmtCount(r.orders)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#DC2626]">
                    {fmtCount(r.fail)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums ${onTimeColor(r.pct_on_time)}`}
                  >
                    {fmtPct(r.pct_on_time)}
                  </td>
                </tr>
              ))}
              {!d?.by_lane.length && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-[#9CA3AF]">
                    {detailQuery.isLoading ? "Loading…" : "No data"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Our Fault container */}
      <FaultBlock
        filters={filters}
        side={side}
        fault="our"
        totals={d?.our_fault_kpi ?? { fail: 0, pct_on_time: null }}
        arrivalLabel={arrivalLabel}
        schedLateLabel={schedLateLabel}
      />

      {/* Not our Fault container */}
      <FaultBlock
        filters={filters}
        side={side}
        fault="not"
        totals={d?.not_fault_kpi ?? { fail: 0, pct_on_time: null }}
        arrivalLabel={arrivalLabel}
        schedLateLabel={schedLateLabel}
      />
    </div>
  )
}
