"use client"

import { useEffect, useMemo, useState } from "react"
import { Loader2 } from "lucide-react"
import {
  Bar,
  Brush,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  fmtBucket,
  fmtCount,
  fmtPct,
  fmtUsd,
  useOppCombo,
  useOppProfitTmGauge,
  useOppWorkdays,
  type LoadType,
  type OppGrain,
  type OppFilters,
} from "@/lib/ops-portal-overview-api"

interface Props {
  filters: OppFilters
  loadType: LoadType
  setLoadType: (v: LoadType) => void
}

type Measure = "volume" | "revenue" | "profit" | "margin_pct"

const MEASURES: { k: Measure; label: string; fmt: (v: number) => string }[] = [
  { k: "volume",     label: "Vol.",   fmt: fmtCount },
  { k: "revenue",    label: "Rev.",   fmt: fmtUsd },
  { k: "profit",     label: "Prof.",  fmt: fmtUsd },
  { k: "margin_pct", label: "Marg.%", fmt: fmtPct },
]

const GRAINS: { k: OppGrain; label: string; defaultVisible: number }[] = [
  { k: "day",   label: "Day",   defaultVisible: 30 },
  { k: "week",  label: "Week",  defaultVisible: 13 },
  { k: "month", label: "Month", defaultVisible: 13 },
]

// Series legend keys — toggled on/off by clicking the legend pills.
type SeriesKey = "bars" | "budget" | "avgLq" | "projected" | "losses"

