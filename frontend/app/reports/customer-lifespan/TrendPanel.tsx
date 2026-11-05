"use client"

import { useMemo, useState } from "react"
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
  COLORS,
  fmtInt,
  fmtPct,
  fmtUsd,
  fmtUsdCompact,
  fmtDate,
  useFlowMembers,
  useTrend,
  type Division,
  type FlowMember,
  type Grain,
  type ReportFilters,
  type TrendRow,
  type Window,
} from "@/lib/customer-lifespan-api"
import { ListDrawer, type ListSection } from "./ListDrawer"
import { AssignedCell, Card, ErrorBox, Loading, Segmented } from "./ui"

const GRAINS = [
  { k: "month", label: "Month" },
  { k: "quarter", label: "Quarter" },
  { k: "year", label: "Year" },
] as const

const yearOf = (period: string) => Number(period.slice(0, 4))

function YearRange({ years, from, to, onChange }: {
  years: number[]
  from: number
  to: number
  onChange: (from: number, to: number) => void
}) {
  const sel = "rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
  return (
    <div className="flex items-center gap-2 text-xs text-[#6B7280]">
      Years
      <select className={sel} value={from} onChange={(e) => onChange(Number(e.target.value), Math.max(to, Number(e.target.value)))}>
        {years.map((y) => <option key={y} value={y}>{y}</option>)}
      </select>
      –
      <select className={sel} value={to} onChange={(e) => onChange(Math.min(from, Number(e.target.value)), Number(e.target.value))}>
        {years.map((y) => <option key={y} value={y}>{y}</option>)}
      </select>
    </div>
  )
}

// The tooltip's reading order (deck p.5): the stock first, then the flows.
const FLOW_ORDER: Record<string, number> = {
  "Customer base": 0, "Shipping customers": 1, New: 2, "Came back": 3, Lost: 4,
}

