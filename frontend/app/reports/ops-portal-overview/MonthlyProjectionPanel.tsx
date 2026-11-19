"use client"

import { useState } from "react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtUsdSigned,
  useOppTeamProjection,
  useOppTeamProjectionHistory,
  useOppTeamProjectionWeekly,
  type OppFilters,
  type OppProjectionHistory,
  type OppTeamProjectionWeek,
} from "@/lib/ops-portal-overview-api"
import { ProjectionTrendModal } from "./ProjectionTrendModal"
import { MetricMatrixModal, type MatrixCell, type MatrixRow } from "./MetricMatrixModal"
import { InfoButtons, PanelCard, Row, signCls } from "./PanelShared"
import { InfoToolbar, infoSubtitle, useInfoState } from "./InfoControls"

// Moved verbatim out of SidePanels.tsx (layout 2026-10-28) — one panel per file.

// ---------------------------------------------------------------------------
// §6 — Team Monthly Projection
// ---------------------------------------------------------------------------

export function TeamProjection({ filters, lockedTeam }: { filters: OppFilters; lockedTeam?: string }) {
  const cf = { team: filters.team, customers: filters.customers, loadType: filters.loadType, lanes: filters.lanes, excludeLanes: filters.excludeLanes }
  const { data, isLoading, error } = useOppTeamProjection(cf)
  const v = data?.data
  // Ops Portal Updates PDF (2026-11-18) R3: ONE "Info" modal (was Week + Team).
  const [infoOpen, setInfoOpen] = useState(false)
  // Request 2026-08-25: the month's high / low / variation for Proj. Profit.
  const [trendOpen, setTrendOpen] = useState(false)
  const { data: histData } = useOppTeamProjectionHistory(cf)
  const hist = histData?.data
  const cur = hist?.tracked ? hist.current_month : null
  return (
    <PanelCard
      title="Monthly Projection"
      icon="🎯"
      loading={isLoading}
      error={error}
      action={
        <InfoButtons onInfo={() => setInfoOpen(true)} onTrend={() => setTrendOpen(true)} />
      }
    >
      <table className="w-full text-xs">
        <tbody>
          {/* "(last 14 days)" is the CALENDAR span of the window: 12 day-slots
              ending yesterday, where Saturday + Sunday together are ONE slot
              (request 2026-10-20 — Sundays used to be dropped). ÷ 12, never
              ÷ 14. The Date filter does not apply. */}
          <Row label="Avg. Vol. x Day (last 14 days)"  value={v ? fmtCount(v.avg_vol_day)  : "—"} />
          <Row label="Avg. Rev. x Day (last 14 days)" value={v ? fmtUsd(v.avg_rev_day)    : "—"} />
          <Row label="Avg. Prof. x Day (last 14 days)" value={v ? fmtUsd(v.avg_prof_day)  : "—"} signed numeric={v?.avg_prof_day ?? 0} />
          <tr><td colSpan={2} className="py-1"></td></tr>
          <Row label="Pending Days"    value={v ? fmtCount(v.pending_workdays) : "—"} />
          {/* Bruno (PDF 2026-08-31) R4: month-start → end of YESTERDAY.
              Since 2026-10-20 the projection uses the same close, so all three
              reconcile on screen: Avg x Day × Pending Days + (MTD) = Proj. —
              and the panel no longer moves during the day (backend _metrics.py). */}
          <Row label="Volume (MTD)"    value={v ? fmtCount(v.mtd_volume)   : "—"} />
          <Row label="Revenue (MTD)"   value={v ? fmtUsd(v.mtd_revenue)    : "—"} />
          <Row label="Profit (MTD)"    value={v ? fmtUsd(v.mtd_profit)     : "—"} signed numeric={v?.mtd_profit ?? 0} />
          <tr><td colSpan={2} className="py-1"></td></tr>
          <Row label="Proj. Volume"    value={v ? fmtCount(v.proj_volume)  : "—"} />
          <Row label="Proj. Revenue"   value={v ? fmtUsd(v.proj_revenue)   : "—"} />
          <Row label="Proj. Profit"    value={v ? fmtUsd(v.proj_profit)    : "—"} signed numeric={v?.proj_profit ?? 0} />
          {cur && cur.high !== null && cur.low !== null && cur.days > 1 && (
            <ProjProfitTicker stats={cur} onOpen={() => setTrendOpen(true)} />
          )}
          <Row label="Proj. Margin P %" value={v ? fmtPct(v.proj_margin_pct) : "—"} signed numeric={v?.proj_margin_pct ?? 0} />
          <Row label="Proj. Rev. x L." value={v ? fmtUsd(v.proj_rev_x_l)   : "—"} />
          <Row label="Proj. Prf. X L." value={v ? fmtUsd(v.proj_prof_x_l)  : "—"} signed numeric={v?.proj_prof_x_l ?? 0} />
          <Row label="Proj. Team Ut."  value={v ? fmtPct(v.proj_team_ut)   : "—"} />
        </tbody>
      </table>
      <p className="mt-2 text-[10px] leading-snug text-[#6B7280]">
        Actuals as of yesterday&apos;s close (CST) — fixed all day. Avg x Day = last 12 working
        days ÷ 12 (Sat + Sun = 1 day). Proj. = Avg x Day × Pending Days + MTD.
      </p>
      {infoOpen && (
        <ProjectionInfoModal filters={filters} lockedTeam={lockedTeam} onClose={() => setInfoOpen(false)} />
      )}
      {trendOpen && <ProjectionTrendModal filters={filters} onClose={() => setTrendOpen(false)} />}
    </PanelCard>
  )
}

