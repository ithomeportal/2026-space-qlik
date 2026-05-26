"use client"

import { Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useCeoOverview,
  type CeoAtpRow,
  type CeoFilters,
  type CeoTeamRow,
} from "@/lib/ceo-api"
import { CeoErrorBanner } from "../ErrorBanner"
import { marginCellClass } from "../margin-color"

interface Props {
  filters: CeoFilters
}

const PROFIT_GOAL_PER_TEAM = 55000

export function Overview({ filters }: Props) {
  const { data, isLoading, error, dataUpdatedAt } = useCeoOverview(filters)
  const d = data?.data

  const goalTeams = filters.team ? 1 : 6
  const goalTotal = PROFIT_GOAL_PER_TEAM * goalTeams
  const goalPct = d && goalTotal ? (d.profit_tm / goalTotal) * 100 : 0

  // Bruno R7 (2026-05-26): surface when the report data last refreshed.
  const refreshedLabel =
    dataUpdatedAt > 0
      ? new Date(dataUpdatedAt).toLocaleString("en-US", {
          month: "short",
          day: "numeric",
          year: "numeric",
          hour: "numeric",
          minute: "2-digit",
        })
      : "—"

  return (
    <div className="space-y-6">
      <CeoErrorBanner label="Overview" errors={[error]} />

      <div className="flex justify-end text-xs text-[#6B7280]">
        Last auto-refreshed: <span className="ml-1 font-medium text-[#374151]">{refreshedLabel}</span>
      </div>

      {/* 6 KPIs — enlarged per Bruno R7. Sized to leave room for a 7th element. */}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6 xl:grid-cols-7">
        <Kpi label="Revenue" value={fmtUsd(d?.kpis.revenue)} tone="blue" loading={isLoading} />
        <Kpi label="Profit" value={fmtUsd(d?.kpis.profit)} tone="yellow" loading={isLoading} />
        <Kpi label="Loads" value={fmtCount(d?.kpis.loads)} tone="red" loading={isLoading} />
        <Kpi label="Margin %" value={fmtPct(d?.kpis.margin_pct)} tone="purple" loading={isLoading} />
        <Kpi label="AVG R / L" value={fmtUsd(d?.kpis.avg_r_per_l)} tone="blue" loading={isLoading} />
        <Kpi label="AVG P / L" value={fmtUsd(d?.kpis.avg_p_per_l)} tone="yellow" loading={isLoading} />
      </section>

      {/* Summary by Team + All Teams Performance side-by-side */}
      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <SummaryByTeam rows={d?.summary_by_team ?? []} loading={isLoading} />
        <AllTeamsPerformance rows={d?.all_teams_performance ?? []} loading={isLoading} />
      </section>

      {/* Profit-TM gauge — moved to end per Bruno feedback (2026-05-07) */}
      <section className="rounded-lg border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="flex items-baseline justify-between">
          <div className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
            Profit — This Month (TM)
          </div>
          <div className="text-xs text-[#6B7280]">Goal: {fmtUsd(goalTotal)}</div>
        </div>
        <div className="mt-1 text-3xl font-semibold text-[#D97706]">{fmtUsd(d?.profit_tm)}</div>
        <div className="mt-2 h-3 w-full rounded-full bg-[#F3F4F6]">
          <div
            className="h-3 rounded-full bg-[#D97706] transition-all"
            style={{ width: `${Math.max(0, Math.min(100, goalPct))}%` }}
          />
        </div>
        <div className="mt-1 text-xs text-[#6B7280]">
          {fmtPct(goalPct)} of goal
          {filters.team ? ` · Team: ${filters.team}` : " · All teams"}
        </div>
      </section>
    </div>
  )
}

