"use client"

import { useState } from "react"
import {
  fmtInt,
  fmtMo,
  fmtPct,
  fmtUsd,
  fmtUsdCompact,
  useCohorts,
  yearLabel,
  type CohortRow,
  type Division,
  type ReportFilters,
  type Window,
} from "@/lib/customer-lifespan-api"
import { Card, ErrorBox, Loading, Segmented } from "./ui"

const UNITS = [
  { k: "pct", label: "By %" },
  { k: "count", label: "By #" },
] as const
type Unit = (typeof UNITS)[number]["k"]

/** White → navy by share; text flips to white on the dark half. */
function heat(pct: number | null): { background: string; color: string } {
  if (pct === null) return { background: "transparent", color: "#9CA3AF" }
  const a = Math.min(Math.max(pct / 100, 0), 1)
  return { background: `rgba(27, 58, 92, ${0.08 + a * 0.85})`, color: a > 0.45 ? "#FFFFFF" : "#111827" }
}

function RetentionHeatmap({ rows, unit, asOf }: { rows: CohortRow[]; unit: Unit; asOf: string }) {
  const years = Array.from(new Set(rows.flatMap((r) => r.retention.map((x) => x.year)))).sort()
  return (
    <div className="overflow-x-auto">
      <table className="text-[11px]">
        <thead>
          <tr className="text-[#6B7280]">
            <th className="px-2 py-1 text-left font-medium">First load</th>
            <th className="px-2 py-1 text-right font-medium">New</th>
            {years.map((y) => <th key={y} className="w-14 whitespace-nowrap px-1 py-1 text-center font-medium">{yearLabel(y, asOf)}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const by = new Map(r.retention.map((x) => [x.year, x]))
            return (
              <tr key={r.cohort}>
                <td className="whitespace-nowrap px-2 py-0.5 font-medium text-[#111827]">{yearLabel(r.cohort, asOf)}</td>
                <td className="px-2 py-0.5 text-right tabular-nums">{fmtInt(r.new)}</td>
                {years.map((y) => {
                  const cell = by.get(y)
                  return (
                    <td key={y} className="p-0.5">
                      {cell ? (
                        <div
                          className="rounded px-1 py-1 text-center tabular-nums"
                          style={heat(cell.pct)}
                          title={`${r.cohort} cohort: ${cell.customers} of ${r.new} customers shipped in ${y}`}
                        >
                          {unit === "pct" ? fmtPct(cell.pct, 0) : fmtInt(cell.customers)}
                        </div>
                      ) : null}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function CohortTable({ rows, asOf }: { rows: CohortRow[]; asOf: string }) {
  const th = "px-2 py-1.5 text-right font-medium"
  const td = "px-2 py-1 text-right tabular-nums"
  const total = rows.reduce((a, r) => ({
    new: a.new + r.new,
    base: a.base + r.base_now,
    atRisk: a.atRisk + r.at_risk_now,
    active: a.active + r.active_now,
    lost: a.lost + r.lost,
  }), { new: 0, base: 0, atRisk: 0, active: 0, lost: 0 })
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-[#F9FAFB] text-[#6B7280]">
          <tr>
            <th className="px-2 py-1.5 text-left font-medium">First load</th>
            <th className={th}>New</th><th className={th}>Still in base</th><th className={th}>At Risk</th><th className={th}>Active</th>
            <th className={th}>Lost</th><th className={th}>Retained</th>
            <th className={th}>Avg lifespan · base</th><th className={th}>Avg lifespan · lost</th>
            <th className={th}>Lifetime revenue</th><th className={th}>Lifetime Profit ($)</th>
            <th className={th}>Avg. Profit ($) per active month</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.cohort} className="border-t border-[#F3F4F6]">
              <td className="whitespace-nowrap px-2 py-1 font-medium">{yearLabel(r.cohort, asOf)}</td>
              <td className={td}>{fmtInt(r.new)}</td>
              <td className={td}>{fmtInt(r.base_now)}</td>
              <td className={`${td} text-[#D97706]`}>{fmtInt(r.at_risk_now)}</td>
              <td className={`${td} text-[#059669]`}>{fmtInt(r.active_now)}</td>
              <td className={`${td} text-[#DC2626]`}>{fmtInt(r.lost)}</td>
              <td className={td}>{fmtPct(r.retained_pct, 0)}</td>
              <td className={td}>{fmtMo(r.avg_lifespan_base)}</td>
              <td className={td}>{fmtMo(r.avg_lifespan_lost)}</td>
              <td className={td}>{fmtUsdCompact(r.revenue)}</td>
              <td className={td}>{fmtUsdCompact(r.margin)}</td>
              <td className={td}>{fmtUsd(r.avg_monthly_margin)}</td>
            </tr>
          ))}
          <tr className="border-t-2 border-[#E5E7EB] font-semibold">
            <td className="px-2 py-1">Total</td>
            <td className={td}>{fmtInt(total.new)}</td>
            <td className={td}>{fmtInt(total.base)}</td>
            <td className={td}>{fmtInt(total.atRisk)}</td>
            <td className={td}>{fmtInt(total.active)}</td>
            <td className={td}>{fmtInt(total.lost)}</td>
            <td className={td}>{fmtPct(total.new ? (total.base / total.new) * 100 : null, 0)}</td>
            <td colSpan={5} />
          </tr>
        </tbody>
      </table>
    </div>
  )
}

export function CohortsPanel({ division, window, filters }: {
  division: Division
  window: Window
  filters: ReportFilters
}) {
  const [unit, setUnit] = useState<Unit>("pct")
  const { data, error, isLoading } = useCohorts(division, window, filters)
  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) return <Loading />
  const rows = data.data
  return (
    <div className="space-y-4">
      <Card
        title="Retention by first-load year"
        description="Shows customer retention over time, grouped by first-load year."
        howToLabel="How to read this report"
        howTo="Each row is the number of new customers by the year they first shipped. Read left to right to see how many kept shipping each year. The diagonal is always 100% representing the total of new customers that year."
        right={<Segmented value={unit} options={UNITS} onChange={setUnit} />}
      >
        <RetentionHeatmap rows={rows} unit={unit} asOf={data.meta.as_of} />
      </Card>
      <Card
        title="Customers by first-load year: active, lost and value"
        hint={`Still in base = a load in the last ${window} days. Lifespan = months between the first and the last month with a load (a one-month customer is 0). "Avg. Profit ($) per active month" averages each customer's profit per month in which it shipped.`}
      >
        <CohortTable rows={rows} asOf={data.meta.as_of} />
      </Card>
    </div>
  )
}