function FlowChart({ rows, onPick }: { rows: TrendRow[]; onPick: (period: string) => void }) {
  const data = rows.map((r) => ({ ...r, label: r.partial ? `${r.period}*` : r.period, lostNeg: -r.lost }))
  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={data}
          stackOffset="sign"
          margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
          className="cursor-pointer"
          onClick={(state) => {
            // null = a click on the legend or margin; Number(null) would open the first period.
            if (state?.activeTooltipIndex == null) return
            const row = rows[Number(state.activeTooltipIndex)]
            if (row) onPick(row.period)
          }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} minTickGap={12} />
          <YAxis yAxisId="flow" tick={{ fontSize: 11 }} width={36} allowDecimals={false} />
          <YAxis yAxisId="stock" orientation="right" tick={{ fontSize: 11 }} width={36} allowDecimals={false} />
          <ReferenceLine yAxisId="flow" y={0} stroke="#9CA3AF" />
          <Tooltip
            formatter={(v, name) => [fmtInt(Math.abs(Number(v))), String(name)]}
            labelFormatter={(l) => `${l}${String(l).endsWith("*") ? " (in progress)" : ""}`}
            itemSorter={(item) => FLOW_ORDER[String(item.name)] ?? 9}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar yAxisId="flow" dataKey="new" name="New" stackId="f" fill={COLORS.new} />
          <Bar yAxisId="flow" dataKey="reactivated" name="Came back" stackId="f" fill={COLORS.reactivated} />
          <Bar yAxisId="flow" dataKey="lostNeg" name="Lost" stackId="f" fill={COLORS.lost} />
          <Line yAxisId="stock" dataKey="base" name="Customer base" stroke={COLORS.base} strokeWidth={2} dot={false} />
          <Line yAxisId="stock" dataKey="active" name="Shipping customers" stroke={COLORS.active} strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function ValueTooltip({ active, payload, label }: {
  active?: boolean
  payload?: readonly { payload?: unknown }[]
  label?: string | number
}) {
  const r = payload?.[0]?.payload as TrendRow | undefined
  if (!active || !r) return null
  const line = (name: string, value: string, color: string) => (
    <div style={{ color }}>{name}: {value}</div>
  )
  return (
    <div className="rounded border border-[#E5E7EB] bg-white px-3 py-2 text-xs shadow-sm">
      <div className="mb-1 text-[#111827]">{label}</div>
      {line("Margin %", fmtPct(r.margin_pct), COLORS.navy)}
      {line("Profit ($)", fmtUsd(r.margin), COLORS.margin)}
      {line("Profit per Customer ($)", fmtUsd(r.margin_per_active), COLORS.navy)}
      {line("Revenue ($)", fmtUsd(r.revenue), "#64748B")}
    </div>
  )
}

function ValueChart({ rows }: { rows: TrendRow[] }) {
  const data = rows.map((r) => ({ ...r, label: r.partial ? `${r.period}*` : r.period }))
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} minTickGap={12} />
          <YAxis yAxisId="usd" tickFormatter={(v: number) => fmtUsdCompact(v)} tick={{ fontSize: 11 }} width={60} />
          <YAxis yAxisId="per" orientation="right" tickFormatter={(v: number) => fmtUsdCompact(v)} tick={{ fontSize: 11 }} width={60} />
          <Tooltip content={<ValueTooltip />} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar yAxisId="usd" dataKey="revenue" name="Revenue ($)" fill={COLORS.revenue} />
          <Bar yAxisId="usd" dataKey="margin" name="Profit ($)" fill={COLORS.margin} />
          <Line yAxisId="per" dataKey="margin_per_active" name="Profit per Customer ($)" stroke={COLORS.navy} strokeWidth={2} dot={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function TrendTable({ rows }: { rows: TrendRow[] }) {
  const th = "px-2 py-1.5 text-right font-medium"
  const td = "px-2 py-1 text-right tabular-nums"
  return (
    <div className="max-h-96 overflow-auto">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-[#F9FAFB] text-[#6B7280]">
          <tr>
            <th className="px-2 py-1.5 text-left font-medium">Period</th>
            <th className={th}>Base</th><th className={th}>Shipping</th><th className={th}>New</th>
            <th className={th}>Came back</th><th className={th}>Lost</th><th className={th}>Net</th>
            <th className={th}>Revenue ($)</th><th className={th}>Profit ($)</th><th className={th}>Margin %</th>
            <th className={th}>Profit per Customer ($)</th>
          </tr>
        </thead>
        <tbody>
          {[...rows].reverse().map((r) => (
            <tr key={r.period} className="border-t border-[#F3F4F6]">
              <td className="px-2 py-1 text-left">{r.period}{r.partial && <span className="text-[#9CA3AF]"> (in progress)</span>}</td>
              <td className={td}>{fmtInt(r.base)}</td><td className={td}>{fmtInt(r.active)}</td>
              <td className={`${td} text-[#059669]`}>{fmtInt(r.new)}</td>
              <td className={`${td} text-[#2563EB]`}>{fmtInt(r.reactivated)}</td>
              <td className={`${td} text-[#DC2626]`}>{fmtInt(r.lost)}</td>
              <td className={`${td} ${r.net < 0 ? "text-[#DC2626]" : ""}`}>{r.net > 0 ? `+${r.net}` : r.net}</td>
              <td className={td}>{fmtUsd(r.revenue)}</td><td className={td}>{fmtUsd(r.margin)}</td>
              <td className={td}>{fmtPct(r.margin_pct)}</td><td className={td}>{fmtUsd(r.margin_per_active)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function memberRows(rows: FlowMember[], dateLabel: string): ListSection["rows"] {
  return rows.map((m) => ({
    id: m.customer_id,
    name: m.name,
    detail: `${dateLabel} ${fmtDate(m.date)}`,
    right: <AssignedCell row={m} />,
  }))
}

function PeriodDrawer({ division, window, grain, period, filters, onClose, onOpen }: {
  division: Division
  window: Window
  grain: Grain
  period: string
  filters: ReportFilters
  onClose: () => void
  onOpen: (id: string) => void
}) {
  const { data, error, isLoading } = useFlowMembers(division, window, grain, period, filters)
  const d = data?.data
  const sections: ListSection[] = d ? [
    { key: "reactivated", label: "Came back", color: COLORS.reactivated, rows: memberRows(d.reactivated, "Returned") },
    { key: "lost", label: "Lost", color: COLORS.lost, rows: memberRows(d.lost, "Last load") },
    { key: "new", label: "New", color: COLORS.new, rows: memberRows(d.new, "First load") },
  ] : []
  return (
    <ListDrawer
      title={period}
      subtitle="Customers behind this period's bars"
      sections={sections}
      loading={isLoading || !d}
      error={error}
      onClose={onClose}
      onOpen={onOpen}
    />
  )
}

export function TrendPanel({ division, window, filters, onOpen }: {
  division: Division
  window: Window
  filters: ReportFilters
  onOpen: (id: string) => void
}) {
  const [grain, setGrain] = useState<Grain>("quarter")
  const [picked, setPicked] = useState<string | null>(null)
  const { data, error, isLoading } = useTrend(division, window, grain, filters)
  const rows = useMemo(() => data?.data ?? [], [data])
  const years = useMemo(() => Array.from(new Set(rows.map((r) => yearOf(r.period)))), [rows])
  const [range, setRange] = useState<[number, number] | null>(null)
  const [from, to] = range ?? [years[0] ?? 2016, years[years.length - 1] ?? 2026]
  const shown = rows.filter((r) => yearOf(r.period) >= from && yearOf(r.period) <= to)

  const controls = (
    <div className="flex flex-wrap items-center gap-3">
      <Segmented value={grain} options={GRAINS} onChange={setGrain} />
      {years.length > 0 && <YearRange years={years} from={from} to={to} onChange={(a, b) => setRange([a, b])} />}
    </div>
  )
  if (error) return <ErrorBox error={error} />
  return (
    <div className="space-y-4">
      <Card
        title="Customer flow"
        description="Tracks new, returning, and lost customers over time, alongside the customer base and customers shipping in each period."
        howTo={`Bars show new (green), returning after ${window}+ inactive days (blue), and lost customers (red). Lines show the customer base and customers shipping that period. Bars use the left axis; lines use the right. Click a period to see its customers.`}
        right={controls}
      >
        {isLoading ? <Loading height="h-80" /> : <FlowChart rows={shown} onPick={setPicked} />}
      </Card>
      <Card
        title="Revenue, profit and profit per shipping customer"
        description="Tracks revenue, profit, and average profit per shipping customer over time."
        howTo="Gray bars show revenue; green bars show profit (left axis). The line shows average profit per shipping customer (right axis)."
      >
        {isLoading ? <Loading height="h-64" /> : <ValueChart rows={shown} />}
      </Card>
      <Card title="By period">{isLoading ? <Loading /> : <TrendTable rows={shown} />}</Card>
      {picked && (
        <PeriodDrawer
          division={division}
          window={window}
          grain={grain}
          period={picked}
          filters={filters}
          onClose={() => setPicked(null)}
          onOpen={onOpen}
        />
      )}
    </div>
  )
}
