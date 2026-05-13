"use client"

import { LineChart, Line, ResponsiveContainer, Tooltip } from "recharts"
import { CalendarClock, CheckCircle2, ClipboardList, FileText, PackageCheck, Receipt } from "lucide-react"
import type {
  AdminCashflowKpis,
  AdminCashflowSparklines,
} from "@/lib/admin-cashflow-api"
import { fmtPct, fmtUsd } from "./format"

interface Props {
  kpis: AdminCashflowKpis | undefined
  loading: boolean
  sparklines: AdminCashflowSparklines | undefined
}

function fmtDays(v: number | undefined) {
  if (v === undefined || v === null || Number.isNaN(v)) return "—"
  return `${v.toFixed(1)}d`
}

export function KpiStrip({ kpis, loading, sparklines }: Props) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3 lg:grid-cols-7">
      <PctKpiCard
        icon={<CheckCircle2 className="h-4 w-4 text-[#1B3A5C]" />}
        label="Delivery vs Bill ≤10d"
        value={loading ? "…" : fmtPct(kpis?.pct_del_bill_le10)}
        threshold={95}
        actual={kpis?.pct_del_bill_le10}
        spark={sparklines?.del_bill_le10 ?? []}
        weeks={sparklines?.weeks ?? []}
      />
      <AvgDaysKpiCard
        icon={<CalendarClock className="h-4 w-4 text-[#1B3A5C]" />}
        label="Avg Days Del → Bill"
        value={loading ? "…" : fmtDays(kpis?.avg_days_del_bill)}
        actual={kpis?.avg_days_del_bill}
        warnAbove={10}
      />
      <PctKpiCard
        icon={<FileText className="h-4 w-4 text-[#1B3A5C]" />}
        label="BOL vs Bill ≤2d"
        value={loading ? "…" : fmtPct(kpis?.pct_bol_bill_le2)}
        threshold={90}
        actual={kpis?.pct_bol_bill_le2}
        spark={sparklines?.bol_bill_le2 ?? []}
        weeks={sparklines?.weeks ?? []}
      />
      <AvgDaysKpiCard
        icon={<CalendarClock className="h-4 w-4 text-[#1B3A5C]" />}
        label="Avg Days BOL → Bill"
        value={loading ? "…" : fmtDays(kpis?.avg_days_bol_bill)}
        actual={kpis?.avg_days_bol_bill}
        warnAbove={2}
      />
      <PctKpiCard
        icon={<Receipt className="h-4 w-4 text-[#1B3A5C]" />}
        label="Carrier Inv vs Bill ≤2d"
        value={loading ? "…" : fmtPct(kpis?.pct_carrinv_bill_le2)}
        threshold={80}
        actual={kpis?.pct_carrinv_bill_le2}
        spark={sparklines?.carrinv_bill_le2 ?? []}
        weeks={sparklines?.weeks ?? []}
      />
      <UsdKpiCard
        icon={<PackageCheck className="h-4 w-4 text-[#B45309]" />}
        label="Delivered, not billed"
        value={loading ? "…" : fmtUsd(kpis?.delivered_not_billed_usd)}
        warn={
          kpis !== undefined &&
          kpis.delivered_not_billed_usd > 1_000_000
        }
      />
      <UsdKpiCard
        icon={<ClipboardList className="h-4 w-4 text-[#B45309]" />}
        label="Ready, not billed"
        value={loading ? "…" : fmtUsd(kpis?.ready_not_billed_usd)}
        warn={
          kpis !== undefined &&
          kpis.ready_not_billed_usd > 1_000_000
        }
      />
    </div>
  )
}

interface AvgDaysKpiProps {
  icon: React.ReactNode
  label: string
  value: string
  actual: number | undefined
  warnAbove: number
}

