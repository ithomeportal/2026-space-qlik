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
  useOppService,
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

// Bruno R5 (2026-06-01) #2: "Service" is now a 5th measure button. It swaps the
// combo for OTP%/OTD% lines (same data as the standalone Service chart above).
type Measure = "volume" | "revenue" | "profit" | "margin_pct" | "service"

const MEASURES: { k: Measure; label: string; fmt: (v: number) => string }[] = [
  { k: "volume",     label: "Vol.",    fmt: fmtCount },
  { k: "revenue",    label: "Rev.",    fmt: fmtUsd },
  { k: "profit",     label: "Prof.",   fmt: fmtUsd },
  { k: "margin_pct", label: "Marg.%",  fmt: fmtPct },
  { k: "service",    label: "Service", fmt: (v) => `${v.toFixed(1)}%` },
]

// Bruno 2026-06-17: default the brush to the most recent 8 buckets for Week
// (last 8 weeks) and Month (last 8 months) — was 13 each, which read as
// "going back ~2 years" once the brush snapped to the full data range.
const GRAINS: { k: OppGrain; label: string; defaultVisible: number }[] = [
  { k: "day",   label: "Day",   defaultVisible: 30 },
  { k: "week",  label: "Week",  defaultVisible: 8 },
  { k: "month", label: "Month", defaultVisible: 8 },
]

// Series legend keys — toggled on/off by clicking the legend pills.
// Bruno R5 (2026-06-01) #3: "variance" (Actual − Budget) legend/tooltip entry
// after Budget. (Bruno R16: Losses series removed.)
type SeriesKey = "bars" | "budget" | "variance" | "avgLq" | "projected"

// Compact data-point labels on the bars (Bruno R4 "show the data points").
// Full USD on every bar overlaps; compact ($210K) keeps the chart readable.
const usdCompact = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
})
function labelFmt(measure: Measure, v: number): string {
  if (!Number.isFinite(v) || v === 0) return ""
  if (measure === "margin_pct") return `${v.toFixed(1)}%`
  if (measure === "volume") return fmtCount(v)
  return usdCompact.format(v)
}

