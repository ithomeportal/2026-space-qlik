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
  useXrayAllOrders,
  useXrayContractSpot,
  useXrayLaneAnalysis,
  type XrayFilters,
} from "@/lib/xray-api"

interface Props {
  filters: XrayFilters
}

const fmtBucket = (s: string) => {
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return `${d.toLocaleString("en-US", { month: "short" })} ${String(d.getDate()).padStart(2, "0")}`
}

export function ContractSpot({ filters }: Props) {
  const trioFilter = { team: filters.team, customer: filters.customer }
  const { data: csRes, isLoading: loadingCs } = useXrayContractSpot(trioFilter)
  const { data: ordersRes, isLoading: loadingOrd } = useXrayAllOrders(filters)
  const { data: laRes, isLoading: loadingLa } = useXrayLaneAnalysis(filters)
  const cs = csRes?.data
  const orders = ordersRes?.data ?? []
  const lanes = laRes?.data ?? []

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {/* Contract */}
        <ChartCard title="% Contract — Revenue vs Loads" subtitle="Last 9 weeks" loading={loadingCs}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={cs?.contract ?? []} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
              <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} />
              <Tooltip labelFormatter={(v) => fmtBucket(String(v))} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey="revenue" name="$ Revenue" fill="#38BDF8" />
              <Line yAxisId="right" type="monotone" dataKey="loads" name="# Loads" stroke="#DC2626" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="% Contract — Profit vs Margin" subtitle="Last 9 weeks" loading={loadingCs}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={cs?.contract ?? []} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
              <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
              <Tooltip labelFormatter={(v) => fmtBucket(String(v))} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey="profit" name="$ Profit" fill="#CA8A04" />
              <Line yAxisId="right" type="monotone" dataKey="margin_pct" name="% Margin" stroke="#9333EA" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="% Spot — Revenue vs Loads" subtitle="Last 9 weeks" loading={loadingCs}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={cs?.spot ?? []} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
              <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} />
              <Tooltip labelFormatter={(v) => fmtBucket(String(v))} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey="revenue" name="$ Revenue" fill="#38BDF8" />
              <Line yAxisId="right" type="monotone" dataKey="loads" name="# Loads" stroke="#DC2626" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="% Spot — Profit vs Margin" subtitle="Last 9 weeks" loading={loadingCs}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={cs?.spot ?? []} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
              <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
              <Tooltip labelFormatter={(v) => fmtBucket(String(v))} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey="profit" name="$ Profit" fill="#CA8A04" />
              <Line yAxisId="right" type="monotone" dataKey="margin_pct" name="% Margin" stroke="#9333EA" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      {/* All orders */}
      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#E5E7EB] bg-[#FEF3C7] px-3 py-2 text-sm font-semibold text-[#111827]">
          All Orders
          <span className="ml-2 text-xs text-[#6B7280]">(first 500 by most recent departure)</span>
        </div>
        {loadingOrd ? (
          <Spin />
        ) : (
          <div className="max-h-[500px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#FEF3C7] text-[#6B7280]">
                <tr>
                  <Th>Team</Th>
                  <Th>Order</Th>
                  <Th>Customer</Th>
                  <Th>Carrier</Th>
                  <Th>Origin</Th>
                  <Th>Destination</Th>
                  <Th>Departure</Th>
                  <Th className="text-right">$ Revenue</Th>
                  <Th className="text-right">$ Profit</Th>
                  <Th className="text-right">Margin %</Th>
                  <Th className="text-right">Diff 15%</Th>
                  <Th className="text-right">Diff 18%</Th>
                  <Th className="text-right">Diff 20%</Th>
                </tr>
              </thead>
              <tbody>
                {orders.map((r) => (
                  <tr key={r.id} className="border-t border-[#F3F4F6] hover:bg-[#FEFCE8]">
                    <td className="px-3 py-1.5">{r.team}</td>
                    <td className="px-3 py-1.5">{r.id}</td>
                    <td className="px-3 py-1.5">{r.customer}</td>
                    <td className="px-3 py-1.5">{r.carrier}</td>
                    <td className="px-3 py-1.5">{r.origin}</td>
                    <td className="px-3 py-1.5">{r.destination}</td>
                    <td className="px-3 py-1.5">{r.departure ? r.departure.substring(0, 16).replace("T", " ") : "—"}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                    <td className={`px-3 py-1.5 text-right ${r.profit < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtUsd(r.profit)}
                    </td>
                    <td className={`px-3 py-1.5 text-right ${r.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtPct(r.margin_pct)}
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_15)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_18)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_20)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Lane production analysis */}
      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#E5E7EB] bg-[#EDE9FE] px-3 py-2 text-sm font-semibold text-[#111827]">
          Lane Production Analysis
          <span className="ml-2 text-xs text-[#6B7280]">sorted by profit concentration</span>
        </div>
        {loadingLa ? (
          <Spin />
        ) : (
          <div className="max-h-[500px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#EDE9FE] text-[#6B7280]">
                <tr>
                  <Th>Customer</Th>
                  <Th>Origin</Th>
                  <Th>Destination</Th>
                  <Th className="text-right">Conc %</Th>
                  <Th className="text-right"># Loads</Th>
                  <Th className="text-right">$ Revenue</Th>
                  <Th className="text-right">$ Profit</Th>
                  <Th className="text-right">Margin %</Th>
                  <Th className="text-right">AVG R/L</Th>
                  <Th className="text-right">AVG P/L</Th>
                  <Th className="text-right">Diff 15%</Th>
                  <Th className="text-right">Diff 18%</Th>
                  <Th className="text-right">Diff 20%</Th>
                </tr>
              </thead>
              <tbody>
                {lanes.map((r, i) => (
                  <tr key={i} className="border-t border-[#F3F4F6] hover:bg-[#FAF5FF]">
                    <td className="px-3 py-1.5">{r.customer}</td>
                    <td className="px-3 py-1.5">{r.origin}</td>
                    <td className="px-3 py-1.5">{r.destination}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(r.conc_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(r.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                    <td className={`px-3 py-1.5 text-right ${r.profit < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtUsd(r.profit)}
                    </td>
                    <td className={`px-3 py-1.5 text-right ${r.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtPct(r.margin_pct)}
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.avg_r_per_l)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.avg_p_per_l)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_15)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_18)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_20)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
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