function SummaryByTeam({ rows, loading }: { rows: CeoTeamRow[]; loading?: boolean }) {
  const tot = rows.reduce(
    (acc, r) => ({
      cust: acc.cust + (r.cust ?? 0),
      loads: acc.loads + (r.loads ?? 0),
      revenue: acc.revenue + (r.revenue ?? 0),
      profit: acc.profit + (r.profit ?? 0),
    }),
    { cust: 0, loads: 0, revenue: 0, profit: 0 },
  )
  const margin = tot.revenue > 0 ? (tot.profit / tot.revenue) * 100 : 0
  const rpl = tot.loads > 0 ? tot.revenue / tot.loads : 0
  const ppl = tot.loads > 0 ? tot.profit / tot.loads : 0

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="bg-[#D1FAE5] px-3 py-2 text-sm font-semibold text-[#065F46]">
        Summary by Team
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-[10.5px] tabular-nums">
            <thead className="bg-[#D1FAE5] text-[#065F46]">
              <tr>
                <th className="px-2 py-1 text-left">Team</th>
                <th className="px-1 py-1 text-right"># Cust</th>
                <th className="px-1 py-1 text-right">Loads</th>
                <th className="px-1 py-1 text-right">Revenue</th>
                <th className="px-1 py-1 text-right">Profit</th>
                <th className="px-1 py-1 text-right">Margin %</th>
                <th className="px-1 py-1 text-right">AVG R / L</th>
                <th className="px-1 py-1 text-right">AVG P / L</th>
              </tr>
            </thead>
            <tbody>
              <tr className="bg-[#A7F3D0] font-semibold">
                <td className="px-2 py-1">Totals</td>
                <td className="px-1 py-1 text-right">{fmtCount(tot.cust)}</td>
                <td className="px-1 py-1 text-right">{fmtCount(tot.loads)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.revenue)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.profit)}</td>
                <td className={`px-1 py-1 text-right ${marginCellClass(margin)}`}>{fmtPct(margin)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(rpl)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(ppl)}</td>
              </tr>
              {rows.map((r) => (
                <tr key={r.team} className="border-t border-[#F3F4F6]">
                  <td className="px-2 py-1">{r.team}</td>
                  <td className="px-1 py-1 text-right">{fmtCount(r.cust)}</td>
                  <td className="px-1 py-1 text-right">{fmtCount(r.loads)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.revenue)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.profit)}</td>
                  <td className={`px-1 py-1 text-right ${marginCellClass(r.margin_pct)}`}>{fmtPct(r.margin_pct)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.avg_r_per_l)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.avg_p_per_l)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function AllTeamsPerformance({ rows, loading }: { rows: CeoAtpRow[]; loading?: boolean }) {
  const tot = rows.reduce(
    (acc, r) => ({
      yd_loads: acc.yd_loads + (r.yd_loads ?? 0),
      yd_profit: acc.yd_profit + (r.yd_profit ?? 0),
      wk_loads: acc.wk_loads + (r.wk_loads ?? 0),
      wk_profit: acc.wk_profit + (r.wk_profit ?? 0),
      mo_loads: acc.mo_loads + (r.mo_loads ?? 0),
      mo_profit: acc.mo_profit + (r.mo_profit ?? 0),
    }),
    { yd_loads: 0, yd_profit: 0, wk_loads: 0, wk_profit: 0, mo_loads: 0, mo_profit: 0 },
  )
  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="bg-[#DBEAFE] px-3 py-2 text-sm font-semibold text-[#1E3A8A]">
        All Teams Performance <span className="text-xs font-normal text-[#6B7280]">· Yd / Wk / Mo — fixed windows</span>
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-[10.5px] tabular-nums">
            <thead className="bg-[#DBEAFE] text-[#1E3A8A]">
              <tr>
                <th className="px-2 py-1 text-left">Team</th>
                <th className="px-1 py-1 text-right">Yd # L</th>
                <th className="px-1 py-1 text-right">Yd $P</th>
                <th className="px-1 py-1 text-right">%M (Ye)</th>
                <th className="px-1 py-1 text-right">Wk # L</th>
                <th className="px-1 py-1 text-right">Wk $P</th>
                <th className="px-1 py-1 text-right">%M (We)</th>
                <th className="px-1 py-1 text-right">Mo # L</th>
                <th className="px-1 py-1 text-right">Mo $P</th>
                <th className="px-1 py-1 text-right">%M (Mo)</th>
                <th className="px-1 py-1 text-right">$P × #L</th>
              </tr>
            </thead>
            <tbody>
              <tr className="bg-[#BFDBFE] font-semibold">
                <td className="px-2 py-1">Totals</td>
                <td className="px-1 py-1 text-right">{fmtCount(tot.yd_loads)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.yd_profit)}</td>
                <td className="px-1 py-1 text-right">—</td>
                <td className="px-1 py-1 text-right">{fmtCount(tot.wk_loads)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.wk_profit)}</td>
                <td className="px-1 py-1 text-right">—</td>
                <td className="px-1 py-1 text-right">{fmtCount(tot.mo_loads)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.mo_profit)}</td>
                <td className="px-1 py-1 text-right">—</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.mo_loads ? tot.mo_profit / tot.mo_loads : 0)}</td>
              </tr>
              {rows.map((r) => (
                <tr key={r.team} className="border-t border-[#F3F4F6]">
                  <td className="px-2 py-1">{r.team}</td>
                  <td className="px-1 py-1 text-right">{fmtCount(r.yd_loads)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.yd_profit)}</td>
                  <td className="px-1 py-1 text-right">{fmtPct(r.yd_margin_pct)}</td>
                  <td className="px-1 py-1 text-right">{fmtCount(r.wk_loads)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.wk_profit)}</td>
                  <td className="px-1 py-1 text-right">{fmtPct(r.wk_margin_pct)}</td>
                  <td className="px-1 py-1 text-right">{fmtCount(r.mo_loads)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.mo_profit)}</td>
                  <td className="px-1 py-1 text-right">{fmtPct(r.mo_margin_pct)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.mo_p_per_l)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

const KPI_TONES: Record<string, string> = {
  red: "border-[#FCA5A5] text-[#DC2626]",
  blue: "border-[#93C5FD] text-[#2563EB]",
  yellow: "border-[#FCD34D] text-[#D97706]",
  purple: "border-[#D8B4FE] text-[#9333EA]",
  green: "border-[#86EFAC] text-[#16A34A]",
}

function Kpi({
  label,
  value,
  tone,
  loading,
}: {
  label: string
  value: string
  tone: keyof typeof KPI_TONES
  loading?: boolean
}) {
  return (
    <div className={`rounded-md border ${KPI_TONES[tone]} bg-white px-3 py-3 text-center shadow-sm`}>
      <div className="text-[11px] uppercase tracking-wider text-[#6B7280]">{label}</div>
      <div className="mt-1 text-xl font-bold tabular-nums leading-tight">
        {loading ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : value}
      </div>
    </div>
  )
}
