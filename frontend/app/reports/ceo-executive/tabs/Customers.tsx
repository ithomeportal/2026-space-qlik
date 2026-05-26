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
  fmtCount,
  fmtPct,
  fmtUsd,
  useCeoCustomers,
  type CeoCustomerRow,
  type CeoFilters,
  type CeoTop5Row,
} from "@/lib/ceo-api"
import { CeoErrorBanner } from "../ErrorBanner"
import { marginCellClass } from "../margin-color"
import { CustomerLink } from "../customer-cell"

interface Props {
  filters: CeoFilters
  onCustomerSelect?: (customer: string) => void
}

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
          sortHint="sorted by highest profit"
          onCustomerSelect={onCustomerSelect}
        />
        <CustomerTable
          title="Worst Profit by Customer"
          tone="red"
          rows={d?.worst_by_customer ?? []}
          loading={isLoading}
          sortHint="sorted by worst profit"
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

function CustomerTable({
  title,
  tone,
  rows,
  loading,
  sortHint,
  onCustomerSelect,
}: {
  title: string
  tone: "green" | "red"
  rows: CeoCustomerRow[]
  loading?: boolean
  sortHint?: string
  onCustomerSelect?: (customer: string) => void
}) {
  const head = tone === "red" ? "bg-[#FEE2E2] text-[#991B1B]" : "bg-[#D1FAE5] text-[#065F46]"
  const tot = rows.reduce(
    (acc, r) => ({
      loads: acc.loads + (r.loads ?? 0),
      revenue: acc.revenue + (r.revenue ?? 0),
      profit: acc.profit + (r.profit ?? 0),
      conc_pct: acc.conc_pct + (r.conc_pct ?? 0),
    }),
    { loads: 0, revenue: 0, profit: 0, conc_pct: 0 },
  )
  const totMargin = tot.revenue > 0 ? (tot.profit / tot.revenue) * 100 : 0
  const totPerL = tot.loads > 0 ? tot.profit / tot.loads : 0

  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className={`${head} px-3 py-2 text-sm font-semibold`}>
        {title}
        {sortHint && <span className="ml-2 text-xs font-normal opacity-75">· {sortHint}</span>}
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[620px] overflow-auto">
          <table className="w-full text-[13px] tabular-nums">
            <thead className={`${head} sticky top-0`}>
              <tr>
                <th className="px-2 py-1.5 text-left">Customer</th>
                <th className="px-1 py-1.5 text-right">Loads</th>
                <th className="px-1 py-1.5 text-right">Revenue</th>
                <th className="px-1 py-1.5 text-right">Profit</th>
                <th className="px-1 py-1.5 text-right">Margin %</th>
                <th className="px-1 py-1.5 text-right">Conc %</th>
                <th className="px-1 py-1.5 text-right">AVG P / L</th>
              </tr>
            </thead>
            <tbody>
              <tr className="sticky top-[30px] bg-[#F3F4F6] font-semibold">
                <td className="px-2 py-1.5">Totals</td>
                <td className="px-1 py-1.5 text-right">{fmtCount(tot.loads)}</td>
                <td className="px-1 py-1.5 text-right">{fmtUsd(tot.revenue)}</td>
                <td className="px-1 py-1.5 text-right">{fmtUsd(tot.profit)}</td>
                <td className={`px-1 py-1.5 text-right ${marginCellClass(totMargin)}`}>{fmtPct(totMargin)}</td>
                <td className="px-1 py-1.5 text-right">{fmtPct(tot.conc_pct)}</td>
                <td className="px-1 py-1.5 text-right">{fmtUsd(totPerL)}</td>
              </tr>
              {rows.map((r) => (
                <tr key={r.customer} className="border-t border-[#F3F4F6]">
                  <td className="px-2 py-1.5">
                    <CustomerLink
                      name={r.customer}
                      onSelect={onCustomerSelect}
                      className="block truncate max-w-[260px]"
                    />
                  </td>
                  <td className="px-1 py-1.5 text-right">{fmtCount(r.loads)}</td>
                  <td className="px-1 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                  <td className="px-1 py-1.5 text-right">{fmtUsd(r.profit)}</td>
                  <td className={`px-1 py-1.5 text-right ${marginCellClass(r.margin_pct)}`}>{fmtPct(r.margin_pct)}</td>
                  <td className="px-1 py-1.5 text-right">{fmtPct(r.conc_pct)}</td>
                  <td className="px-1 py-1.5 text-right">{fmtUsd(r.avg_p_per_l)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
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
        <span className="ml-2 text-xs font-normal opacity-75">· honors Division · Team · Customer · full-year window</span>
      </div>
      <div className="grid grid-cols-1 gap-0 md:grid-cols-2">
        {loading ? (
          <div className="col-span-2 flex h-72 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : (
          <>
            <div className="p-3">
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={chartData}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={70}
                    outerRadius={110}
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
            <div className="max-h-[340px] overflow-auto border-l border-[#F3F4F6]">
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
