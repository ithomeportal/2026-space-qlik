"use client"

import { useMemo } from "react"
import {
  useAttritionSummary,
  type AttritionFilters,
  type CountBlock,
  type DiffPair,
  type MetricBlock,
} from "@/lib/attrition-wow-api"
import type { CeoFilters } from "@/lib/ceo-api"
import { PivotsTab } from "../../attrition-wow/tabs/PivotsTab"
import { AttritionErrorBanner } from "../../attrition-wow/ErrorBanner"
import {
  fmtCount,
  fmtCount1,
  fmtPct,
  fmtSignedCount,
  fmtSignedPct,
  fmtSignedUsd,
  fmtUsd,
  fmtWeekRange,
} from "../../attrition-wow/format"

// Column tints mirror the Attrition-WoW Overview table so the duplicated
// table reads identically (Bruno 2026-06-30, Requests 3 & 4).
const L8W_BG = "bg-[#FFFBEB]"
const L2W_BG = "bg-[#EFF6FF]"
const LW_BG = "bg-[#ECFDF5]"

const CORP_ATTR_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"]
const ALL_ATTR_TEAMS = [...CORP_ATTR_TEAMS, "TEAM-DFW"]

// Map the CEO Executive filter scope onto the Attrition-WoW team taxonomy.
//   CORP + TEAMn          -> teams=[TEAMn]
//   DFW  + TMn            -> teams=[TEAM-DFW], sub_team=TMn (narrows the team col)
//   CORP / DFW (no team)  -> all CORP teams / TEAM-DFW
//   no division/team      -> every team
// The attrition windows are weekly trailing (L8W/LW), so the CEO date range
// intentionally does not apply here — only Division/Team/Customer do.
function ceoToAttrition(f: CeoFilters): AttritionFilters {
  const customer = f.customer || undefined
  // Bruno 2026-07-01 Request 3: the global Contract/Spot filter applies here too.
  const contract = f.contractType || undefined
  const t = f.team
  if (t) {
    if (t.startsWith("TM")) return { teams: ["TEAM-DFW"], sub_team: t, customer, contract }
    return { teams: [t], customer, contract }
  }
  if (f.division === "CORP") return { teams: CORP_ATTR_TEAMS, customer, contract }
  if (f.division === "DFW") return { teams: ["TEAM-DFW"], customer, contract }
  return { teams: ALL_ATTR_TEAMS, customer, contract }
}

export function Attrition({ filters }: { filters: CeoFilters }) {
  const af = useMemo(() => ceoToAttrition(filters), [filters])
  const entityLabel = "Customer"

  const { data: summaryRes, isLoading: loadingSummary, error: summaryErr } =
    useAttritionSummary(af)
  const s = summaryRes?.data

  return (
    <div className="space-y-8">
      <AttritionErrorBanner errors={[summaryErr]} label="Attrition" />

      {/* Window labels — same trailing windows the cards/table aggregate. */}
      {s && (
        <div className="flex flex-wrap gap-3 text-[11px] text-[#6B7280]">
          <Badge label="Last 8 Weeks" range={s.windows.l8w} />
          <Badge label="Last Week" range={s.windows.lw} />
          <Badge label="Last 2 Weeks" range={s.windows.l2w} />
        </div>
      )}

      {/* Request 3: Lane Attrition + Customer Attrition containers. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ActiveCard
          title="Lane Attrition"
          accent="text-[#1B3A5C]"
          loading={loadingSummary}
          block={s?.active_lanes}
        />
        <ActiveCard
          title={`${entityLabel} Attrition`}
          accent="text-[#1B3A5C]"
          loading={loadingSummary}
          block={s?.active_customers}
        />
      </div>

      {/* Request 3: the metric table (# Loads, $ Revenue, $ Profit, % Margin,
          $/Load) across L8W / L2W / LW. */}
      <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-[#F9FAFB] text-[10px] text-[#6B7280]">
            <tr>
              <th className="w-32 px-3 py-2 text-left font-semibold uppercase tracking-wider">
                Metric
              </th>
              <th className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${L8W_BG}`}>
                L8W avg
              </th>
              <th className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${L2W_BG}`}>
                L2W avg
              </th>
              <th className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${L2W_BG}`}>
                Δ (L2W vs L8W)
              </th>
              <th className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${L2W_BG}`}>
                % (L2W vs L8W)
              </th>
              <th className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${LW_BG}`}>
                Last Week
              </th>
              <th className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${LW_BG}`}>
                Δ (LW vs L8W)
              </th>
              <th className={`px-3 py-2 text-right font-semibold uppercase tracking-wider ${LW_BG}`}>
                % (LW vs L8W)
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {/* Bruno PDF 2026-07-22 R3: L8W AVG / L2W AVG to one decimal for
                #Loads only (both are genuine /8 and /2 averages server-side). */}
            <MetricRow label="# Loads" loading={loadingSummary} block={s?.loads} fmt={fmtCount} avgFmt={fmtCount1} isCount />
            <MetricRow label="$ Revenue" loading={loadingSummary} block={s?.revenue} fmt={fmtUsd} />
            <MetricRow label="$ Profit" loading={loadingSummary} block={s?.profit} fmt={fmtUsd} />
            <MetricRow label="% Margin" loading={loadingSummary} block={s?.margin_pct} fmt={fmtPct} isPct />
            <MetricRow label="$ Profit per Load" loading={loadingSummary} block={s?.profit_per_load} fmt={fmtUsd} />
          </tbody>
        </table>
      </div>

      {/* Request 4: Performance Trends pivot table (all metrics + views),
          Difference column sorted ascending by default. */}
      <div>
        <h3 className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-[#6B7280]">
          Performance Trends
        </h3>
        <PivotsTab
          filters={af}
          entityLabel={entityLabel}
          defaultDim="customer"
          defaultSortKey="diff"
          defaultSortDir="asc"
        />
      </div>
    </div>
  )
}

