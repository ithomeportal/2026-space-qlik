"use client"

import { Loader2 } from "lucide-react"
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useXrayRisk,
  type XrayFilters,
} from "@/lib/xray-api"
import { XrayErrorBanner } from "../ErrorBanner"

interface Props {
  filters: XrayFilters
}

export function Risk({ filters }: Props) {
  const { data, isLoading, error } = useXrayRisk(filters)
  const r = data?.data

  const fmtBucket = (s: string) => {
    const d = new Date(s)
    if (Number.isNaN(d.getTime())) return s
    return `${d.toLocaleString("en-US", { month: "short" })} ${String(d.getDate()).padStart(2, "0")}`
  }

  return (
    <div className="space-y-6">
      <XrayErrorBanner label="Risk" errors={[error]} />
      {/* Worst margins by lane */}
      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#FCA5A5] bg-[#FEE2E2] px-3 py-2 text-sm font-semibold text-[#991B1B]">
          Worst Margins by Lane
        </div>
        {isLoading ? (
          <Spin />
        ) : (
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#FEE2E2] text-[#6B7280]">
                <tr>
                  <Th>Customer</Th>
                  <Th>Origin</Th>
                  <Th>Destination</Th>
                  <Th className="text-right"># Loads</Th>
                  <Th className="text-right">$ Revenue</Th>
                  <Th className="text-right">$ Profit</Th>
                  <Th className="text-right">Margin %</Th>
                  <Th className="text-right">Diff to 15%</Th>
                  <Th className="text-right">Diff to 18%</Th>
                  <Th className="text-right">Diff to 20%</Th>
                </tr>
              </thead>
              <tbody>
                {(r?.worst_lanes ?? []).map((row, i) => (
                  <tr key={i} className="border-t border-[#FECACA] hover:bg-[#FEF2F2]">
                    <td className="px-3 py-1.5">{row.customer}</td>
                    <td className="px-3 py-1.5">{row.origin}</td>
                    <td className="px-3 py-1.5">{row.destination}</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(row.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.revenue)}</td>
                    <td className="px-3 py-1.5 text-right text-[#DC2626]">{fmtUsd(row.profit)}</td>
                    <td className="px-3 py-1.5 text-right text-[#DC2626]">{fmtPct(row.margin_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.diff_15)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.diff_18)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.diff_20)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Negative loads by order */}
      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#FCA5A5] bg-[#FEE2E2] px-3 py-2 text-sm font-semibold text-[#991B1B]">
          Negative Loads — by Order
        </div>
        {isLoading ? (
          <Spin />
        ) : (
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#FEE2E2] text-[#6B7280]">
                <tr>
                  <Th>Order</Th>
                  <Th>Customer</Th>
                  <Th>Carrier</Th>
                  <Th>Origin</Th>
                  <Th>Destination</Th>
                  <Th className="text-right">$ Revenue</Th>
                  <Th className="text-right">$ Profit</Th>
                  <Th className="text-right">Margin %</Th>
                  <Th className="text-right">Conc %</Th>
                </tr>
              </thead>
              <tbody>
                {(r?.neg_orders ?? []).map((row) => (
                  <tr key={row.id} className="border-t border-[#FECACA] hover:bg-[#FEF2F2]">
                    <td className="px-3 py-1.5">{row.id}</td>
                    <td className="px-3 py-1.5">{row.customer}</td>
                    <td className="px-3 py-1.5">{row.carrier}</td>
                    <td className="px-3 py-1.5">{row.origin}</td>
                    <td className="px-3 py-1.5">{row.destination}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.revenue)}</td>
                    <td className="px-3 py-1.5 text-right text-[#DC2626]">{fmtUsd(row.profit)}</td>
                    <td className="px-3 py-1.5 text-right text-[#DC2626]">{fmtPct(row.margin_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(row.conc_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Negative loads by customer roll-up */}
      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#FCA5A5] bg-[#FEE2E2] px-3 py-2 text-sm font-semibold text-[#991B1B]">
          Negative Loads — by Customer
        </div>
        {isLoading ? (
          <Spin />
        ) : (
          <div className="max-h-[400px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#FEE2E2] text-[#6B7280]">
                <tr>
                  <Th>Customer</Th>
                  <Th className="text-right"># Loads</Th>
                  <Th className="text-right">$ Revenue</Th>
                  <Th className="text-right">$ Profit</Th>
                  <Th className="text-right">Conc %</Th>
                </tr>
              </thead>
              <tbody>
                {(r?.neg_customers ?? []).map((row, i) => (
                  <tr key={i} className="border-t border-[#FECACA] hover:bg-[#FEF2F2]">
                    <td className="px-3 py-1.5">{row.customer}</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(row.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(row.revenue)}</td>
                    <td className="px-3 py-1.5 text-right text-[#DC2626]">{fmtUsd(row.profit)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(row.conc_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Losses over time — combo chart */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Losses by Month" subtitle="Last 8 months" loading={isLoading}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={[...(r?.losses_month ?? [])].reverse()} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
              <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} />
              <Tooltip labelFormatter={(v) => fmtBucket(String(v))} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey="profit" name="$ Profit (negative)" fill="#DC2626" />
              <Line yAxisId="right" type="monotone" dataKey="loads" name="# Loads" stroke="#1F4F99" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>
        <ChartCard title="Losses by Week" subtitle="Last 8 weeks" loading={isLoading}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={[...(r?.losses_week ?? [])].reverse()} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
              <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} />
              <Tooltip labelFormatter={(v) => fmtBucket(String(v))} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey="profit" name="$ Profit (negative)" fill="#DC2626" />
              <Line yAxisId="right" type="monotone" dataKey="loads" name="# Loads" stroke="#1F4F99" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>
    </div>
  )
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <th className={`px-3 py-1.5 text-left font-semibold ${className}`}>{children}</th>
}

function Spin() {
  return (
    <div className="flex h-40 items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
    </div>
  )
}

function ChartCard({
  title,
  subtitle,
  children,
  loading,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
  loading?: boolean
}) {
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <div className="mb-2">
        <div className="text-sm font-semibold text-[#111827]">{title}</div>
        {subtitle && <div className="text-[10px] text-[#6B7280]">{subtitle}</div>}
      </div>
      {loading ? <Spin /> : children}
    </div>
  )
}