export function ComboChart({ filters, loadType, setLoadType }: Props) {
  const cf = { team: filters.team, customer: filters.customer, loadType }
  const [grain, setGrain] = useState<OppGrain>("month")
  const [measure, setMeasure] = useState<Measure>("revenue")
  const [hidden, setHidden] = useState<Set<SeriesKey>>(new Set())
  const toggle = (k: SeriesKey) => {
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(k)) next.delete(k)
      else next.add(k)
      return next
    })
  }
  const isHidden = (k: SeriesKey) => hidden.has(k)

  const { data: comboRes, isLoading, error } = useOppCombo(cf, grain)
  const { data: workdaysRes } = useOppWorkdays()
  const { data: gaugeRes } = useOppProfitTmGauge(cf)

  const data = comboRes?.data
  const buckets = useMemo(() => data?.buckets ?? [], [data])

  const chartData = useMemo(
    () => buckets.map((b) => ({ ...b, label: fmtBucket(b.bucket_start, grain) })),
    [buckets, grain],
  )

  // Brush position — default to the most recent N buckets per grain.
  const defaultVisible =
    GRAINS.find((g) => g.k === grain)?.defaultVisible ?? 13
  const [brush, setBrush] = useState<{ start: number; end: number }>({
    start: 0,
    end: 0,
  })

  // Reset brush whenever grain or data length changes.
  useEffect(() => {
    if (!chartData.length) return
    const end = chartData.length - 1
    const start = Math.max(0, end - defaultVisible + 1)
    setBrush({ start, end })
  }, [grain, chartData.length, defaultVisible])

  // ------- Per-tab series keys (Bruno round 3) ----------------------------
  // Bars / Budget / Losses each have a per-measure variant so the chart line
  // is in the same unit as the bars (drops the dual-axis pre-r3 hack).
  const budgetKey: keyof typeof chartData[number] = (
    measure === "revenue"    ? "budget_revenue"
    : measure === "profit"   ? "budget_profit"
    : measure === "volume"   ? "budget_loads"
    : "budget_margin_pct"
  )
  const lossesKey: keyof typeof chartData[number] = (
    measure === "revenue"    ? "losses_rev"
    : measure === "profit"   ? "losses_prof"
    : measure === "volume"   ? "losses_vol"
    : "losses_margin_pct"
  )

  const measureMeta = MEASURES.find((m) => m.k === measure)!
  const fmt = measureMeta.fmt

  // Average-LQ = mean of last 4 closed buckets (exclude latest, which is partial).
  const avgLq = useMemo(() => {
    if (chartData.length < 5) return 0
    const closed = chartData.slice(brush.end - 4, brush.end)
    const vals = closed
      .map((d) => Number((d as Record<string, unknown>)[measure] ?? 0))
      .filter((v) => Number.isFinite(v))
    if (!vals.length) return 0
    return vals.reduce((a, b) => a + b, 0) / vals.length
  }, [chartData, measure, brush.end])

  // Projected — pick per-measure key from response.
  const projected = (
    measure === "revenue"    ? data?.projected_revenue
    : measure === "profit"   ? data?.projected_profit
    : measure === "volume"   ? data?.projected_vol
    : data?.projected_margin_pct
  ) ?? 0

  const wd = workdaysRes?.data
  const gauge = gaugeRes?.data

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
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <PillGroup
          options={GRAINS.map((g) => ({ k: g.k, label: g.label }))}
          value={grain}
          onChange={setGrain}
        />
        <div className="ml-auto flex flex-wrap items-center gap-2 text-xs">
          <LegendChip
            label={measureMeta.label}
            color="#7DD3FC"
            active={!isHidden("bars")}
            onClick={() => toggle("bars")}
          />
          <LegendChip
            label="BDGT"
            color="#16A34A"
            active={!isHidden("budget")}
            onClick={() => toggle("budget")}
          />
          <LegendChip
            label="Avg. LQ"
            color="#9333EA"
            dashed
            active={!isHidden("avgLq")}
            onClick={() => toggle("avgLq")}
          />
          <LegendChip
            label="Projected TM"
            color="#2563EB"
            dashed
            active={!isHidden("projected")}
            onClick={() => toggle("projected")}
          />
          <LegendChip
            label="losses x M"
            color="#DC2626"
            active={!isHidden("losses")}
            onClick={() => toggle("losses")}
          />
        </div>
      </div>

      {/* Chart body */}
      <div className="px-3 py-3">
        {isLoading ? (
          <div className="flex h-[380px] items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : error ? (
          <div className="flex h-[380px] items-center justify-center text-sm text-[#DC2626]">
            Failed to load chart
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={380}>
            <ComposedChart data={chartData} margin={{ top: 16, right: 24, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => fmt(Number(v))} />
              <Tooltip
                formatter={(v, name) => {
                  const num = Number(v)
                  if (measure === "margin_pct") return fmtPct(num)
                  if (measure === "volume" && (name === "Budget" || name === "Losses x M" || name === measureMeta.label))
                    return fmtCount(num)
                  return fmtUsd(num)
                }}
              />
              {!isHidden("bars") && (
                <Bar
                  dataKey={measure}
                  name={measureMeta.label}
                  fill="#7DD3FC"
                />
              )}
              {!isHidden("budget") && (
                <Line
                  type="monotone"
                  dataKey={budgetKey}
                  name="Budget"
                  stroke="#16A34A"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              )}
              {!isHidden("losses") && (
                <Line
                  type="monotone"
                  dataKey={lossesKey}
                  name="Losses x M"
                  stroke="#DC2626"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              )}
              {!isHidden("avgLq") && avgLq !== 0 && (
                <ReferenceLine
                  y={avgLq}
                  stroke="#9333EA"
                  strokeDasharray="6 4"
                  label={{ value: `Avg. LQ ${fmt(avgLq)}`, fontSize: 10, fill: "#7C3AED", position: "right" }}
                />
              )}
              {!isHidden("projected") && projected !== 0 && (
                <ReferenceLine
                  y={projected}
                  stroke="#2563EB"
                  strokeDasharray="6 4"
                  label={{ value: `Projected TM ${fmt(projected)}`, fontSize: 10, fill: "#2563EB", position: "right" }}
                />
              )}
              <Brush
                dataKey="label"
                height={20}
                stroke="#94A3B8"
                travellerWidth={8}
                startIndex={brush.start}
                endIndex={brush.end}
                onChange={(r) => {
                  if (r && typeof r.startIndex === "number" && typeof r.endIndex === "number") {
                    setBrush({ start: r.startIndex, end: r.endIndex })
                  }
                }}
              />
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

function LegendChip({
  label,
  color,
  dashed,
  active,
  onClick,
}: {
  label: string
  color: string
  dashed?: boolean
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
        active
          ? "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F9FAFB]"
          : "border-[#E5E7EB] bg-[#F3F4F6] text-[#9CA3AF] line-through"
      }`}
    >
      <span
        className="inline-block h-2 w-4 rounded-sm"
        style={{
          background: dashed
            ? `repeating-linear-gradient(90deg, ${color} 0 4px, transparent 4px 8px)`
            : color,
          opacity: active ? 1 : 0.4,
        }}
      />
      {label}
    </button>
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
