"use client"

import { useEffect } from "react"
import { Loader2, X } from "lucide-react"
import {
  fmtAttritionPct,
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtUsdSigned,
  useOppTeamWeekly,
  type OppFilters,
  type OppWeekPerf,
} from "@/lib/ops-portal-overview-api"

interface Props {
  filters: OppFilters
  onClose: () => void
}

// "attritionPct" carries attrition-wow's signed "% Δ" — INVERTED colours,
// positive = red (Bruno PDF 2026-08-31 R3, §95). It is its own kind rather
// than `pct` + `signed` because `signed` colours negatives red, which is
// exactly backwards here: a negative % Δ means the active roster GREW.
type Kind = "count" | "usd" | "usdSigned" | "pct" | "attritionPct"

// Mirrors the §5 Team Monthly Performance row set, split into the last 5 weeks.
const ROWS: {
  label: string
  field: keyof OppWeekPerf
  kind: Kind
  signed?: boolean
  highlight?: boolean
  band?: boolean
}[] = [
  { label: "Customers",        field: "customers",  kind: "count" },
  { label: "Lanes",            field: "lanes",      kind: "count" },
  { label: "Volume",           field: "volume",     kind: "count", highlight: true },
  { label: "Revenue",          field: "revenue",    kind: "usd" },
  { label: "Total Cost",       field: "total_cost", kind: "usd" },
  { label: "Profit",           field: "profit",     kind: "usd", signed: true, highlight: true },
  { label: "Margin P %",       field: "margin_pct", kind: "pct", signed: true, highlight: true },
  { label: "Rev. x L.",        field: "rev_x_l",    kind: "usd" },
  { label: "Prf. X L.",        field: "prof_x_l",   kind: "usd", signed: true },
  { label: "Team Ut.",         field: "team_ut",    kind: "pct" },
  { label: "OTP.",             field: "otp_pct",    kind: "pct", band: true },
  { label: "Lates PU",         field: "lates_pu",   kind: "count" },
  { label: "OTD.",             field: "otd_pct",    kind: "pct", band: true },
  { label: "Lates DEL.",       field: "lates_del",  kind: "count" },
  { label: "Savings.",         field: "savings",    kind: "usd" },
  { label: "Over Pay",         field: "over_pay",   kind: "usd", signed: true },
  { label: "Net Savings",      field: "net_savings", kind: "usdSigned", signed: true },
  { label: "Loads w/ Loss.",   field: "loss_loads", kind: "count" },
  { label: "Total Negative Loads Losses", field: "profit_loss", kind: "usdSigned", signed: true },
  { label: "Cust. Attrition %", field: "cust_attr_pct", kind: "attritionPct" },
  { label: "Lane Attrition %", field: "lane_attr_pct", kind: "attritionPct" },
]

function fmtVal(kind: Kind, v: number): string {
  if (kind === "count") return fmtCount(v)
  if (kind === "usd") return fmtUsd(v)
  if (kind === "usdSigned") return fmtUsdSigned(v)
  if (kind === "attritionPct") return fmtAttritionPct(v).text
  return fmtPct(v)
}

function bandCls(pct: number): string {
  if (pct >= 95.5) return "bg-[#DCFCE7] text-[#166534]"
  if (pct >= 93) return "bg-[#FEF9C3] text-[#854D0E]"
  return "bg-[#FEE2E2] text-[#991B1B]"
}

export function TeamWeeklyModal({ filters, onClose }: Props) {
  const cf = { team: filters.team, customer: filters.customer, loadType: filters.loadType, lanes: filters.lanes, excludeLanes: filters.excludeLanes }
  const { data, isLoading, error } = useOppTeamWeekly(cf, true)
  const weeks: OppWeekPerf[] = data?.data?.weeks ?? []

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
            <div className="text-sm font-semibold text-[#1B3A5C]">Weekly Performance</div>
            <span className="text-xs text-[#6B7280]">· last 5 weeks (Mon–Sun)</span>
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
              Weekly performance query failed: {(error as Error).message}
            </div>
          )}
          {!isLoading && !error && (
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#E5E7EB] text-[#6B7280]">
                  <th className="px-2 py-2 text-left font-semibold uppercase tracking-wider text-[10px]">
                    Metric
                  </th>
                  {weeks.map((w) => (
                    <th key={w.start} className="px-2 py-2 text-right font-semibold text-[#1B3A5C]">
                      {w.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ROWS.map((row) => (
                  <tr
                    key={row.label}
                    className={`border-b border-[#F3F4F6] ${row.highlight ? "bg-[#F0F9FF]" : ""}`}
                  >
                    <td className={`px-2 py-1.5 ${row.highlight ? "font-semibold text-[#1B3A5C]" : "text-[#6B7280]"}`}>
                      {row.label}
                    </td>
                    {weeks.map((w) => {
                      const v = Number(w[row.field] ?? 0)
                      const neg = row.signed && v < 0
                      // ⚠ Attrition colours are inverted, so they cannot go
                      // through `neg` — see the Kind comment above.
                      const attrCls =
                        row.kind === "attritionPct" ? fmtAttritionPct(v).className : null
                      return (
                        <td key={w.start} className="px-2 py-1.5 text-right tabular-nums">
                          {row.band ? (
                            <span className={`rounded px-1.5 py-0.5 font-semibold ${bandCls(v)}`}>
                              {fmtVal(row.kind, v)}
                            </span>
                          ) : (
                            <span
                              className={`${attrCls ?? (neg ? "text-[#DC2626]" : "text-[#374151]")} ${
                                row.highlight ? "font-bold text-[#1B3A5C]" : ""
                              }`}
                            >
                              {fmtVal(row.kind, v)}
                            </span>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
