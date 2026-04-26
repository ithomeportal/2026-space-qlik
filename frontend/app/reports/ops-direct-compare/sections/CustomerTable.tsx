"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import { fmtCount, fmtUsd, marginBgColor } from "../../ops-margins/format"
import { DCErrorBanner } from "../ErrorBanner"
import {
  useDCByCustomer,
  useDCByCustomerDiff,
  type DCPanelFilters,
} from "@/lib/ops-direct-compare-api"

interface Props {
  title: string
  panel: "p1" | "p2"
  panelFilters: DCPanelFilters       // primary panel filters
  diffAgainst?: DCPanelFilters       // when set, render diff columns (p2 - p1)
}

export function CustomerTable({ title, panel, panelFilters, diffAgainst }: Props) {
  const [sort, setSort] = useState<string>(
    diffAgainst ? "p2_profit_desc" : "profit_desc",
  )
  const single = useDCByCustomer(panel, panelFilters, { sort, limit: 200 })
  const diff = useDCByCustomerDiff(diffAgainst ?? panelFilters, panelFilters, {
    sort,
    limit: 200,
  })
  const active = diffAgainst ? diff : single
  const rows = active.data?.data ?? []
  const total = active.data?.meta?.total ?? 0
  const totals = rows.reduce(
    (acc, r) => {
      acc.loads += r.loads
      acc.revenue += r.revenue
      acc.profit += r.profit
      acc.diff_profit += r.diff_profit ?? 0
      acc.diff_revenue += r.diff_revenue ?? 0
      return acc
    },
    { loads: 0, revenue: 0, profit: 0, diff_profit: 0, diff_revenue: 0 },
  )
  const totalMarginPct =
    totals.revenue !== 0 ? (totals.profit / totals.revenue) * 100 : null

  const headerSort = (key: string) => {
    if (sort === `${key}_desc`) setSort(`${key}_asc`)
    else setSort(`${key}_desc`)
  }
  const arrow = (key: string) =>
    sort === `${key}_desc` ? "↓" : sort === `${key}_asc` ? "↑" : ""

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <DCErrorBanner errors={[active.error]} label={title} />
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#1B3A5C]">{title}</h3>
        <span className="text-[10px] text-[#6B7280]">
          {total.toLocaleString()} customers
        </span>
      </div>
      {active.isLoading ? (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-white">
              <tr className="border-b border-[#E5E7EB] text-[10px] uppercase tracking-wider text-[#6B7280]">
                <th className="px-2 py-2 text-left">Customer</th>
                <th
                  className="cursor-pointer px-2 py-2 text-right hover:text-[#111827]"
                  onClick={() => headerSort(diffAgainst ? "p2_loads" : "loads")}
                >
                  # Loads {arrow(diffAgainst ? "p2_loads" : "loads")}
                </th>
                <th
                  className="cursor-pointer px-2 py-2 text-right hover:text-[#111827]"
                  onClick={() => headerSort(diffAgainst ? "p2_revenue" : "revenue")}
                >
                  $ Revenue {arrow(diffAgainst ? "p2_revenue" : "revenue")}
                </th>
                <th
                  className="cursor-pointer px-2 py-2 text-right hover:text-[#111827]"
                  onClick={() => headerSort(diffAgainst ? "p2_profit" : "profit")}
                >
                  $ Profit {arrow(diffAgainst ? "p2_profit" : "profit")}
                </th>
                <th
                  className="cursor-pointer px-2 py-2 text-right hover:text-[#111827]"
                  onClick={() => headerSort("margin")}
                >
                  % Margin {arrow("margin")}
                </th>
                <th className="px-2 py-2 text-right">Avg $P / #L</th>
                {diffAgainst && (
                  <>
                    <th
                      className="cursor-pointer px-2 py-2 text-right hover:text-[#111827]"
                      onClick={() => headerSort("diff_profit")}
                    >
                      Diff $ Profit {arrow("diff_profit")}
                    </th>
                    <th
                      className="cursor-pointer px-2 py-2 text-right hover:text-[#111827]"
                      onClick={() => headerSort("diff_revenue")}
                    >
                      Diff $ Rev {arrow("diff_revenue")}
                    </th>
                  </>
                )}
              </tr>
              <tr className="border-b border-[#E5E7EB] bg-[#F9FAFB] font-semibold text-[#374151]">
                <td className="px-2 py-1.5">Totals</td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {fmtCount(totals.loads)}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {fmtUsd(totals.revenue)}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {fmtUsd(totals.profit)}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {totalMarginPct === null ? "—" : `${totalMarginPct.toFixed(2)}%`}
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">—</td>
                {diffAgainst && (
                  <>
                    <td
                      className={`px-2 py-1.5 text-right tabular-nums ${totals.diff_profit < 0 ? "text-[#DC2626]" : "text-[#16A34A]"}`}
                    >
                      {fmtUsd(totals.diff_profit)}
                    </td>
                    <td
                      className={`px-2 py-1.5 text-right tabular-nums ${totals.diff_revenue < 0 ? "text-[#DC2626]" : "text-[#16A34A]"}`}
                    >
                      {fmtUsd(totals.diff_revenue)}
                    </td>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr
                  key={`${r.customer}-${idx}`}
                  className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]"
                >
                  <td className="px-2 py-1.5 text-[#111827]" title={r.customer}>
                    {r.customer}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-[#374151]">
                    {fmtCount(r.loads)}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-[#374151]">
                    {fmtUsd(r.revenue)}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-[#374151]">
                    {fmtUsd(r.profit)}
                  </td>
                  <td
                    className={`px-2 py-1.5 text-right tabular-nums ${marginBgColor(r.margin_pct)}`}
                  >
                    {r.margin_pct === null ? "—" : `${r.margin_pct.toFixed(2)}%`}
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums text-[#374151]">
                    {fmtUsd(r.avg_p_per_l)}
                  </td>
                  {diffAgainst && (
                    <>
                      <td
                        className={`px-2 py-1.5 text-right tabular-nums ${(r.diff_profit ?? 0) < 0 ? "text-[#DC2626]" : "text-[#16A34A]"}`}
                      >
                        {fmtUsd(r.diff_profit ?? 0)}
                      </td>
                      <td
                        className={`px-2 py-1.5 text-right tabular-nums ${(r.diff_revenue ?? 0) < 0 ? "text-[#DC2626]" : "text-[#16A34A]"}`}
                      >
                        {fmtUsd(r.diff_revenue ?? 0)}
                      </td>
                    </>
                  )}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td
                    colSpan={diffAgainst ? 8 : 6}
                    className="px-2 py-4 text-center text-[#6B7280]"
                  >
                    No data in window.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
