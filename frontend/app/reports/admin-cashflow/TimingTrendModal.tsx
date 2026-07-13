"use client"

import { useEffect, useMemo, useState } from "react"
import { Loader2 } from "lucide-react"
import {
  Bar,
  Brush,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  useAdminCashflowTimingMonthly,
  type AdminCashflowFilters,
  type TimingGrain,
  type TimingMetricKey,
} from "@/lib/admin-cashflow-api"
import { UnbilledExpandModal } from "./UnbilledShared"
import { fmtCount } from "./format"

// Bruno Aging "+" pop-up (PDF 2026-06-22): per-KPI monthly combo chart.
// Bar = total orders in the metric's universe, green line = within threshold,
// red line = over threshold. One pop-up per discipline KPI.

const META: Record<
  TimingMetricKey,
  { title: string; within: string; over: string }
> = {
  del: { title: "Delivery vs Bill ≤2d", within: "≤2d", over: ">2d" },
  bol: { title: "BOL vs Bill ≤1d", within: "≤1d", over: ">1d" },
  carrinv: { title: "Carrier Inv vs Bill ≤1d", within: "≤1d", over: ">1d" },
}

const COLORS = { total: "#7DD3FC", within: "#16A34A", over: "#DC2626" }

// "2025-11-01" → "Nov 25"
const MONTHS_ABBR = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]
function fmtMonth(iso: string): string {
  const [y, m] = iso.split("-")
  const mi = Number(m) - 1
  if (mi < 0 || mi > 11) return iso
  return `${MONTHS_ABBR[mi]} ${y.slice(2)}`
}

// Week grain: ISO-Monday bucket start "2026-06-15" → "Jun 15"
function fmtWeek(iso: string): string {
  const [, m, d] = iso.split("-")
  const mi = Number(m) - 1
  if (mi < 0 || mi > 11 || !d) return iso
  return `${MONTHS_ABBR[mi]} ${Number(d)}`
}

// Default the brush to the most recent 8 buckets (matches the reference image;
// Bruno Aging R 2026-07-13 also wants the Week view defaulting to 8 weeks).
const DEFAULT_VISIBLE = 8