function AvgDaysKpiCard({ icon, label, value, actual, warnAbove }: AvgDaysKpiProps) {
  // green if at/below target days; amber within 50% over; red beyond.
  let tone = "border-[#E5E7EB] bg-white"
  let valueColor = "text-[#1B3A5C]"
  if (actual !== undefined && !Number.isNaN(actual)) {
    if (actual <= warnAbove) {
      tone = "border-[#A7F3D0] bg-[#ECFDF5]"
      valueColor = "text-[#065F46]"
    } else if (actual <= warnAbove * 1.5) {
      tone = "border-[#FCD34D] bg-[#FFFBEB]"
      valueColor = "text-[#92400E]"
    } else {
      tone = "border-[#FCA5A5] bg-[#FEF2F2]"
      valueColor = "text-[#991B1B]"
    }
  }
  return (
    <div className={`rounded-xl border p-3 shadow-sm ${tone}`}>
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-[#6B7280]">
        {icon}
        {label}
      </div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${valueColor}`}>
        {value}
      </div>
      <div className="mt-1 text-[10px] text-[#6B7280]">target ≤{warnAbove}d</div>
    </div>
  )
}

interface PctKpiProps {
  icon: React.ReactNode
  label: string
  value: string
  threshold: number
  actual: number | undefined
  spark: (number | null)[]
  weeks: string[]
}

function PctKpiCard({ icon, label, value, threshold, actual, spark, weeks }: PctKpiProps) {
  // Card highlight: green if at/above threshold, amber if within 5pts, red below.
  let tone = "border-[#E5E7EB] bg-white"
  let valueColor = "text-[#1B3A5C]"
  if (actual !== undefined) {
    if (actual >= threshold) {
      tone = "border-[#A7F3D0] bg-[#ECFDF5]"
      valueColor = "text-[#065F46]"
    } else if (actual >= threshold - 5) {
      tone = "border-[#FCD34D] bg-[#FFFBEB]"
      valueColor = "text-[#92400E]"
    } else {
      tone = "border-[#FCA5A5] bg-[#FEF2F2]"
      valueColor = "text-[#991B1B]"
    }
  }

  // Recharts wants {x, y} objects; nulls are dropped via connectNulls=false.
  const data = spark.map((y, i) => ({ wk: weeks[i] ?? "", v: y }))
  const hasData = data.some((d) => d.v !== null && d.v !== undefined)

  return (
    <div className={`rounded-xl border p-3 shadow-sm ${tone}`}>
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-[#6B7280]">
        {icon}
        {label}
      </div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${valueColor}`}>
        {value}
      </div>
      <div className="mt-1 text-[10px] text-[#6B7280]">
        target ≥{threshold}%
      </div>
      <div className="mt-1 h-10">
        {hasData ? (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <Line
                type="monotone"
                dataKey="v"
                stroke="#1B3A5C"
                strokeWidth={1.6}
                dot={false}
                isAnimationActive={false}
                connectNulls={false}
              />
              <Tooltip
                cursor={{ stroke: "#9CA3AF", strokeDasharray: "2 2" }}
                contentStyle={{
                  fontSize: 11,
                  borderRadius: 6,
                  border: "1px solid #E5E7EB",
                  padding: "4px 8px",
                }}
                labelFormatter={(v) => `Week of ${v}`}
                formatter={(v) =>
                  v === null || v === undefined ? ["—", "%"] : [`${v}%`, ""]
                }
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="flex h-full items-center text-[10px] text-[#9CA3AF]">
            12-week trend (no data yet)
          </div>
        )}
      </div>
    </div>
  )
}

interface UsdKpiProps {
  icon: React.ReactNode
  label: string
  value: string
  warn?: boolean
}

function UsdKpiCard({ icon, label, value, warn = false }: UsdKpiProps) {
  return (
    <div
      className={`rounded-xl border p-3 shadow-sm ${
        warn
          ? "border-[#FCD34D] bg-[#FFFBEB]"
          : "border-[#E5E7EB] bg-white"
      }`}
    >
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-[#6B7280]">
        {icon}
        {label}
      </div>
      <div
        className={`mt-1 text-2xl font-semibold tabular-nums ${
          warn ? "text-[#92400E]" : "text-[#1B3A5C]"
        }`}
      >
        {value}
      </div>
      <div className="mt-1 text-[10px] text-[#6B7280]">$ revenue at risk</div>
    </div>
  )
}
