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
  useTrend,
  type Division,
  type Grain,
  type TrendRow,
  type Window,
} from "@/lib/customer-lifespan-api"
import { Card, ErrorBox, Loading, Segmented } from "./ui"

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

function FlowChart({ rows }: { rows: TrendRow[] }) {
  const data = rows.map((r) => ({ ...r, label: r.partial ? `${r.period}*` : r.period, lostNeg: -r.lost }))
  return (
    <div className="h-80">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} stackOffset="sign" margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} minTickGap={12} />
          <YAxis yAxisId="flow" tick={{ fontSize: 11 }} width={36} allowDecimals={false} />
          <YAxis yAxisId="stock" orientation="right" tick={{ fontSize: 11 }} width={36} allowDecimals={false} />
          <ReferenceLine yAxisId="flow" y={0} stroke="#9CA3AF" />
          <Tooltip
            formatter={(v, name) => [fmtInt(Math.abs(Number(v))), String(name)]}
            labelFormatter={(l) => `${l}${String(l).endsWith("*") ? " (in progress)" : ""}`}
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
          <Tooltip formatter={(v, name) => [fmtUsd(Number(v)), String(name)]} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar yAxisId="usd" dataKey="revenue" name="Revenue" fill={COLORS.revenue} />
          <Bar yAxisId="usd" dataKey="margin" name="Margin" fill={COLORS.margin} />
          <Line yAxisId="per" dataKey="margin_per_active" name="Margin per shipping customer" stroke={COLORS.navy} strokeWidth={2} dot={false} />
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
            <th className={th}>Revenue</th><th className={th}>Margin</th><th className={th}>Margin %</th>
            <th className={th}>Margin / customer</th>
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

export function TrendPanel({ division, window }: { division: Division; window: Window }) {
  const [grain, setGrain] = useState<Grain>("quarter")
  const { data, error, isLoading } = useTrend(division, window, grain)
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
        hint={`Bars: customers won (new), won back after more than ${window} quiet days, and lost (last load before a silence longer than ${window} days — counted only once the silence is confirmed). Lines: the customer base (load in the ${window} days to period end) and customers shipping in the period. * = period still in progress.`}
        right={controls}
      >
        {isLoading ? <Loading height="h-80" /> : <FlowChart rows={shown} />}
      </Card>
      <Card title="Revenue, margin and margin per shipping customer">
        {isLoading ? <Loading height="h-64" /> : <ValueChart rows={shown} />}
      </Card>
      <Card title="By period">{isLoading ? <Loading /> : <TrendTable rows={shown} />}</Card>
    </div>
  )
}