export function ComboChart({ filters, loadType, setLoadType }: Props) {
  const cf = { team: filters.team, customer: filters.customer, loadType, lanes: filters.lanes, excludeLanes: filters.excludeLanes }
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

  const isService = measure === "service"

  const { data: comboRes, isLoading: comboLoading, error: comboError } = useOppCombo(cf, grain)
  const { data: workdaysRes } = useOppWorkdays()
  const { data: gaugeRes } = useOppProfitTmGauge(cf)
  // Shares the React Query cache with the standalone Service chart (#1) — no
  // extra fetch. Only the data we actually render in Service mode is used.
  const { data: serviceRes, isLoading: svcLoading, error: svcError } = useOppService(cf, grain)

  const isLoading = isService ? svcLoading : comboLoading
  const error = isService ? svcError : comboError

  const data = comboRes?.data
  const buckets = useMemo(() => data?.buckets ?? [], [data])

  const serviceBuckets = useMemo(() => serviceRes?.data?.buckets ?? [], [serviceRes])

  // Two separate typed arrays (union data confuses Recharts' generic typing).
  const chartData = useMemo(
    () => buckets.map((b) => ({ ...b, label: fmtBucket(b.bucket_start, grain) })),
    [buckets, grain],
  )
  const serviceData = useMemo(
    () => serviceBuckets.map((b) => ({ ...b, label: fmtBucket(b.bucket_start, grain) })),
    [serviceBuckets, grain],
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

  // Bruno 2026-06-18 #1 (R10): auto-fit the Service y-axis to the values in the
  // VISIBLE (brushed) window — lowest displayed % → axis min, highest → axis max —
  // with a 1% pad on each end so the lines aren't flush against the frame.
  const serviceDomain = useMemo<[number, number]>(() => {
    const slice = serviceData.slice(brush.start, brush.end + 1)
    const vals = slice
      .flatMap((d) => [d.otp_pct, d.otd_pct])
      .map((v) => Number(v))
      .filter((v) => Number.isFinite(v))
    if (!vals.length) return [90, 100]
    const lo = Math.max(0, Math.floor(Math.min(...vals) - 1))
    const hi = Math.min(100, Math.ceil(Math.max(...vals) + 1))
    return hi > lo ? [lo, hi] : [90, 100]
  }, [serviceData, brush.start, brush.end])

  // ------- Per-tab series keys (Bruno round 3) ----------------------------
  // Bars / Budget each have a per-measure variant so the chart line
  // is in the same unit as the bars (drops the dual-axis pre-r3 hack).
  const budgetKey: string = (
    measure === "revenue"    ? "budget_revenue"
    : measure === "profit"   ? "budget_profit"
    : measure === "volume"   ? "budget_loads"
    : "budget_margin_pct"
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
          {isService ? (
            <>
              <span className="flex items-center gap-1.5 text-[11px] text-[#374151]">
                <span className="inline-block h-2 w-4 rounded-sm bg-[#16A34A]" /> OTP %
              </span>
              <span className="flex items-center gap-1.5 text-[11px] text-[#374151]">
                <span className="inline-block h-2 w-4 rounded-sm bg-[#2563EB]" /> OTD %
              </span>
            </>
          ) : (
            <>
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
              {/* Bruno R5 #3: Variance = Actual − Budget, after Budget. */}
              <LegendChip
                label="Variance"
                color="#F59E0B"
                active={!isHidden("variance")}
                onClick={() => toggle("variance")}
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
            </>
          )}
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
        ) : isService ? (
          /* Bruno R5 #2: Service mode — OTP%/OTD% lines (same as the chart above). */
          <ResponsiveContainer width="100%" height={380}>
            <ComposedChart data={serviceData} margin={{ top: 16, right: 24, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              {/* Bruno 2026-06-18 #1 (R10): auto-fit the y-axis to the visible
                  OTP/OTD values (lowest → min, highest → max) with a 1% pad each
                  end, so the near-flat lines spread out and trends are readable. */}
              <YAxis tick={{ fontSize: 10 }} domain={serviceDomain} allowDecimals={false} tickFormatter={(v) => `${Number(v).toFixed(0)}%`} />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload || !payload.length) return null
                  const row = payload[0].payload as { label?: string; otp_pct?: number; otd_pct?: number }
                  return (
                    <div className="rounded-md border border-[#E5E7EB] bg-white px-3 py-2 text-xs shadow-md">
                      <div className="mb-1 font-semibold text-[#111827]">{row.label}</div>
                      <div className="flex items-center justify-between gap-4">
                        <span className="flex items-center gap-1.5">
                          <span className="inline-block h-2 w-2 rounded-full bg-[#16A34A]" /> OTP %
                        </span>
                        <span className="font-medium tabular-nums">{Number(row.otp_pct ?? 0).toFixed(2)}%</span>
                      </div>
                      <div className="flex items-center justify-between gap-4">
                        <span className="flex items-center gap-1.5">
                          <span className="inline-block h-2 w-2 rounded-full bg-[#2563EB]" /> OTD %
                        </span>
                        <span className="font-medium tabular-nums">{Number(row.otd_pct ?? 0).toFixed(2)}%</span>
                      </div>
                    </div>
                  )
                }}
              />
              {/* Bruno 2026-06-18 #2: show the % value at each data point.
                  OTP labels sit above the dot, OTD below, so they don't collide. */}
              <Line type="monotone" dataKey="otp_pct" name="OTP %" stroke="#16A34A" strokeWidth={2} dot={{ r: 3 }} connectNulls>
                <LabelList dataKey="otp_pct" position="top" fontSize={9} fill="#16A34A" formatter={(v) => `${Number(v).toFixed(1)}%`} />
              </Line>
              <Line type="monotone" dataKey="otd_pct" name="OTD %" stroke="#2563EB" strokeWidth={2} dot={{ r: 3 }} connectNulls>
                <LabelList dataKey="otd_pct" position="bottom" fontSize={9} fill="#2563EB" formatter={(v) => `${Number(v).toFixed(1)}%`} />
              </Line>
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
        ) : (
          <ResponsiveContainer width="100%" height={380}>
            <ComposedChart data={chartData} margin={{ top: 16, right: 24, bottom: 0, left: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} tickFormatter={(v) => fmt(Number(v))} />
              <Tooltip
                content={({ active, payload }) => {
                  if (!active || !payload || !payload.length) return null
                  const row = payload[0].payload as Record<string, number> & { label?: string }
                  // Bruno R16: fixed order — Actual · Budget · Variance · Avg · Projected.
                  // (Losses series removed.)
                  const actualVal = Number(row[measure] ?? 0)
                  const budgetVal = Number(row[budgetKey] ?? 0)
                  const items = [
                    { key: "bars" as SeriesKey,      label: "Actual",    color: "#0EA5E9", value: actualVal },
                    { key: "budget" as SeriesKey,    label: "Budget",    color: "#16A34A", value: budgetVal },
                    { key: "variance" as SeriesKey,  label: "Variance",  color: "#F59E0B", value: actualVal - budgetVal },
                    { key: "avgLq" as SeriesKey,     label: "Avg",       color: "#9333EA", value: avgLq },
                    { key: "projected" as SeriesKey, label: "Projected", color: "#2563EB", value: projected },
                  ].filter((i) => !isHidden(i.key))
                  return (
                    <div className="rounded-md border border-[#E5E7EB] bg-white px-3 py-2 text-xs shadow-md">
                      <div className="mb-1 font-semibold text-[#111827]">{row.label}</div>
                      {items.map((i) => (
                        <div key={i.key} className="flex items-center justify-between gap-4">
                          <span className="flex items-center gap-1.5">
                            <span className="inline-block h-2 w-2 rounded-full" style={{ background: i.color }} />
                            {i.label}
                          </span>
                          <span className="font-medium tabular-nums text-[#111827]">{fmt(i.value)}</span>
                        </div>
                      ))}
                    </div>
                  )
                }}
              />
              {!isHidden("bars") && (
                <Bar
                  dataKey={measure}
                  name="Actual"
                  fill="#7DD3FC"
                >
                  <LabelList
                    dataKey={measure}
                    position="top"
                    fontSize={9}
                    fill="#475569"
                    formatter={(v) => labelFmt(measure, Number(v))}
                  />
                </Bar>
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
  const completionPct = target > 0 ? (mtd / target) * 100 : 0
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
      {target > 0 && (
        <div className="mt-0.5 text-center text-xs font-medium tabular-nums text-[#374151]">
          {completionPct.toFixed(2)}%
        </div>
      )}
    </div>
  )
}
