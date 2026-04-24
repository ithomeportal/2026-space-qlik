"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useXrayTrends,
  useXraySummaryTable,
  type XrayFilters,
  type XrayTrendPoint,
} from "@/lib/xray-api"
import { XrayErrorBanner } from "../ErrorBanner"

interface Props {
  filters: XrayFilters
}

type Grain = "day" | "week" | "month"

export function Trends({ filters }: Props) {
  const trioFilter = { team: filters.team, customer: filters.customer }
  const { data: trendsRes, isLoading: loadingTrends, error: trendsErr } = useXrayTrends(trioFilter)
  const { data: summRes, isLoading: loadingSumm, error: summErr } = useXraySummaryTable(trioFilter)
  const t = trendsRes?.data
  const summ = summRes?.data

  const [barGrain, setBarGrain] = useState<Exclude<Grain, "month">>("day")
  const [comboGrain, setComboGrain] = useState<Grain>("month")
  const [summaryGrain, setSummaryGrain] = useState<Exclude<Grain, "day">>("month")

  const barData = t?.[barGrain] ?? []
  const comboData = t?.[comboGrain] ?? []
  const summaryRows = summaryGrain === "month" ? summ?.months ?? [] : summ?.weeks ?? []

  const avgLoadsLM = avgFromBucket(barData, "loads", "prev")
  const avgLoadsTM = avgFromBucket(barData, "loads", "current")

  return (
    <div className="space-y-6">
      <XrayErrorBanner label="Trends" errors={[trendsErr, summErr]} />
      {/* Rev-vs-CC per load (line chart, monthly or weekly) */}
      <ChartCard
        title="Revenue × Load vs Carrier Cost × Load"
        subtitle={comboGrain === "month" ? "Last 15 months" : comboGrain === "week" ? "Last 12 weeks" : "Last 15 days"}
        grainToggle={
          <GrainToggle
            value={comboGrain}
            onChange={setComboGrain}
            options={[
              { k: "month", label: "Month" },
              { k: "week", label: "Week" },
            ]}
          />
        }
        loading={loadingTrends}
      >
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={comboData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => `$${v}`} />
            <Tooltip formatter={(v) => fmtUsd(Number(v))} labelFormatter={(v) => fmtBucket(String(v))} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Line type="monotone" dataKey="avg_r_per_l" name="AVG R/L" stroke="#1F4F99" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="avg_p_per_l" name="AVG P/L" stroke="#16A34A" strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="avg_cc_per_l" name="AVG CC/L" stroke="#9333EA" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </ChartCard>

      {/* Day/Week bar charts — Loads, Revenue, Profit, Margin */}
      <GrainToggle
        value={barGrain}
        onChange={setBarGrain}
        options={[
          { k: "day", label: "Day (last 15 days)" },
          { k: "week", label: "Week (last 12 weeks)" },
        ]}
        className="justify-end"
      />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="# Loads" loading={loadingTrends}>
          <BarChartWithAvg data={barData} dataKey="loads" color="#DC2626" avg={avgLoadsLM} avgTM={avgLoadsTM} format={fmtCount} />
        </ChartCard>
        <ChartCard title="$ Revenue" loading={loadingTrends}>
          <BarChartWithAvg data={barData} dataKey="revenue" color="#0EA5E9" format={fmtUsd} />
        </ChartCard>
        <ChartCard title="$ Profit" loading={loadingTrends}>
          <BarChartWithAvg data={barData} dataKey="profit" color="#CA8A04" format={fmtUsd} />
        </ChartCard>
        <ChartCard title="% Margin" loading={loadingTrends}>
          <BarChartWithAvg data={barData} dataKey="margin_pct" color="#9333EA" format={fmtPct} isPercent />
        </ChartCard>
      </div>

      {/* Combo: Loads vs Revenue + Profit vs Margin (by month / by week) */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="Loads vs Revenue" loading={loadingTrends}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={comboData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
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

        <ChartCard title="Profit vs Margin %" loading={loadingTrends}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={comboData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
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

      {/* Summary Table — by month or by week */}
      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="flex items-center justify-between border-b border-[#E5E7EB] bg-[#F3F4F6] px-3 py-2">
          <div className="text-sm font-semibold text-[#111827]">Summary</div>
          <GrainToggle
            value={summaryGrain}
            onChange={setSummaryGrain}
            options={[
              { k: "month", label: "By Month" },
              { k: "week", label: "By Week" },
            ]}
          />
        </div>
        {loadingSumm ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : (
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#F9FAFB] text-[#6B7280]">
                <tr>
                  <th className="px-3 py-1.5 text-left font-semibold">
                    {summaryGrain === "month" ? "Month" : "Week"}
                  </th>
                  <th className="px-3 py-1.5 text-right font-semibold"># Lanes</th>
                  <th className="px-3 py-1.5 text-right font-semibold"># Loads</th>
                  <th className="px-3 py-1.5 text-right font-semibold">$ Revenue</th>
                  <th className="px-3 py-1.5 text-right font-semibold">$ Profit</th>
                  <th className="px-3 py-1.5 text-right font-semibold">% Margin</th>
                  <th className="px-3 py-1.5 text-right font-semibold">OTP %</th>
                  <th className="px-3 py-1.5 text-right font-semibold">OTD %</th>
                </tr>
              </thead>
              <tbody>
                {summaryRows.map((r) => (
                  <tr key={r.bucket} className="border-t border-[#F3F4F6] hover:bg-[#F9FAFB]">
                    <td className="px-3 py-1.5">{fmtBucket(r.bucket)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(r.lanes)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(r.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.profit)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(r.margin_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(r.otp_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(r.otd_pct)}</td>
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

// -- helpers --

function ChartCard({
  title,
  subtitle,
  grainToggle,
  children,
  loading,
}: {
  title: string
  subtitle?: string
  grainToggle?: React.ReactNode
  children: React.ReactNode
  loading?: boolean
}) {
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-[#111827]">{title}</div>
          {subtitle && <div className="text-[10px] text-[#6B7280]">{subtitle}</div>}
        </div>
        {grainToggle}
      </div>
      {loading ? (
        <div className="flex h-48 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        children
      )}
    </div>
  )
}

function GrainToggle<T extends string>({
  value,
  onChange,
  options,
  className = "",
}: {
  value: T
  onChange: (v: T) => void
  options: { k: T; label: string }[]
  className?: string
}) {
  return (
    <div className={`flex ${className}`}>
      <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-[11px]">
        {options.map((opt) => (
          <button
            key={opt.k}
            onClick={() => onChange(opt.k)}
            className={`px-3 py-1 ${
              value === opt.k
                ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                : "text-[#6B7280] hover:text-[#111827]"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function BarChartWithAvg({
  data,
  dataKey,
  color,
  avg,
  avgTM,
  format,
  isPercent,
}: {
  data: XrayTrendPoint[]
  dataKey: keyof XrayTrendPoint
  color: string
  avg?: number
  avgTM?: number
  format: (v: number | null | undefined) => string
  isPercent?: boolean
}) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
        <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
        <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => (isPercent ? `${v}%` : String(v))} />
        <Tooltip formatter={(v) => format(Number(v))} labelFormatter={(v) => fmtBucket(String(v))} />
        <Bar dataKey={dataKey as string} fill={color} />
        {avg !== undefined && (
          <ReferenceLine y={avg} stroke="#9CA3AF" strokeDasharray="4 4" label={{ value: "Avg LM", fontSize: 9, fill: "#6B7280" }} />
        )}
        {avgTM !== undefined && (
          <ReferenceLine y={avgTM} stroke="#1F4F99" strokeDasharray="4 4" label={{ value: "Avg TM", fontSize: 9, fill: "#1F4F99" }} />
        )}
      </BarChart>
    </ResponsiveContainer>
  )
}

function avgFromBucket(
  data: XrayTrendPoint[],
  key: keyof XrayTrendPoint,
  which: "current" | "prev",
): number | undefined {
  if (!data.length) return undefined
  const today = new Date()
  const cur = today.getMonth()
  const year = today.getFullYear()
  const filtered = data.filter((d) => {
    const b = new Date(d.bucket)
    if (which === "current") return b.getFullYear() === year && b.getMonth() === cur
    // prev month
    const prevYear = cur === 0 ? year - 1 : year
    const prevMonth = cur === 0 ? 11 : cur - 1
    return b.getFullYear() === prevYear && b.getMonth() === prevMonth
  })
  if (!filtered.length) return undefined
  const sum = filtered.reduce((acc, d) => acc + Number(d[key] || 0), 0)
  return sum / filtered.length
}

function fmtBucket(bucket: string) {
  const d = new Date(bucket)
  if (Number.isNaN(d.getTime())) return bucket
  return `${d.toLocaleString("en-US", { month: "short" })} ${String(d.getDate()).padStart(2, "0")}`
}
