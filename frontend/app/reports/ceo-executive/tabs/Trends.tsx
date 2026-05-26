"use client"

import { useEffect, useRef } from "react"
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
import { fmtDay, fmtMonth, fmtUsd, useCeoTrends, type CeoFilters } from "@/lib/ceo-api"
import { CeoErrorBanner } from "../ErrorBanner"

// Bruno R7 (2026-05-26): per-day colors for the two "by Day" charts.
const C_LOADS = "rgb(191, 0, 0)"
const C_PROFIT = "rgb(235, 198, 0)"
const C_CUSTOMER = "rgb(33, 191, 106)"
const C_MARGIN = "rgb(0, 101, 128)"

// ~30 days fit a typical panel width; 80 days overflow into horizontal scroll.
const PX_PER_DAY = 44

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

// Bruno R7 (2026-05-26): show genuine per-day points (no weekly aggregation),
// default to the most-recent ~30 days, and scroll back through all 80.
function toDailyPoints(
  daily: { bucket: string; customers: number; margin_pct: number; profit: number; loads: number }[],
) {
  return daily.map((d) => ({
    label: fmtDay(d.bucket),
    bucket: d.bucket,
    customers: d.customers,
    margin_pct: d.margin_pct,
    profit: d.profit,
    loads: d.loads,
  }))
}

interface TrendsProps {
  filters: CeoFilters
}

export function Trends({ filters }: TrendsProps) {
  const { data, isLoading, error } = useCeoTrends({
    division: filters.division,
    team: filters.team,
    customer: filters.customer,
  })
  const d = data?.data

  const monthly = (d?.monthly ?? []).map((r) => ({
    ...r,
    label: fmtMonth(r.bucket),
  }))
  const dailyPoints = toDailyPoints(d?.daily ?? [])

  return (
    <div className="space-y-6">
      <CeoErrorBanner label="Trends" errors={[error]} />

      <div className="rounded-md border border-[#E5E7EB] bg-white p-3 text-xs text-[#6B7280]">
        Trends panels are <strong>date-immutable</strong> — they ignore Range and always show
        the fixed windows below. Division, Team and Customer filters are honored.
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
          subtitle="one point per day · showing recent days · scroll ← for up to 80 days"
          loading={isLoading}
        >
          <DailyScrollChart count={dailyPoints.length}>
            <ComposedChart data={dailyPoints} margin={{ top: 18, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 9 }} interval={0} />
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
                stroke={C_PROFIT}
                name="Profit"
                dot={{ r: 2, fill: C_PROFIT }}
              >
                <LabelList dataKey="profit" position="top" fontSize={8} fill="#92400E" formatter={fmtK} />
              </Line>
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="loads"
                stroke={C_LOADS}
                name="Loads"
                dot={{ r: 2, fill: C_LOADS }}
              >
                <LabelList dataKey="loads" position="bottom" fontSize={8} fill="#991B1B" formatter={fmtInt} />
              </Line>
            </ComposedChart>
          </DailyScrollChart>
        </Panel>

        <Panel
          title="Customer Count & Margin % by Day — Last 80 Days"
          subtitle="one point per day · showing recent days · scroll ← for up to 80 days"
          loading={isLoading}
        >
          <DailyScrollChart count={dailyPoints.length}>
            <ComposedChart data={dailyPoints} margin={{ top: 18, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 9 }} interval={0} />
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
                stroke={C_CUSTOMER}
                name="# Customer"
                dot={{ r: 2, fill: C_CUSTOMER }}
              >
                <LabelList dataKey="customers" position="top" fontSize={8} fill="#065F46" formatter={fmtInt} />
              </Line>
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="margin_pct"
                stroke={C_MARGIN}
                name="% Margin"
                dot={{ r: 2, fill: C_MARGIN }}
              >
                <LabelList dataKey="margin_pct" position="bottom" fontSize={8} fill="#0E7490" formatter={fmtPct1} />
              </Line>
            </ComposedChart>
          </DailyScrollChart>
        </Panel>
      </section>
    </div>
  )
}

// Horizontally scrollable wrapper for the per-day charts. Sizes the inner
// canvas to PX_PER_DAY × point-count so ~30 days fill a typical panel and the
// rest scroll; auto-scrolls to the right (most recent) on mount / data change.
function DailyScrollChart({ count, children }: { count: number; children: React.ReactElement }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.scrollLeft = ref.current.scrollWidth
  }, [count])
  const innerWidth = Math.max(count * PX_PER_DAY, 600)
  return (
    <div ref={ref} className="overflow-x-auto">
      <div style={{ width: innerWidth, minWidth: "100%" }}>
        <ResponsiveContainer width="100%" height={300}>
          {children}
        </ResponsiveContainer>
      </div>
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
