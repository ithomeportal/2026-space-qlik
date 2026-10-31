"use client"

import { useState } from "react"
import {
  fmtCount,
  fmtPct,
  fmtUsdSigned,
  useOppTeamVariance,
  useOppTeamVarianceByTeam,
  useOppTeamVarianceWeekly,
  type OppFilters,
  type OppTeamVariance,
} from "@/lib/ops-portal-overview-api"
import { MetricMatrixModal, type MatrixCell, type MatrixRow } from "./MetricMatrixModal"
import { PanelCard, Row, WeekTeamButtons, concPct, signCls } from "./PanelShared"

// Moved verbatim out of SidePanels.tsx (layout 2026-10-28) — one panel per file.

// ---------------------------------------------------------------------------
// §2 — Team Budget Monthly Variance (inverted single-row table)
// ---------------------------------------------------------------------------

export function TeamBudgetVariance({ filters, lockedTeam }: { filters: OppFilters; lockedTeam?: string }) {
  const { data, isLoading, error } = useOppTeamVariance(filters)
  const v = data?.data
  // Bruno (PDF 2026-07-13): Week / Team break-out modals.
  const [weekOpen, setWeekOpen] = useState(false)
  const [teamOpen, setTeamOpen] = useState(false)
  return (
    <PanelCard
      title="Budget Monthly Variance"
      icon="📊"
      loading={isLoading}
      error={error}
      action={
        <WeekTeamButtons
          onWeek={() => setWeekOpen(true)}
          onTeam={() => setTeamOpen(true)}
          lockedTeam={lockedTeam}
        />
      }
    >
      <table className="w-full text-xs">
        <tbody>
          <Row label="Customers"  value={v ? String(v.customers) : "—"} signed numeric={v?.customers ?? 0} />
          <Row label="Volume"     value={v ? fmtCount(v.volume_var) : "—"}  signed numeric={v?.volume_var ?? 0} />
          <Row label="Revenue"    value={v ? fmtUsdSigned(v.revenue_var) : "—"} signed numeric={v?.revenue_var ?? 0} />
          <Row label="Profit"     value={v ? fmtUsdSigned(v.profit_var) : "—"}  signed numeric={v?.profit_var ?? 0} />
          <Row label="Margin P %" value={v ? fmtPct(v.margin_var_pct) : "—"} signed numeric={v?.margin_var_pct ?? 0} />
          <Row label="Rev. x L."  value={v ? fmtUsdSigned(v.rev_x_l) : "—"}   signed numeric={v?.rev_x_l ?? 0} />
          <Row label="Prf. X L."  value={v ? fmtUsdSigned(v.prof_x_l) : "—"}  signed numeric={v?.prof_x_l ?? 0} />
        </tbody>
      </table>
      {weekOpen && <VarianceWeekModal filters={filters} onClose={() => setWeekOpen(false)} />}
      {teamOpen && <VarianceTeamModal filters={filters} onClose={() => setTeamOpen(false)} />}
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-07-13) — Week / Team break-out modals for the Team Budget
// Variance and Team Monthly Projection panels.
// ---------------------------------------------------------------------------

function VarianceWeekModal({ filters, onClose }: { filters: OppFilters; onClose: () => void }) {
  const { data, isLoading, error } = useOppTeamVarianceWeekly(filters, true)
  const weeks = data?.data?.weeks ?? []
  const columns = weeks.map((w) => w.label)
  const num = (get: (w: OppTeamVariance) => number, fmt: (n: number) => string, signed = true): MatrixCell[] =>
    weeks.map((w) => {
      const v = get(w)
      return { text: fmt(v), className: signed ? signCls(v) : undefined }
    })
  const rows: MatrixRow[] = [
    { label: "Customers",  cells: num((w) => w.customers, fmtCount, false) },
    { label: "Volume",     cells: num((w) => w.volume_var, fmtCount), highlight: true },
    { label: "Revenue",    cells: num((w) => w.revenue_var, fmtUsdSigned) },
    { label: "Profit",     cells: num((w) => w.profit_var, fmtUsdSigned), highlight: true },
    { label: "Margin P %", cells: num((w) => w.margin_var_pct, fmtPct) },
    { label: "Rev. x L.",  cells: num((w) => w.rev_x_l, fmtUsdSigned) },
    { label: "Prf. X L.",  cells: num((w) => w.prof_x_l, fmtUsdSigned) },
  ]
  return (
    <MetricMatrixModal
      title="Budget Monthly Variance"
      subtitle="last 5 weeks (Mon–Sun)"
      icon="📊"
      columns={columns}
      rows={rows}
      loading={isLoading}
      error={error}
      onClose={onClose}
    />
  )
}

function VarianceTeamModal({ filters, onClose }: { filters: OppFilters; onClose: () => void }) {
  const { data, isLoading, error } = useOppTeamVarianceByTeam(filters, true)
  const total = data?.data?.total
  const teams = data?.data?.teams ?? []
  const columns = ["Total", ...teams.map((t) => t.team_id)]
  const num = (
    get: (v: OppTeamVariance) => number,
    fmt: (n: number) => string,
    { signed = true, showConc = false }: { signed?: boolean; showConc?: boolean } = {},
  ): MatrixCell[] => {
    const tv = total ? get(total) : 0
    const cells: MatrixCell[] = [
      { text: total ? fmt(tv) : "—", className: signed ? signCls(tv) : undefined },
    ]
    for (const t of teams) {
      const v = get(t)
      cells.push({
        text: fmt(v),
        className: signed ? signCls(v) : undefined,
        conc: showConc ? concPct(v, tv) : undefined,
      })
    }
    return cells
  }
  const rows: MatrixRow[] = [
    { label: "Customers",  cells: num((v) => v.customers, fmtCount, { signed: false, showConc: true }) },
    { label: "Volume",     cells: num((v) => v.volume_var, fmtCount, { showConc: true }), highlight: true },
    { label: "Revenue",    cells: num((v) => v.revenue_var, fmtUsdSigned, { showConc: true }) },
    { label: "Profit",     cells: num((v) => v.profit_var, fmtUsdSigned, { showConc: true }), highlight: true },
    { label: "Margin P %", cells: num((v) => v.margin_var_pct, fmtPct) },
    { label: "Rev. x L.",  cells: num((v) => v.rev_x_l, fmtUsdSigned) },
    { label: "Prf. X L.",  cells: num((v) => v.prof_x_l, fmtUsdSigned) },
  ]
  return (
    <MetricMatrixModal
      title="Budget Monthly Variance"
      subtitle="by team"
      icon="📊"
      columns={columns}
      rows={rows}
      loading={isLoading}
      error={error}
      onClose={onClose}
    />
  )
}