function Badge({ label, range }: { label: string; range: { start: string; end: string } }) {
  return (
    <span className="rounded-full bg-[#F3F4F6] px-3 py-1 text-[#374151]">
      <strong>{label}:</strong>&nbsp;{fmtWeekRange(range.start, range.end)}
    </span>
  )
}

function ActiveCard({
  title,
  accent,
  loading,
  block,
}: {
  title: string
  accent: string
  loading: boolean
  block: CountBlock | undefined
}) {
  const sd = fmtSignedCount(block?.diff ?? null)
  const sp = fmtSignedPct(block?.pct ?? null)
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="text-[11px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {title}
      </div>
      <div className="mt-3 grid grid-cols-4 gap-2">
        {/* Bruno PDF 2026-07-22 R1+R2: L8W to one decimal on BOTH cards (this
            ActiveCard renders twice — "Lane Attrition" and "<entity> Attrition").
            Both are now genuine per-week averages over the 8-week window, so
            the decimal carries real information: customer L8W stopped being a
            union-distinct integer on 2026-08-03 (it has to equal the "Weekly
            Customers" chart's 8W-Avg line — see the l8w_weekly CTE in
            attrition_wow.py). LW stays integer, matching attrition-wow. */}
        <CountCell label="L8W" value={loading ? "—" : fmtCount1(block?.l8w)} accent={accent} />
        <CountCell label="LW" value={loading ? "—" : fmtCount(block?.lw)} accent={accent} />
        <CountCell label="Δ (LW − L8W)" value={loading ? "—" : sd.text} accent={sd.className} />
        {/* Bruno 2026-07-01 Attrition Request 2: "% Δ" → "% Attrition" (this report only). */}
        <CountCell label="% Attrition" value={loading ? "—" : sp.text} accent={sp.className} />
      </div>
    </div>
  )
}

function CountCell({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div className="rounded-md border border-[#F3F4F6] bg-[#F9FAFB] p-2">
      <div className="text-[9px] font-semibold uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className={`mt-1 text-xl font-semibold ${accent}`}>{value}</div>
    </div>
  )
}

function MetricRow({
  label,
  loading,
  block,
  fmt,
  avgFmt,
  isCount,
  isPct,
}: {
  label: string
  loading: boolean
  block: MetricBlock | undefined
  fmt: (v: number | null | undefined) => string
  /** Formatter for the L8W AVG / L2W AVG cells only. Defaults to `fmt`, which
   *  is what keeps the $ Revenue / $ Profit / % Margin / $ Profit-per-Load rows
   *  unchanged — they pass no `avgFmt`. Mirrors attrition-wow's OverviewTab. */
  avgFmt?: (v: number | null | undefined) => string
  isCount?: boolean
  isPct?: boolean
}) {
  const cell = (v: number | null | undefined) => (loading ? "—" : fmt(v))
  const cellAvg = (v: number | null | undefined) => (loading ? "—" : (avgFmt ?? fmt)(v))
  const renderDiff = (d: DiffPair | undefined) => {
    if (!d) return { abs: "—", pct: "—", absCls: "text-[#6B7280]", pctCls: "text-[#6B7280]" }
    if (isPct) {
      const absText =
        d.diff === null ? "—" : `${d.diff >= 0 ? "+" : ""}${(d.diff * 100).toFixed(2)}pp`
      const cls =
        d.diff === null
          ? "text-[#6B7280]"
          : d.diff > 0
            ? "text-[#15803D]"
            : d.diff < 0
              ? "text-[#DC2626]"
              : "text-[#B45309]"
      const sp = fmtSignedPct(d.pct)
      return { abs: absText, pct: sp.text, absCls: cls, pctCls: sp.className }
    }
    const sa = isCount ? fmtSignedCount(d.diff) : fmtSignedUsd(d.diff)
    const sp = fmtSignedPct(d.pct)
    return { abs: sa.text, pct: sp.text, absCls: sa.className, pctCls: sp.className }
  }
  const lwDiff = renderDiff(block?.diff_lw_vs_l8w)
  const l2wDiff = renderDiff(block?.diff_l2w_vs_l8w)

  return (
    <tr>
      <td className="px-3 py-2.5 text-left text-xs font-semibold text-[#374151]">{label}</td>
      <td className={`px-3 py-2.5 text-right font-mono text-base text-[#111827] ${L8W_BG}`}>
        {cellAvg(block?.l8w_avg)}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base text-[#111827] ${L2W_BG}`}>
        {cellAvg(block?.l2w_avg)}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base ${L2W_BG} ${l2wDiff.absCls}`}>
        {l2wDiff.abs}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base ${L2W_BG} ${l2wDiff.pctCls}`}>
        {l2wDiff.pct}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base text-[#111827] ${LW_BG}`}>
        {cell(block?.lw)}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base ${LW_BG} ${lwDiff.absCls}`}>
        {lwDiff.abs}
      </td>
      <td className={`px-3 py-2.5 text-right font-mono text-base ${LW_BG} ${lwDiff.pctCls}`}>
        {lwDiff.pct}
      </td>
    </tr>
  )
}
