"use client"

import { useState } from "react"
import {
  fmtCount,
  fmtPct,
  fmtUsdSigned,
  useOppTeamVariance,
  useOppTeamVarianceWeekly,
  type OppFilters,
  type OppTeamVariance,
} from "@/lib/ops-portal-overview-api"
import { MetricMatrixModal, type MatrixCell, type MatrixRow } from "./MetricMatrixModal"
import { InfoButtons, PanelCard, Row, signCls } from "./PanelShared"
import { InfoToolbar, infoSubtitle, useInfoState } from "./InfoControls"

// Moved verbatim out of SidePanels.tsx (layout 2026-10-28) — one panel per file.

// ---------------------------------------------------------------------------
// §2 — Team Budget Monthly Variance (inverted single-row table)
// ---------------------------------------------------------------------------

export function TeamBudgetVariance({ filters, lockedTeam }: { filters: OppFilters; lockedTeam?: string }) {
  const { data, isLoading, error } = useOppTeamVariance(filters)
  const v = data?.data
  // Ops Portal Updates PDF (2026-11-18) R4: ONE "Info" modal (was Week + Team).
  const [infoOpen, setInfoOpen] = useState(false)
  return (
    <PanelCard
      title="Budget Monthly Variance"
      icon="📊"
      loading={isLoading}
      error={error}
      action={
        <InfoButtons onInfo={() => setInfoOpen(true)} />
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
      {infoOpen && (
        <VarianceInfoModal filters={filters} lockedTeam={lockedTeam} onClose={() => setInfoOpen(false)} />
      )}
    </PanelCard>
  )
}

// ---------------------------------------------------------------------------
// Ops Portal Updates PDF (2026-11-18) R4 — the "Info" modal: the old Week
// matrix per Day / Week / Month, with an internal Team filter. The old "Team"
// (side-by-side by team) modal is gone; the filter replaces it.
// ---------------------------------------------------------------------------

function VarianceInfoModal({
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
  const { data, isLoading, error } = useOppTeamVarianceWeekly(
    { team: team || undefined, customers: filters.customers },
    true,
    info.grain,
  )
  const periods = data?.data?.periods ?? data?.data?.weeks ?? []
  const columns = periods.map((w) => w.label)
  const num = (get: (w: OppTeamVariance) => number, fmt: (n: number) => string, signed = true): MatrixCell[] =>
    periods.map((w) => {
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
      subtitle={infoSubtitle(info.grain, team, "actual − budget (current period vs its whole goal)")}
      icon="📊"
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
