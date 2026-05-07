"use client"

import { Loader2 } from "lucide-react"
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { fmtDay, fmtMonth, fmtUsd, useCeoTrends } from "@/lib/ceo-api"
import { CeoErrorBanner } from "../ErrorBanner"

// Compact label formatters used by Recharts <LabelList />. Recharts v3 typed
// the formatter signature loosely (string | number | undefined), so accept any.
const fmtK = (v: unknown) => {
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return ""
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 1_000) return `${Math.round(n / 1000)}k`
  return `${Math.round(n)}`
}
const fmtPct1 = (v: unknown) => {
  const n = Number(v)
  if (!Number.isFinite(n)) return ""
  return `${n.toFixed(1)}%`
}
const fmtInt = (v: unknown) => {
  const n = Number(v)
  if (!Number.isFinite(n) || n === 0) return ""
  return String(Math.round(n))
}

// Aggregate daily points into ISO weeks (Mon-Sun). Each bucket is plotted
// at the week-ending Sunday on a continuous daily x-axis (all 80 days emitted),
// so the weekly markers sit alongside their natural day position. Days that
// don't fall on a Sunday have null values so the line only draws weekly points.
function bucketDailyToWeekly(daily: { bucket: string; customers: number; margin_pct: number; profit: number; loads: number }[]) {
  if (daily.length === 0) return [] as Array<{ label: string; bucket: string; customers: number | null; margin_pct: number | null; profit: number | null; loads: number | null; isSunday: boolean }>

  // Group by ISO week ending Sunday (week's last day).
  const weekMap = new Map<string, {
    sundayIso: string
    customersSum: number
    daysWithCustomers: number
    revenueWeighted: number
    weightDenom: number
    profit: number
    loads: number
  }>()

  for (const d of daily) {
    const dt = new Date(d.bucket + "T00:00:00")
    const dow = dt.getDay() // 0=Sun, 1=Mon, ... 6=Sat
    // Week-ending Sunday = next Sunday (or today if Sun).
    const daysToSunday = dow === 0 ? 0 : 7 - dow
    const sunday = new Date(dt)
    sunday.setDate(sunday.getDate() + daysToSunday)
    const sundayIso = sunday.toISOString().slice(0, 10)

    const w = weekMap.get(sundayIso) ?? {
      sundayIso,
      customersSum: 0,
      daysWithCustomers: 0,
      revenueWeighted: 0,
      weightDenom: 0,
      profit: 0,
      loads: 0,
    }
    if (d.customers > 0) {
      w.customersSum += d.customers
      w.daysWithCustomers += 1
    }
    // Approximate revenue from profit/margin so we can re-derive a weekly
    // margin_pct as profit/revenue. If margin is 0, fall back to per-day avg.
    if (d.margin_pct !== 0 && d.profit !== 0) {
      const rev = d.profit / (d.margin_pct / 100)
      w.revenueWeighted += d.profit
      w.weightDenom += rev
    }
    w.profit += d.profit
    w.loads += d.loads
    weekMap.set(sundayIso, w)
  }

  // Daily x-axis: emit one row per day with values only on the week-ending Sunday.
  return daily.map((d) => {
    const dt = new Date(d.bucket + "T00:00:00")
    const isSunday = dt.getDay() === 0
    if (!isSunday) {
      return {
        label: fmtDay(d.bucket),
        bucket: d.bucket,
        customers: null,
        margin_pct: null,
        profit: null,
        loads: null,
        isSunday: false,
      }
    }
    const w = weekMap.get(d.bucket)
    if (!w) {
      return {
        label: fmtDay(d.bucket),
        bucket: d.bucket,
        customers: null,
        margin_pct: null,
        profit: null,
        loads: null,
        isSunday: true,
      }
    }
    const avgCust = w.daysWithCustomers > 0 ? Math.round(w.customersSum / w.daysWithCustomers) : 0
    const margin = w.weightDenom > 0 ? (w.revenueWeighted / w.weightDenom) * 100 : 0
    return {
      label: fmtDay(d.bucket),
      bucket: d.bucket,
      customers: avgCust,
      margin_pct: margin,
      profit: w.profit,
      loads: w.loads,
      isSunday: true,
    }
  })
}