// Request 2026-08-25 — the "stock market" strip under Proj. Profit: this
// month's HIGH, LOW and % variation, plus the day-over-day move.
//
// Rendered as <tr>s so it sits inside the panel's own table and inherits its
// column widths; a sibling <div> would break the label/value alignment of
// every row above and below it.
//
// ⚠ The values come from an endpoint that folds the LIVE projection into the
// stored series, so the High can never print below the Proj. Profit figure on
// the line directly above (§16). Hidden entirely when the panel is filtered —
// history is unfiltered, and a range from a different population would be a
// lie told confidently.
function ProjProfitTicker({
  stats,
  onOpen,
}: {
  stats: NonNullable<OppProjectionHistory["current_month"]>
  onOpen: () => void
}) {
  const chg = stats.chg_pct
  return (
    <tr>
      <td colSpan={2} className="pb-1 pl-2 pr-1">
        <button
          type="button"
          onClick={onOpen}
          title="Open the month's projection path and the monthly error rate"
          className="flex w-full flex-wrap items-center gap-x-2 gap-y-0.5 rounded px-1 py-0.5 text-left text-[10px] leading-tight text-[#6B7280] hover:bg-[#F0F9FF]"
        >
          <span className="whitespace-nowrap font-semibold text-[#166534]">
            ▲ {fmtUsd(stats.high ?? 0)}
            {stats.high_date && (
              <span className="font-normal text-[#9CA3AF]"> {shortDay(stats.high_date)}</span>
            )}
          </span>
          <span className="whitespace-nowrap font-semibold text-[#991B1B]">
            ▼ {fmtUsd(stats.low ?? 0)}
            {stats.low_date && (
              <span className="font-normal text-[#9CA3AF]"> {shortDay(stats.low_date)}</span>
            )}
          </span>
          {stats.range_pct !== null && (
            <span className="whitespace-nowrap">
              range <span className="font-semibold text-[#374151]">{fmtPct(stats.range_pct)}</span>
            </span>
          )}
          {chg !== null && (
            <span
              className={`whitespace-nowrap font-semibold ${chg < 0 ? "text-[#DC2626]" : "text-[#166534]"}`}
            >
              {chg < 0 ? "▼" : "▲"} {fmtPct(Math.abs(chg))}
            </span>
          )}
        </button>
      </td>
    </tr>
  )
}

/** "08/20" from an ISO date — matches the Trend modal's axis labels. */
function shortDay(iso: string): string {
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}`
}

function projectionCf(filters: OppFilters) {
  return {
    team: filters.team,
    customers: filters.customers,
    loadType: filters.loadType,
    lanes: filters.lanes,
    excludeLanes: filters.excludeLanes,
    carriers: filters.carriers,
    excludeCarriers: filters.excludeCarriers,
  }
}

// Ops Portal Updates PDF (2026-11-18) R3 — the "Info" modal: per-period
// ACTUALS under the projection's row labels, per Day / Week / Month, with an
// internal Team filter (replaces the old Week + Team modals).
function ProjectionInfoModal({
  filters,
  lockedTeam,
  onClose,
}: {
  filters: OppFilters
  lockedTeam?: string
  onClose: () => void
}) {
  const info = useInfoState(lockedTeam ?? filters.team)
  const team = lockedTeam ?? info.team
  const { data, isLoading, error } = useOppTeamProjectionWeekly(
    { ...projectionCf(filters), team: team || undefined },
    true,
    info.grain,
  )
  const periods = data?.data?.periods ?? data?.data?.weeks ?? []
  const columns = periods.map((w) => w.label)
  const num = (get: (w: OppTeamProjectionWeek) => number, fmt: (n: number) => string, signed = false): MatrixCell[] =>
    periods.map((w) => {
      const v = get(w)
      return { text: fmt(v), className: signed ? signCls(v) : undefined }
    })
  const rows: MatrixRow[] = [
    { label: "Avg. Vol x Day",   cells: num((w) => w.avg_vol_day, fmtCount) },
    { label: "Avg. Rev. x Day",  cells: num((w) => w.avg_rev_day, fmtUsd) },
    { label: "Avg. Prof. x Day", cells: num((w) => w.avg_prof_day, fmtUsdSigned, true) },
    { label: "Days Worked",      cells: num((w) => w.pending_workdays, fmtCount) },
    { label: "Volume",           cells: num((w) => w.proj_volume, fmtCount), highlight: true },
    { label: "Revenue",          cells: num((w) => w.proj_revenue, fmtUsd) },
    { label: "Profit",           cells: num((w) => w.proj_profit, fmtUsdSigned, true), highlight: true },
    { label: "Margin P %",       cells: num((w) => w.proj_margin_pct, fmtPct, true) },
    { label: "Rev. x L.",        cells: num((w) => w.proj_rev_x_l, fmtUsd) },
    { label: "Prf. X L.",        cells: num((w) => w.proj_prof_x_l, fmtUsdSigned, true) },
    { label: "Team Ut.",         cells: num((w) => w.proj_team_ut, fmtPct) },
  ]
  return (
    <MetricMatrixModal
      title="Monthly Projection"
      subtitle={infoSubtitle(info.grain, team, "actuals per period")}
      icon="🎯"
      columns={columns}
      rows={rows}
      loading={isLoading}
      error={error}
      onClose={onClose}
      toolbar={
        <InfoToolbar
          grain={info.grain}
          onGrain={info.setGrain}
          team={team}
          onTeam={info.setTeam}
          lockedTeam={lockedTeam}
        />
      }
    />
  )
}
