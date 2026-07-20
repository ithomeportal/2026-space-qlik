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

// Bruno Aging (PDF 2026-07-20) "+" Table view helpers. Week bucket is an
// ISO-Monday start → render "Jun 15 – Jun 21" (Mon–Sun) and the ISO week #.
function fmtWeekRange(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number)
  if (!y || !m || !d) return iso
  const start = new Date(Date.UTC(y, m - 1, d))
  const end = new Date(start.getTime())
  end.setUTCDate(end.getUTCDate() + 6)
  const f = (dt: Date) => `${MONTHS_ABBR[dt.getUTCMonth()]} ${dt.getUTCDate()}`
  return `${f(start)} – ${f(end)}`
}
function isoWeekNum(iso: string): number | null {
  const [y, m, d] = iso.split("-").map(Number)
  if (!y || !m || !d) return null
  const dt = new Date(Date.UTC(y, m - 1, d))
  const day = dt.getUTCDay() || 7
  dt.setUTCDate(dt.getUTCDate() + 4 - day) // shift to Thursday of this week
  const yearStart = new Date(Date.UTC(dt.getUTCFullYear(), 0, 1))
  return Math.ceil(((dt.getTime() - yearStart.getTime()) / 86400000 + 1) / 7)
}

// Default the brush to the most recent 8 buckets (matches the reference image;
// Bruno Aging R 2026-07-13 also wants the Week view defaulting to 8 weeks).
const DEFAULT_VISIBLE = 8

// Bruno Aging (PDF 2026-07-20): the "+" Table view lists the last 8 months
// (Month view) or last 14 weeks (Week view).
const TABLE_ROWS_MONTH = 8
const TABLE_ROWS_WEEK = 14

type ChartView = "chart" | "table"

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
  // Bruno Aging (PDF 2026-07-20): Chart (default) / Table view toggle.
  const [view, setView] = useState<ChartView>("chart")
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

  // Bruno Aging (PDF 2026-07-20): rows for the "+" Table view — last 8 months
  // or last 14 weeks, most recent first. Percentage = within/total; AVG Days
  // comes straight from the backend bucket aggregate.
  const tableData = useMemo(() => {
    if (!payload) return []
    const s = payload[metric]
    const avg = s.avg_days ?? []
    const n = grain === "week" ? TABLE_ROWS_WEEK : TABLE_ROWS_MONTH
    const rows = payload.months.map((iso, i) => {
      const total = s.total[i] ?? 0
      const within = s.within[i] ?? 0
      return {
        iso,
        pct: total > 0 ? (within / total) * 100 : null,
        avgDays: avg[i] ?? null,
      }
    })
    return rows.slice(Math.max(0, rows.length - n)).reverse()
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
        <div className="flex items-center gap-2">
          {/* Bruno Aging (PDF 2026-07-20): Chart / Table view toggle. */}
          <div className="inline-flex overflow-hidden rounded-md border border-[#E5E7EB]">
            {(["chart", "table"] as ChartView[]).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`px-2.5 py-1 text-[11px] capitalize ${
                  view === v
                    ? "bg-[#1B3A5C] text-white"
                    : "bg-white text-[#6B7280] hover:bg-[#F3F4F6]"
                }`}
              >
                {v}
              </button>
            ))}
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
      ) : view === "table" ? (
        <div className="max-h-[420px] overflow-auto rounded-lg border border-[#E5E7EB]">
          <table className="w-full text-left text-[12px]">
            <thead className="sticky top-0 bg-[#F8FAFC] text-[11px] font-semibold text-[#475569]">
              <tr>
                <th className="px-3 py-2">{grain === "week" ? "Week" : "Month"}</th>
                {grain === "week" && <th className="px-3 py-2">Week #</th>}
                <th className="px-3 py-2 text-right">Percentage</th>
                <th className="px-3 py-2 text-right">AVG Days</th>
              </tr>
            </thead>
            <tbody>
              {tableData.map((r) => (
                <tr key={r.iso} className="border-t border-[#F1F5F9]">
                  <td className="px-3 py-2 font-medium text-[#111827]">
                    {grain === "week" ? fmtWeekRange(r.iso) : fmtMonth(r.iso)}
                  </td>
                  {grain === "week" && (
                    <td className="px-3 py-2 tabular-nums text-[#6B7280]">
                      {isoWeekNum(r.iso) ?? "—"}
                    </td>
                  )}
                  <td className="px-3 py-2 text-right font-semibold tabular-nums text-[#1B3A5C]">
                    {r.pct == null ? "—" : `${r.pct.toFixed(1)}%`}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-[#111827]">
                    {r.avgDays == null ? "—" : r.avgDays.toFixed(1)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