export function TimingTrendModal({
  metric,
  filters,
  onClose,
}: {
  metric: TimingMetricKey
  filters: AdminCashflowFilters
  onClose: () => void
}) {
  const meta = META[metric]
  // Bruno Aging R (PDF 2026-07-13): Month (default) / Week grain toggle.
  const [grain, setGrain] = useState<TimingGrain>("month")
  const { data: res, isLoading, error } = useAdminCashflowTimingMonthly(
    filters,
    true,
    grain,
  )
  const payload = res?.data

  const chartData = useMemo(() => {
    if (!payload) return []
    const s = payload[metric]
    const fmt = grain === "week" ? fmtWeek : fmtMonth
    return payload.months.map((mon, i) => ({
      label: fmt(mon),
      total: s.total[i] ?? 0,
      within: s.within[i] ?? 0,
      over: s.over[i] ?? 0,
    }))
  }, [payload, metric, grain])

  const [brush, setBrush] = useState<{ start: number; end: number }>({
    start: 0,
    end: 0,
  })
  useEffect(() => {
    if (!chartData.length) return
    const end = chartData.length - 1
    const start = Math.max(0, end - DEFAULT_VISIBLE + 1)
    setBrush({ start, end })
  }, [chartData.length])

  return (
    <UnbilledExpandModal
      title={meta.title}
      subtitle={
        grain === "week"
          ? "Weekly orders — bar = total, green = on-time, red = late · trailing 13 weeks"
          : "Monthly orders — bar = total, green = on-time, red = late · trailing 13 months"
      }
      onClose={onClose}
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3 text-[11px] text-[#374151]">
        <div className="flex flex-wrap items-center gap-3">
          <LegendItem color={COLORS.total} label="Total orders" square />
          <LegendItem color={COLORS.within} label={`On time (${meta.within})`} />
          <LegendItem color={COLORS.over} label={`Late (${meta.over})`} />
        </div>
        {/* Bruno Aging R (PDF 2026-07-13): Month / Week grain toggle. */}
        <div className="inline-flex overflow-hidden rounded-md border border-[#E5E7EB]">
          {(["month", "week"] as TimingGrain[]).map((g) => (
            <button
              key={g}
              onClick={() => setGrain(g)}
              className={`px-2.5 py-1 text-[11px] capitalize ${
                grain === g
                  ? "bg-[#1B3A5C] text-white"
                  : "bg-white text-[#6B7280] hover:bg-[#F3F4F6]"
              }`}
            >
              {g}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex h-[420px] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : error ? (
        <div className="flex h-[420px] items-center justify-center text-sm text-[#DC2626]">
          Failed to load chart
        </div>
      ) : !chartData.length ? (
        <div className="flex h-[420px] items-center justify-center text-sm text-[#6B7280]">
          No data in range
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={420}>
          <ComposedChart
            data={chartData}
            margin={{ top: 20, right: 24, bottom: 0, left: 8 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} />
            <YAxis
              tick={{ fontSize: 10 }}
              allowDecimals={false}
              tickFormatter={(v) => fmtCount(Number(v))}
            />
            <Tooltip
              content={({ active, payload: pl }) => {
                if (!active || !pl || !pl.length) return null
                const row = pl[0].payload as {
                  label?: string
                  total: number
                  within: number
                  over: number
                }
                const items = [
                  { label: "Total orders", color: COLORS.total, value: row.total },
                  { label: `On time (${meta.within})`, color: COLORS.within, value: row.within },
                  { label: `Late (${meta.over})`, color: COLORS.over, value: row.over },
                ]
                return (
                  <div className="rounded-md border border-[#E5E7EB] bg-white px-3 py-2 text-xs shadow-md">
                    <div className="mb-1 font-semibold text-[#111827]">
                      {row.label}
                    </div>
                    {items.map((i) => (
                      <div
                        key={i.label}
                        className="flex items-center justify-between gap-4"
                      >
                        <span className="flex items-center gap-1.5">
                          <span
                            className="inline-block h-2 w-2 rounded-full"
                            style={{ background: i.color }}
                          />
                          {i.label}
                        </span>
                        <span className="font-medium tabular-nums text-[#111827]">
                          {fmtCount(i.value)}
                        </span>
                      </div>
                    ))}
                  </div>
                )
              }}
            />
            <Bar dataKey="total" name="Total orders" fill={COLORS.total}>
              <LabelList
                dataKey="total"
                position="top"
                fontSize={9}
                fill="#475569"
                formatter={(v) => (Number(v) > 0 ? fmtCount(Number(v)) : "")}
              />
            </Bar>
            <Line
              type="monotone"
              dataKey="within"
              name="On time"
              stroke={COLORS.within}
              strokeWidth={2}
              dot={{ r: 3 }}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="over"
              name="Late"
              stroke={COLORS.over}
              strokeWidth={2}
              dot={{ r: 3 }}
              connectNulls
            />
            <Brush
              dataKey="label"
              height={20}
              stroke="#94A3B8"
              travellerWidth={8}
              startIndex={brush.start}
              endIndex={brush.end}
              onChange={(r) => {
                if (
                  r &&
                  typeof r.startIndex === "number" &&
                  typeof r.endIndex === "number"
                ) {
                  setBrush({ start: r.startIndex, end: r.endIndex })
                }
              }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </UnbilledExpandModal>
  )
}

function LegendItem({
  color,
  label,
  square,
}: {
  color: string
  label: string
  square?: boolean
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className={`inline-block h-2 w-4 ${square ? "rounded-sm" : "rounded-full"}`}
        style={{ background: color }}
      />
      {label}
    </span>
  )
}
