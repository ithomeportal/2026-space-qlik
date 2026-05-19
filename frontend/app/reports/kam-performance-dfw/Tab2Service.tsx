"use client"

import { useState } from "react"
import { CheckCircle2, Loader2 } from "lucide-react"
import {
  KAM_CURRENT_WEEK,
  useDfwServiceFailures,
  useDfwServiceKpi,
} from "@/lib/kam-performance-dfw-api"
import { fmtCount, fmtDate, fmtPct } from "./format"

type Side = "pu" | "del"

export function Tab2Service() {
  const [side, setSide] = useState<Side>("pu")
  const { start, end } = KAM_CURRENT_WEEK()
  const { data: puKpi, isLoading: loadingPu } = useDfwServiceKpi("pu")
  const { data: delKpi, isLoading: loadingDel } = useDfwServiceKpi("del")

  const otp = puKpi?.data?.kpi
  const otd = delKpi?.data?.kpi

  return (
    <div className="space-y-4">
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
        Current week ({start} → {end}, Mon-anchored) · scope: TEAM-DFW · source:
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
            Counted first, then not-counted
          </span>
        </div>
        <FailuresTable side={side} />
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

function FailuresTable({ side }: { side: Side }) {
  // Pull both buckets in parallel; render counted first then not-counted.
  const our = useDfwServiceFailures(side, "our", 1, 200)
  const not = useDfwServiceFailures(side, "not", 1, 200)

  const ourRows = our.data?.data ?? []
  const notRows = not.data?.data ?? []
  const loading = our.isLoading || not.isLoading
  const total = ourRows.length + notRows.length

  return (
    <div className="overflow-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
          <tr className="border-b border-[#E5E7EB]">
            <th className="px-2 py-1.5 text-left">Order</th>
            <th className="px-2 py-1.5 text-left">Team</th>
            <th className="px-2 py-1.5 text-left">Customer</th>
            <th className="px-2 py-1.5 text-left">Code</th>
            <th className="px-2 py-1.5 text-left">Delay Descr</th>
            <th className="px-2 py-1.5 text-left">Comment</th>
            <th className="px-2 py-1.5 text-left">Entered by</th>
            <th className="px-2 py-1.5 text-left">When</th>
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={8} className="py-10 text-center">
                <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
              </td>
            </tr>
          ) : total === 0 ? (
            <tr>
              <td colSpan={8} className="py-10 text-center text-[#9CA3AF]">
                No service failures this week
              </td>
            </tr>
          ) : (
            <>
              {ourRows.length > 0 && (
                <tr>
                  <td
                    colSpan={8}
                    className="bg-[#FEF2F2] px-2 py-1 text-[10px] uppercase tracking-wider text-[#991B1B]"
                  >
                    Counted ({ourRows.length})
                  </td>
                </tr>
              )}
              {ourRows.map((r) => (
                <FailureRow key={`our-${r.id}`} row={r} counted />
              ))}
              {notRows.length > 0 && (
                <tr>
                  <td
                    colSpan={8}
                    className="bg-[#F3F4F6] px-2 py-1 text-[10px] uppercase tracking-wider text-[#6B7280]"
                  >
                    Not counted ({notRows.length})
                  </td>
                </tr>
              )}
              {notRows.map((r) => (
                <FailureRow key={`not-${r.id}`} row={r} counted={false} />
              ))}
            </>
          )}
        </tbody>
      </table>
    </div>
  )
}

interface RowProps {
  row: {
    id: string
    team_id: string | null
    customer_name: string | null
    actual_arrival: string | null
    edi_standard_code: string | null
    edi_code_descr: string | null
    dsp_comment: string | null
    entered_user_id: string | null
  }
  counted: boolean
}

function FailureRow({ row, counted }: RowProps) {
  return (
    <tr className={`border-b border-[#F3F4F6] ${counted ? "" : "opacity-70"}`}>
      <td className="px-2 py-1.5 font-mono text-[11px]">{row.id}</td>
      <td className="px-2 py-1.5">{row.team_id ?? "—"}</td>
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
