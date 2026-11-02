"use client"

import { useState } from "react"
import { Loader2, Minus, Plus } from "lucide-react"
import {
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts"
import {
  fmtPct,
  fmtUsd,
  useCeoCustomers,
  type CeoFilters,
  type CeoTop5Row,
} from "@/lib/ceo-api"
import { CeoErrorBanner } from "../ErrorBanner"
import { CustomerLink } from "../customer-cell"
import { CustomerTable } from "../CustomerTable"
import type { CustomerSort } from "../customer-table-sort"

interface Props {
  filters: CeoFilters
  onCustomerSelect?: (customer: string) => void
}

// Server order of each list — the tables open in it and return to its wording.
const PROFIT_DEFAULT_SORT: CustomerSort = { key: "profit", dir: "desc" }
const WORST_DEFAULT_SORT: CustomerSort = { key: "profit", dir: "asc" }

const DONUT_COLORS = ["#0F766E", "#9F1239", "#CA8A04", "#7C3AED", "#0891B2", "#9CA3AF"]

export function Customers({ filters, onCustomerSelect }: Props) {
  const { data, isLoading, error } = useCeoCustomers(filters)
  const d = data?.data

  return (
    <div className="space-y-6">
      <CeoErrorBanner label="Customers" errors={[error]} />

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <CustomerTable
          title="Profit by Customer"
          tone="green"
          rows={d?.by_customer ?? []}
          loading={isLoading}
          defaultSort={PROFIT_DEFAULT_SORT}
          defaultHint="sorted by highest profit"
          count={d?.customer_count}
          showCount
          totals={d?.totals}
          onCustomerSelect={onCustomerSelect}
        />
        <CustomerTable
          title="Worst Profit by Customer"
          tone="red"
          rows={d?.worst_by_customer ?? []}
          loading={isLoading}
          defaultSort={WORST_DEFAULT_SORT}
          defaultHint="sorted by worst profit"
          count={d?.customer_count}
          totals={d?.totals}
          onCustomerSelect={onCustomerSelect}
        />
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Top5Panel
          title="% Customer Concentration by Revenue — Top 5"
          rows={d?.top5_revenue ?? []}
          others={d?.top5_revenue_others ?? []}
          loading={isLoading}
          metric="revenue"
          onCustomerSelect={onCustomerSelect}
        />
        <Top5Panel
          title="% Customer Concentration by Profit — Top 5"
          rows={d?.top5_profit ?? []}
          others={d?.top5_profit_others ?? []}
          loading={isLoading}
          metric="profit"
          onCustomerSelect={onCustomerSelect}
        />
      </section>
    </div>
  )
}

function Top5Panel({
  title,
  rows,
  others,
  loading,
  metric,
  onCustomerSelect,
}: {
  title: string
  rows: CeoTop5Row[]
  others: CeoTop5Row[]
  loading?: boolean
  metric: "revenue" | "profit"
  onCustomerSelect?: (customer: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const chartData = rows.map((r) => ({
    name: r.customer,
    value: metric === "revenue" ? r.revenue : r.profit,
    pct: r.conc_pct,
  }))
  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="bg-[#FEF3C7] px-3 py-2 text-sm font-semibold text-[#92400E]">
        {title}
        <span className="ml-2 text-xs font-normal opacity-75">· honors Division · Team · Customer · date filter</span>
      </div>
      <div className="grid grid-cols-1 gap-0 md:grid-cols-2">
        {loading ? (
          <div className="col-span-2 flex h-80 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : (
          <>
            {/* Bruno 2026-07-01 Requests 5 & 6: taller container + a smaller
                donut (with chart margins) so the outside % labels never clip. */}
            <div className="p-3">
              <ResponsiveContainer width="100%" height={360}>
                <PieChart margin={{ top: 20, right: 24, bottom: 20, left: 24 }}>
                  <Pie
                    data={chartData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={54}
                    outerRadius={86}
                    label={(entry: unknown) => {
                      const pct = (entry as { pct?: number } | null)?.pct
                      return pct !== undefined ? `${pct.toFixed(1)}%` : ""
                    }}
                  >
                    {chartData.map((_, i) => (
                      <Cell key={i} fill={DONUT_COLORS[i % DONUT_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(v) => fmtUsd(Number(v))} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="max-h-[400px] overflow-auto border-l border-[#F3F4F6]">
              <table className="w-full text-[12px] tabular-nums">
                <thead className="sticky top-0 bg-[#FEF3C7] text-[#92400E]">
                  <tr>
                    <th className="px-2 py-1.5 text-left">Customer</th>
                    <th className="px-1 py-1.5 text-right">Revenue</th>
                    <th className="px-1 py-1.5 text-right">Profit</th>
                    <th className="px-1 py-1.5 text-right">% Concen</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => {
                    const isOthers = r.customer === "Others"
                    return (
                      <tr key={r.customer + i} className="border-t border-[#F3F4F6]">
                        <td className="px-2 py-1.5">
                          {isOthers ? (
                            <button
                              type="button"
                              onClick={() => setExpanded((v) => !v)}
                              disabled={others.length === 0}
                              className="flex items-center gap-1 font-medium disabled:cursor-default disabled:opacity-60"
                              title={others.length ? "Show remaining customers" : "No remaining customers"}
                            >
                              {others.length > 0 &&
                                (expanded ? <Minus className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />)}
                              Others
                              {others.length > 0 && (
                                <span className="text-[#92400E]/60">({others.length})</span>
                              )}
                            </button>
                          ) : (
                            <CustomerLink
                              name={r.customer}
                              onSelect={onCustomerSelect}
                              className="block truncate max-w-[200px]"
                            />
                          )}
                        </td>
                        <td className="px-1 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                        <td className="px-1 py-1.5 text-right">{fmtUsd(r.profit)}</td>
                        <td className="px-1 py-1.5 text-right">{fmtPct(r.conc_pct)}</td>
                      </tr>
                    )
                  })}
                  {expanded &&
                    others.map((r, i) => (
                      <tr key={"o" + r.customer + i} className="border-t border-[#F3F4F6] bg-[#FFFBEB]">
                        <td className="px-2 py-1.5 pl-6">
                          <CustomerLink
                            name={r.customer}
                            onSelect={onCustomerSelect}
                            className="block truncate max-w-[190px] text-[#6B7280]"
                          />
                        </td>
                        <td className="px-1 py-1.5 text-right text-[#6B7280]">{fmtUsd(r.revenue)}</td>
                        <td className="px-1 py-1.5 text-right text-[#6B7280]">{fmtUsd(r.profit)}</td>
                        <td className="px-1 py-1.5 text-right text-[#6B7280]">{fmtPct(r.conc_pct)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
