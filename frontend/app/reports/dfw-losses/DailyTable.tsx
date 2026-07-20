"use client"

import { Loader2 } from "lucide-react"
import { useDfwLossesDaily, type DfwLossesFilters } from "@/lib/dfw-losses-api"
import { DfwLossesErrorBanner } from "./ErrorBanner"
import { fmtUsd, fmtCount, fmtLossCell } from "./format"

export function DailyTable({ filters }: { filters: DfwLossesFilters }) {
  const { data, isLoading, isFetching, error } = useDfwLossesDaily(filters)
  const d = data?.data
  const customers = d?.customers ?? []
  const rows = d?.rows ?? []
  const summary = d?.summary

  return (
    <section className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-[#E5E7EB] px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-[#1B3A5C]">DFW Losses — Daily</h2>
          {d?.customers_truncated && (
            <span className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[10px] text-[#92400E]">
              Top {customers.length} customers shown
            </span>
          )}
        </div>
        {isFetching && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
      </div>

      <div className="px-4 pt-3">
        <DfwLossesErrorBanner errors={[error]} label="Daily" />
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
        </div>
      ) : rows.length === 0 ? (
        <div className="px-4 py-12 text-center text-sm text-[#6B7280]">
          No activity in the selected window.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-[#E5E7EB] bg-[#F9FAFB] text-left text-[#6B7280]">
                <th className="sticky left-0 z-10 bg-[#F9FAFB] px-3 py-2 font-semibold">Day</th>
                <th className="px-3 py-2 font-semibold">Month</th>
                <th className="px-3 py-2 text-right font-semibold">Loads</th>
                <th className="px-3 py-2 text-right font-semibold">Amount Lost</th>
                <th className="px-3 py-2 text-right font-semibold">Loss / Load</th>
                {customers.map((c) => (
                  <th
                    key={c}
                    className="max-w-[140px] truncate px-3 py-2 text-right font-semibold"
                    title={c}
                  >
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={r.date}
                  className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]"
                >
                  <td className="sticky left-0 z-10 bg-white px-3 py-1.5 font-medium text-[#111827]">
                    {r.day}
                  </td>
                  <td className="px-3 py-1.5 text-[#374151]">{r.month}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#111827]">
                    {fmtCount(r.loads)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#DC2626]">
                    {fmtUsd(r.amount_lost)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#B45309]">
                    {fmtUsd(r.loss_per_load)}
                  </td>
                  {customers.map((c) => {
                    const v = r.by_customer[c] ?? 0
                    return (
                      <td
                        key={c}
                        className={`px-3 py-1.5 text-right tabular-nums ${
                          v < 0 ? "text-[#DC2626]" : "text-[#9CA3AF]"
                        }`}
                      >
                        {fmtLossCell(v)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
            {summary && (
              <tfoot>
                <tr className="border-t-2 border-[#E5E7EB] bg-[#F3F4F6] font-semibold text-[#111827]">
                  <td className="sticky left-0 z-10 bg-[#F3F4F6] px-3 py-2">Avg</td>
                  <td className="px-3 py-2" />
                  <td className="px-3 py-2 text-right tabular-nums">
                    {fmtCount(Math.round(summary.loads_avg))}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#DC2626]">
                    {fmtUsd(summary.amount_lost_avg)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#B45309]">
                    {fmtUsd(summary.loss_per_load_avg)}
                  </td>
                  {customers.map((c) => (
                    <td key={c} className="px-3 py-2" />
                  ))}
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </section>
  )
}
