"use client"

import { Loader2 } from "lucide-react"
import type { SavingsTeamRow } from "@/lib/api"

const CURRENCY = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const DECIMAL1 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
})

function fmtCurrency(v: number): string {
  if (!Number.isFinite(v)) return "—"
  return CURRENCY.format(v)
}

function fmtPct(v: number): string {
  if (!Number.isFinite(v)) return "—"
  return `${DECIMAL1.format(v)}%`
}

interface TeamSummaryTableProps {
  rows: SavingsTeamRow[]
  loading?: boolean
}

export function TeamSummaryTable({ rows, loading }: TeamSummaryTableProps) {
  const totals = rows.reduce(
    (acc, r) => ({
      loads: acc.loads + r.loads,
      total_savings: acc.total_savings + r.total_savings,
      total_overpay: acc.total_overpay + r.total_overpay,
      net_variance: acc.net_variance + r.net_variance,
    }),
    { loads: 0, total_savings: 0, total_overpay: 0, net_variance: 0 },
  )

  const savingsBase = totals.total_savings || 1
  const overpayBase = totals.total_overpay || 1

  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="border-b border-[#E5E7EB] bg-[#F9FAFB] px-4 py-2 text-sm font-semibold text-[#1B3A5C]">
        Team Summary
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-[#F9FAFB] text-xs uppercase tracking-wider text-[#6B7280]">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Division</th>
              <th className="px-3 py-2 text-left font-medium">Team</th>
              <th className="px-3 py-2 text-right font-medium">Total Savings</th>
              <th className="px-3 py-2 text-right font-medium">% Savings</th>
              <th className="px-3 py-2 text-right font-medium">Avg Saving × Load</th>
              <th className="px-3 py-2 text-right font-medium">Total Overpay</th>
              <th className="px-3 py-2 text-right font-medium">% Overpay</th>
              <th className="px-3 py-2 text-right font-medium">Net Variance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {/* Sticky-ish total row on top */}
            <tr className="bg-[#F3F4F6] font-semibold text-[#111827]">
              <td className="px-3 py-2">Total</td>
              <td className="px-3 py-2 text-[#6B7280]"></td>
              <td className="px-3 py-2 text-right tabular-nums">
                {fmtCurrency(totals.total_savings)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">100.0%</td>
              <td className="px-3 py-2 text-right tabular-nums">
                {totals.loads > 0
                  ? fmtCurrency(totals.total_savings / totals.loads).replace("$", "$")
                  : "—"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-[#DC2626]">
                {fmtCurrency(totals.total_overpay)}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">100.0%</td>
              <td
                className={`px-3 py-2 text-right tabular-nums ${
                  totals.net_variance >= 0 ? "text-[#059669]" : "text-[#DC2626]"
                }`}
              >
                {fmtCurrency(totals.net_variance)}
              </td>
            </tr>

            {loading && rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin text-[#6B7280]" />
                </td>
              </tr>
            )}

            {!loading && rows.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-xs text-[#9CA3AF]">
                  No teams match the current filters
                </td>
              </tr>
            )}

            {rows.map((r) => {
              const pctSavings = (r.total_savings / savingsBase) * 100
              const pctOverpay = (r.total_overpay / overpayBase) * 100
              const avgPerLoad = r.loads > 0 ? r.total_savings / r.loads : 0
              return (
                <tr key={`${r.division}-${r.team_id}`} className="hover:bg-[#F9FAFB]">
                  <td className="px-3 py-2 text-[#374151]">{r.division}</td>
                  <td className="px-3 py-2 font-medium text-[#111827]">{r.team_id}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {fmtCurrency(r.total_savings)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#6B7280]">
                    {fmtPct(pctSavings)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#6B7280]">
                    {r.loads > 0 ? `$${DECIMAL1.format(avgPerLoad)}` : "—"}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#DC2626]">
                    {fmtCurrency(r.total_overpay)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#6B7280]">
                    {fmtPct(pctOverpay)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums font-medium ${
                      r.net_variance >= 0 ? "text-[#059669]" : "text-[#DC2626]"
                    }`}
                  >
                    {fmtCurrency(r.net_variance)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
