"use client"

import { Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useXrayKpis,
  useXrayProjection,
  useXrayTrio,
  type XrayFilters,
  type XrayTrioRow,
} from "@/lib/xray-api"

interface Props {
  filters: XrayFilters
}

const PROFIT_GOAL_PER_TEAM = 55000

export function Overview({ filters }: Props) {
  const { data: kpiRes, isLoading: loadingKpis } = useXrayKpis(filters)
  const k = kpiRes?.data
  const trioFilter = { team: filters.team, customer: filters.customer }
  const { data: trioRes, isLoading: loadingTrio } = useXrayTrio(trioFilter)
  const { data: projRes, isLoading: loadingProj } = useXrayProjection(trioFilter)
  const p = projRes?.data
  const trio = trioRes?.data

  const goalTeams = filters.team ? 1 : 5
  const goalTotal = PROFIT_GOAL_PER_TEAM * goalTeams
  const goalPct = k && goalTotal ? (k.profit_tm / goalTotal) * 100 : 0

  return (
    <div className="space-y-6">
      {/* 6 Primary KPIs */}
      <section className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <Kpi label="# Loads" value={fmtCount(k?.loads)} tone="red" loading={loadingKpis} />
        <Kpi label="$ Revenue" value={fmtUsd(k?.revenue)} tone="blue" loading={loadingKpis} />
        <Kpi label="$ Profit" value={fmtUsd(k?.profit)} tone="yellow" loading={loadingKpis} />
        <Kpi label="Margin %" value={fmtPct(k?.margin_pct)} tone="purple" loading={loadingKpis} />
        <Kpi label="OTP %" value={fmtPct(k?.otp_pct)} tone="green" loading={loadingKpis} />
        <Kpi label="OTD %" value={fmtPct(k?.otd_pct)} tone="green" loading={loadingKpis} />
      </section>

      {/* Loss Loads + Profit-TM gauge + Savings trio */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-[#E5E7EB] bg-white p-4 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
            Loss Loads
          </div>
          <div className="mt-1 text-3xl font-semibold text-[#DC2626]">
            {loadingKpis ? <Loader2 className="h-6 w-6 animate-spin" /> : fmtCount(k?.loss_loads)}
          </div>
          <div className="text-xs text-[#6B7280]">Window: {k?.window.start} → {k?.window.end}</div>
        </div>

        <div className="rounded-lg border border-[#E5E7EB] bg-white p-4 shadow-sm">
          <div className="flex items-baseline justify-between">
            <div className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
              Profit — This Month
            </div>
            <div className="text-xs text-[#6B7280]">Goal: {fmtUsd(goalTotal)}</div>
          </div>
          <div className="mt-1 text-2xl font-semibold text-[#D97706]">{fmtUsd(k?.profit_tm)}</div>
          <div className="mt-2 h-2 w-full rounded-full bg-[#F3F4F6]">
            <div
              className="h-2 rounded-full bg-[#D97706] transition-all"
              style={{ width: `${Math.max(0, Math.min(100, goalPct))}%` }}
            />
          </div>
          <div className="mt-1 text-xs text-[#6B7280]">{fmtPct(goalPct)} of goal</div>
        </div>

        <div className="grid grid-cols-3 gap-2 rounded-lg border border-[#E5E7EB] bg-white p-4 shadow-sm">
          <MiniKpi label="Total Savings" value={fmtUsd(k?.total_savings)} tone="positive" />
          <MiniKpi label="Total Overpay" value={fmtUsd(k?.total_overpay)} tone="negative" />
          <MiniKpi
            label="Net Variance"
            value={fmtUsd(k?.net_variance)}
            tone={k && k.net_variance >= 0 ? "positive" : "negative"}
          />
        </div>
      </section>

      {/* Trio tables — Yesterday / This Week / This Month */}
      <section className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <TrioTable
          title="Yesterday"
          subtitle={trio?.yesterday ? `${trio.yesterday.from}` : ""}
          totals={trio?.yesterday.totals ?? null}
          rows={trio?.yesterday.teams ?? []}
          tone="red"
          loading={loadingTrio}
        />
        <TrioTable
          title="This Week"
          subtitle={trio ? `${trio.week.from} → ${trio.week.to}` : ""}
          totals={trio?.week.totals ?? null}
          rows={trio?.week.teams ?? []}
          tone="green"
          loading={loadingTrio}
        />
        <TrioTable
          title="This Month"
          subtitle={trio ? `${trio.month.from} → ${trio.month.to}` : ""}
          totals={trio?.month.totals ?? null}
          rows={trio?.month.teams ?? []}
          tone="yellow"
          loading={loadingTrio}
        />
      </section>

      {/* Projection KPIs */}
      <section>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
          Projection (current month, rolling)
        </h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <MiniKpi label="Total Customers" value={fmtCount(p?.total_customers)} loading={loadingProj} />
          <MiniKpi label="Total Lanes" value={fmtCount(p?.total_lanes)} loading={loadingProj} />
          <MiniKpi label="AVG Vol × Day" value={fmtCount(p?.avg_vol_day)} loading={loadingProj} />
          <MiniKpi label="AVG Vol × Week" value={fmtCount(p?.avg_vol_week)} loading={loadingProj} />
          <MiniKpi label="Projected Vol (Month)" value={fmtCount(p?.projected_vol_month)} loading={loadingProj} />
          <MiniKpi label="AVG Profit × Day" value={fmtUsd(p?.avg_profit_day)} loading={loadingProj} />
          <MiniKpi label="AVG Profit × Week" value={fmtUsd(p?.avg_profit_week)} loading={loadingProj} />
          <MiniKpi label="Projected Profit (Month)" value={fmtUsd(p?.projected_profit_month)} loading={loadingProj} />
          <MiniKpi label="Past Days" value={fmtCount(p?.past_days)} tone="negative" />
          <MiniKpi label="Pending Days" value={fmtCount(p?.pending_days)} tone="positive" />
        </div>
      </section>
    </div>
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
    <div className={`rounded-lg border-2 ${KPI_TONES[tone]} bg-white p-3 text-center shadow-sm`}>
      <div className="text-xs uppercase tracking-wider text-[#6B7280]">{label}</div>
      <div className="mt-1 text-2xl font-bold tabular-nums">
        {loading ? <Loader2 className="mx-auto h-5 w-5 animate-spin" /> : value}
      </div>
    </div>
  )
}

function MiniKpi({
  label,
  value,
  tone,
  loading,
}: {
  label: string
  value: string
  tone?: "positive" | "negative"
  loading?: boolean
}) {
  const color = tone === "positive" ? "text-[#16A34A]" : tone === "negative" ? "text-[#DC2626]" : "text-[#1B3A5C]"
  return (
    <div className="rounded-md border border-[#E5E7EB] bg-white px-3 py-2 shadow-sm">
      <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">{label}</div>
      <div className={`text-lg font-semibold tabular-nums ${color}`}>
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : value}
      </div>
    </div>
  )
}

function TrioTable({
  title,
  subtitle,
  totals,
  rows,
  tone,
  loading,
}: {
  title: string
  subtitle: string
  totals: XrayTrioRow | null
  rows: XrayTrioRow[]
  tone: "red" | "green" | "yellow"
  loading?: boolean
}) {
  const headerBg = tone === "red" ? "bg-[#FEE2E2]" : tone === "green" ? "bg-[#D1FAE5]" : "bg-[#FEF3C7]"
  const totalsBg = tone === "red" ? "bg-[#FECACA]" : tone === "green" ? "bg-[#A7F3D0]" : "bg-[#FDE68A]"

  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className={`${headerBg} px-3 py-2`}>
        <div className="text-sm font-semibold text-[#111827]">{title}</div>
        <div className="text-[10px] text-[#6B7280]">{subtitle}</div>
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <table className="w-full text-[11px] tabular-nums">
          <thead className={`${headerBg} text-[#6B7280]`}>
            <tr>
              <th className="px-2 py-1 text-left">Team</th>
              <th className="px-1 py-1 text-right">Vol</th>
              <th className="px-1 py-1 text-right">Rev</th>
              <th className="px-1 py-1 text-right">Prof</th>
              <th className="px-1 py-1 text-right">M%</th>
              <th className="px-1 py-1 text-right">OTP%</th>
              <th className="px-1 py-1 text-right">OTD%</th>
              <th className="px-1 py-1 text-right">TU</th>
              <th className="px-1 py-1 text-right">R/L</th>
              <th className="px-1 py-1 text-right">P/L</th>
            </tr>
          </thead>
          <tbody>
            {totals && (
              <tr className={`${totalsBg} font-semibold`}>
                <td className="px-2 py-1">Totals</td>
                <td className="px-1 py-1 text-right">{fmtCount(totals.vol)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(totals.rev)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(totals.prof)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(totals.m_pct ?? 0)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(totals.otp_pct ?? 0)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(totals.otd_pct ?? 0)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(totals.tu)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(totals.r_per_l)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(totals.p_per_l)}</td>
              </tr>
            )}
            {rows.map((r) => (
              <tr key={r.team} className="border-t border-[#F3F4F6]">
                <td className="px-2 py-1">{r.team}</td>
                <td className="px-1 py-1 text-right">{fmtCount(r.vol)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(r.rev)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(r.prof)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(r.m_pct ?? 0)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(r.otp_pct ?? 0)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(r.otd_pct ?? 0)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(r.tu)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(r.r_per_l)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(r.p_per_l)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
