"use client"

import { useEffect } from "react"
import { Loader2, X } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtUsdSigned,
  useOppTeamPerformanceByTeam,
  type OppFilters,
  type OppTeamPerformance,
} from "@/lib/ops-portal-overview-api"

interface Props {
  filters: OppFilters
  onClose: () => void
}

type Kind = "count" | "usd" | "usdSigned" | "pct"

// Mirrors the §5 Team Monthly Performance row set, broken out by team (one column per team).
// `conc` marks count/volume rows where a per-team concentration % (team / total) is meaningful.
// Field is a wire key OR the derived "cost_x_load" (total_cost / volume).
type RowField = keyof OppTeamPerformance | "cost_x_load"

const ROWS: {
  label: string
  field: RowField
  kind: Kind
  signed?: boolean
  highlight?: boolean
  band?: boolean
  conc?: boolean
}[] = [
  { label: "Customers",        field: "customers",  kind: "count", conc: true },
  { label: "Lanes",            field: "lanes",      kind: "count", conc: true },
  { label: "Volume",           field: "volume",     kind: "count", highlight: true, conc: true },
  { label: "Revenue",          field: "revenue",    kind: "usd", conc: true },
  { label: "Total Cost",       field: "total_cost", kind: "usd", conc: true },
  { label: "Profit",           field: "profit",     kind: "usd", signed: true, highlight: true, conc: true },
  { label: "Margin P %",       field: "margin_pct", kind: "pct", signed: true, highlight: true },
  { label: "Rev. x L.",        field: "rev_x_l",    kind: "usd" },
  { label: "Prf. X L.",        field: "prof_x_l",   kind: "usd", signed: true },
  { label: "Cost x Load",      field: "cost_x_load", kind: "usd" },
  { label: "Team Ut.",         field: "team_ut",    kind: "pct" },
  { label: "OTP.",             field: "otp_pct",    kind: "pct", band: true },
  { label: "Lates PU",         field: "lates_pu",   kind: "count", conc: true },
  { label: "OTD.",             field: "otd_pct",    kind: "pct", band: true },
  { label: "Lates DEL.",       field: "lates_del",  kind: "count", conc: true },
  { label: "Savings.",         field: "savings",    kind: "usd", conc: true },
  { label: "Over Pay",         field: "over_pay",   kind: "usd", signed: true },
  { label: "Net Savings",      field: "net_savings", kind: "usdSigned", signed: true },
  { label: "Loads w/ Loss.",   field: "loss_loads", kind: "count", conc: true },
  { label: "Profit Loss",      field: "profit_loss", kind: "usdSigned", signed: true },
  { label: "Cust. Attrition %", field: "cust_attr_pct", kind: "pct" },
  { label: "Lane Attrition %", field: "lane_attr_pct", kind: "pct" },
]

// "Cost x Load" is derived (total_cost / volume) — not a wire field, so read it via this helper.
function fieldVal(row: OppTeamPerformance, field: RowField): number {
  if (field === "cost_x_load") {
    const vol = Number(row.volume ?? 0)
    return vol > 0 ? Number(row.total_cost ?? 0) / vol : 0
  }
  return Number(row[field] ?? 0)
}

function fmtVal(kind: Kind, v: number): string {
  if (kind === "count") return fmtCount(v)
  if (kind === "usd") return fmtUsd(v)
  if (kind === "usdSigned") return fmtUsdSigned(v)
  return fmtPct(v)
}

function bandCls(pct: number): string {
  if (pct >= 95.5) return "bg-[#DCFCE7] text-[#166534]"
  if (pct >= 93) return "bg-[#FEF9C3] text-[#854D0E]"
  return "bg-[#FEE2E2] text-[#991B1B]"
}

export function TeamMonthlyModal({ filters, onClose }: Props) {
  const { data, isLoading, error } = useOppTeamPerformanceByTeam(filters)
  const total = data?.data?.total
  const teams = data?.data?.teams ?? []

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#E5E7EB] bg-[#F0F9FF] px-4 py-3">
          <div className="flex items-center gap-2">
            <span aria-hidden>📈</span>
            <div className="text-sm font-semibold text-[#1B3A5C]">Team Monthly Performance</div>
            <span className="text-xs text-[#6B7280]">· by team</span>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-[#6B7280] hover:bg-white hover:text-[#111827]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
            </div>
          )}
          {!!error && !isLoading && (
            <div className="rounded-lg border border-[#FCA5A5] bg-[#FEE2E2] px-3 py-2 text-xs text-[#991B1B]">
              Monthly performance query failed: {(error as Error).message}
            </div>
          )}
          {!isLoading && !error && (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#E5E7EB] text-[#6B7280]">
                  <th className="px-2 py-2 text-left font-semibold uppercase tracking-wider text-[10px]">
                    Metric
                  </th>
                  <th className="px-2 py-2 text-right font-semibold text-[#1B3A5C]">Total</th>
                  {teams.map((t) => (
                    <th key={t.team_id} className="px-2 py-2 text-right font-semibold text-[#1B3A5C]">
                      {t.team_id}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ROWS.map((row) => {
                  const totalVal = total ? fieldVal(total, row.field) : 0
                  return (
                    <tr
                      key={row.label}
                      className={`border-b border-[#F3F4F6] ${row.highlight ? "bg-[#F0F9FF]" : ""}`}
                    >
                      <td className={`px-2 py-1.5 ${row.highlight ? "font-semibold text-[#1B3A5C]" : "text-[#6B7280]"}`}>
                        {row.label}
                      </td>
                      <td className="px-2 py-1.5 text-right tabular-nums">
                        {row.band ? (
                          <span className={`rounded px-1.5 py-0.5 font-semibold ${bandCls(totalVal)}`}>
                            {fmtVal(row.kind, totalVal)}
                          </span>
                        ) : (
                          <span
                            className={`${row.signed && totalVal < 0 ? "text-[#DC2626]" : "text-[#374151]"} ${
                              row.highlight ? "font-bold text-[#1B3A5C]" : ""
                            }`}
                          >
                            {fmtVal(row.kind, totalVal)}
                          </span>
                        )}
                      </td>
                      {teams.map((t) => {
                        const v = fieldVal(t, row.field)
                        const neg = row.signed && v < 0
                        const conc = row.conc && totalVal !== 0 ? (v / totalVal) * 100 : null
                        return (
                          <td key={t.team_id} className="px-2 py-1.5 text-right tabular-nums">
                            {row.band ? (
                              <span className={`rounded px-1.5 py-0.5 font-semibold ${bandCls(v)}`}>
                                {fmtVal(row.kind, v)}
                              </span>
                            ) : (
                              <span className="inline-flex items-baseline gap-1">
                                <span
                                  className={`${neg ? "text-[#DC2626]" : "text-[#374151]"} ${
                                    row.highlight ? "font-bold text-[#1B3A5C]" : ""
                                  }`}
                                >
                                  {fmtVal(row.kind, v)}
                                </span>
                                {conc !== null && (
                                  <span className="text-[#2563EB] text-[10px]">{conc.toFixed(2)}%</span>
                                )}
                              </span>
                            )}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
