"use client"

import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  fmtCount,
  fmtMonth,
  fmtPct,
  fmtUsd,
  useOppCombo,
  useOppProfitTmGauge,
  useOppWorkdays,
  type LoadType,
  type OppFilters,
} from "@/lib/ops-portal-overview-api"

interface Props {
  filters: OppFilters
  loadType: LoadType
  setLoadType: (v: LoadType) => void
}

type Measure = "volume" | "revenue" | "profit" | "margin_pct"

const MEASURES: { k: Measure; label: string; color: string; fmt: (v: number) => string }[] = [
  { k: "volume",     label: "Vol.",   color: "#7DD3FC", fmt: fmtCount },
  { k: "revenue",    label: "Rev.",   color: "#7DD3FC", fmt: fmtUsd },
  { k: "profit",     label: "Prof.",  color: "#7DD3FC", fmt: fmtUsd },
  { k: "margin_pct", label: "Marg.%", color: "#7DD3FC", fmt: fmtPct },
]

export function ComboChart({ filters, loadType, setLoadType }: Props) {
  const cf = { team: filters.team, customer: filters.customer, loadType }
  const { data: comboRes, isLoading, error } = useOppCombo(cf)
  const { data: workdaysRes } = useOppWorkdays()
  const { data: gaugeRes } = useOppProfitTmGauge(cf)

  const [measure, setMeasure] = useState<Measure>("revenue")

  const chartData = useMemo(() => {
    const months = comboRes?.data?.months ?? []
    return months.map((m) => ({
      ...m,
      label: fmtMonth(m.month_start),
    }))
  }, [comboRes])

  const projectedTm = comboRes?.data?.projected_tm ?? 0
  const wd = workdaysRes?.data
  const gauge = gaugeRes?.data

  // Average-LQ line = mean of last 4 closed months for the chosen measure (excludes current).
  const avgLq = useMemo(() => {
    if (chartData.length < 5) return 0
    const closed = chartData.slice(-5, -1)
    const vals = closed
      .map((d) => Number(d[measure as keyof typeof d] || 0))
      .filter((v) => Number.isFinite(v))
    if (!vals.length) return 0
    return vals.reduce((a, b) => a + b, 0) / vals.length
  }, [chartData, measure])

  // Budget line value to overlay — match the toggled measure.
  const budgetKey: keyof typeof chartData[number] | null =
    measure === "revenue" ? "budget_revenue"
    : measure === "profit" ? "budget_profit"
    : measure === "volume" ? "budget_loads"
    : null

  const fmt = MEASURES.find((m) => m.k === measure)!.fmt

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      {/* KPI MANAGEMENT toggle bar */}
      <div className="flex flex-wrap items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
        <span className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
          KPI Management
        </span>
        <PillGroup
          options={MEASURES.map((m) => ({ k: m.k, label: m.label }))}
          value={measure}
          onChange={setMeasure}
        />
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <PillGroup
          options={[
            { k: "" as LoadType, label: "All" },
            { k: "contract" as LoadType, label: "Contractual" },
            { k: "spot" as LoadType, label: "Spot" },
          ]}
          value={loadType}
          onChange={setLoadType}
        />
        <div className="ml-auto flex items-center gap-3 text-xs">
          <Legend2 color="#7DD3FC" label={MEASURES.find((m) => m.k === measure)!.label} />
          {budgetKey && <Legend2 color="#16A34A" label="BDGT" />}
          <Legend2 color="#9333EA" label="Avg. LQ" dashed />
          <Legend2 color="#2563EB" label="Projected TM" dashed />
          <Legend2 color="#DC2626" label="losses x M" />
        </div>
      </div>

      {/* Chart body */}
      <div className="px-3 py-3">
        {isLoading ? (
          <div className="flex h-[360px] items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : error ? (
          <div className="flex h-[360px] items-center justify-center text-sm text-[#DC2626]">
            Failed to load chart
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={360}>
            <ComposedChart data={chartData} margin={{ top: 16, right: 24, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis
                yAxisId="left"
                tick={{ fontSize: 10 }}
                tickFormatter={(v) => fmt(Number(v))}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fontSize: 10 }}
                tickFormatter={(v) => fmtUsd(Number(v))}
              />
              <Tooltip
                formatter={(v, name) => {
                  const num = Number(v)
                  if (typeof name === "string" && name.includes("Margin")) return fmtPct(num)
                  return fmtUsd(num)
                }}
              />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey={measure} name={MEASURES.find((m) => m.k === measure)!.label} fill="#7DD3FC" />
              {budgetKey && (
                <Line
                  yAxisId="left"
                  type="monotone"
                  dataKey={budgetKey}
                  name="Budget"
                  stroke="#16A34A"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              )}
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="losses"
                name="Losses x M"
                stroke="#DC2626"
                strokeWidth={2}
                dot={{ r: 3 }}
              />
              {avgLq > 0 && (
                <ReferenceLine
                  yAxisId="left"
                  y={avgLq}
                  stroke="#9333EA"
                  strokeDasharray="6 4"
                  label={{ value: `Avg. LQ ${fmt(avgLq)}`, fontSize: 10, fill: "#7C3AED", position: "right" }}
                />
              )}
              {projectedTm > 0 && measure === "revenue" && (
                <ReferenceLine
                  yAxisId="left"
                  y={projectedTm}
                  stroke="#2563EB"
                  strokeDasharray="6 4"
                  label={{ value: `Projected TM ${fmtUsd(projectedTm)}`, fontSize: 10, fill: "#2563EB", position: "right" }}
                />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        )}

        {/* Bottom row: Working-day KPIs + Profit-TM gauge */}
        <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-[auto_1fr]">
          <div className="grid grid-cols-3 gap-3">
            <KpiBox label="Total Working Days" value={wd?.total_workdays ?? 0} tone="neutral" />
            <KpiBox label="Past Days"          value={wd?.past_workdays ?? 0}  tone="neutral" />
            <KpiBox label="Pending Days"       value={wd?.pending_workdays ?? 0} tone="accent" />
          </div>
          <ProfitTmGauge
            mtd={gauge?.profit_mtd ?? 0}
            target={gauge?.profit_budget ?? 0}
          />
        </div>
      </div>
    </section>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function PillGroup<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { k: T; label: string }[]
  value: T
  onChange: (v: T) => void
}) {
  return (
    <div className="flex rounded-lg border border-[#E5E7EB] bg-white text-xs">
      {options.map((opt) => (
        <button
          key={opt.k}
          onClick={() => onChange(opt.k)}
          className={`px-3 py-1 ${
            value === opt.k
              ? "bg-[#1B3A5C] font-semibold text-white"
              : "text-[#6B7280] hover:text-[#111827]"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  )
}

function Legend2({ color, label, dashed }: { color: string; label: string; dashed?: boolean }) {
  return (
    <span className="flex items-center gap-1 text-[#374151]">
      <span
        className="inline-block h-2 w-4 rounded-sm"
        style={{
          background: dashed ? `repeating-linear-gradient(90deg, ${color} 0 4px, transparent 4px 8px)` : color,
        }}
      />
      {label}
    </span>
  )
}

function KpiBox({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone: "neutral" | "accent"
}) {
  return (
    <div
      className={`rounded-lg border px-3 py-2 ${
        tone === "accent"
          ? "border-[#BFDBFE] bg-[#EFF6FF]"
          : "border-[#E5E7EB] bg-white"
      }`}
    >
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className="text-2xl font-bold text-[#1B3A5C]">{value}</div>
    </div>
  )
}

function ProfitTmGauge({ mtd, target }: { mtd: number; target: number }) {
  const max = Math.max(target, mtd, 1) * 1.05
  const pct = Math.min(100, Math.max(0, (mtd / max) * 100))
  const targetPct = target > 0 ? Math.min(100, Math.max(0, (target / max) * 100)) : 0
  const onTrack = target > 0 && mtd >= target * (new Date().getDate() / 30)
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-2">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
          Profit - TM
        </span>
        <span className="text-xs font-semibold text-[#1B3A5C]">
          {fmtUsd(mtd)} <span className="text-[#9CA3AF]">/ Target {fmtUsd(target)}</span>
        </span>
      </div>
      <div className="relative h-3 w-full overflow-hidden rounded-full bg-[#F3F4F6]">
        <div
          className="absolute inset-y-0 left-0"
          style={{
            width: `${pct}%`,
            background: onTrack ? "#16A34A" : mtd < 0 ? "#DC2626" : "#F59E0B",
          }}
        />
        {targetPct > 0 && (
          <div
            className="absolute inset-y-0 w-0.5 bg-[#1B3A5C]"
            style={{ left: `${targetPct}%` }}
          />
        )}
      </div>
    </div>
  )
}