export function Trends() {
  const { data, isLoading, error } = useCeoTrends()
  const d = data?.data

  const monthly = (d?.monthly ?? []).map((r) => ({
    ...r,
    label: fmtMonth(r.bucket),
  }))
  const dailyWeekly = bucketDailyToWeekly(d?.daily ?? [])

  // Sparser x-axis tick stride for the 80-day chart so labels don't overlap.
  const dailyTickStride = Math.max(0, Math.floor(dailyWeekly.length / 16))

  return (
    <div className="space-y-6">
      <CeoErrorBanner label="Trends" errors={[error]} />

      <div className="rounded-md border border-[#E5E7EB] bg-white p-3 text-xs text-[#6B7280]">
        All Trends panels are <strong>date-immutable</strong> — they ignore the Range / Team /
        Customer filters and always show the fixed windows below.
      </div>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Customer Count & Margin % — Last 15 Months" loading={isLoading}>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={monthly} margin={{ top: 18, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
              <YAxis
                yAxisId="right"
                orientation="right"
                tickFormatter={(v) => `${v.toFixed(0)}%`}
                tick={{ fontSize: 11 }}
                domain={[0, 50]}
              />
              <Tooltip formatter={(v, name) =>
                name === "% Margin" ? `${Number(v).toFixed(2)}%` : String(v)
              } />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar yAxisId="left" dataKey="customers" fill="#10B981" name="# Customer" barSize={28}>
                <LabelList dataKey="customers" position="top" fontSize={10} fill="#065F46" formatter={fmtInt} />
              </Bar>
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="margin_pct"
                stroke="#2563EB"
                name="% Margin"
                dot={{ r: 3 }}
              >
                <LabelList dataKey="margin_pct" position="top" fontSize={10} fill="#1E40AF" formatter={fmtPct1} />
              </Line>
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Profit / Loads by Month — Last 15 Months" loading={isLoading}>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={monthly} margin={{ top: 18, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis yAxisId="left" tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v, name) =>
                name === "Profit" ? fmtUsd(Number(v)) : String(v)
              } />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar yAxisId="left" dataKey="profit" fill="#D97706" name="Profit" barSize={28}>
                <LabelList dataKey="profit" position="top" fontSize={10} fill="#92400E" formatter={fmtK} />
              </Bar>
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="loads"
                stroke="#DC2626"
                name="Loads"
                dot={{ r: 3 }}
              >
                <LabelList dataKey="loads" position="top" fontSize={10} fill="#991B1B" formatter={fmtInt} />
              </Line>
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>
      </section>

      <section className="grid grid-cols-1 gap-4">
        <Panel
          title="Profit / Loads by Day — Last 80 Days"
          subtitle="Aggregated weekly · plotted on the day-axis at each week-ending Sunday"
          loading={isLoading}
        >
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={dailyWeekly} margin={{ top: 16, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={dailyTickStride} />
              <YAxis yAxisId="left" tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v, name) =>
                name === "Profit" ? fmtUsd(Number(v)) : String(v)
              } />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="profit"
                stroke="#D97706"
                name="Profit"
                connectNulls
                dot={{ r: 3, fill: "#D97706" }}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="loads"
                stroke="#DC2626"
                name="Loads"
                connectNulls
                dot={{ r: 3, fill: "#DC2626" }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>

        <Panel
          title="Customer Count & Margin % by Day — Last 80 Days"
          subtitle="Aggregated weekly · plotted on the day-axis at each week-ending Sunday"
          loading={isLoading}
        >
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={dailyWeekly} margin={{ top: 16, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={dailyTickStride} />
              <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
              <YAxis
                yAxisId="right"
                orientation="right"
                tickFormatter={(v) => `${v.toFixed(0)}%`}
                tick={{ fontSize: 11 }}
              />
              <Tooltip formatter={(v, name) =>
                name === "% Margin" ? `${Number(v).toFixed(2)}%` : String(v)
              } />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line
                yAxisId="left"
                type="monotone"
                dataKey="customers"
                stroke="#10B981"
                name="# Customer"
                connectNulls
                dot={{ r: 3, fill: "#10B981" }}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="margin_pct"
                stroke="#2563EB"
                name="% Margin"
                connectNulls
                dot={{ r: 3, fill: "#2563EB" }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>
      </section>
    </div>
  )
}

function Panel({
  title,
  subtitle,
  loading,
  children,
}: {
  title: string
  subtitle?: string
  loading?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="bg-[#F9FAFB] px-3 py-2 text-sm font-semibold text-[#111827]">
        {title}
        {subtitle && <span className="ml-2 text-xs font-normal text-[#6B7280]">· {subtitle}</span>}
      </div>
      <div className="p-3">
        {loading ? (
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  )
}
