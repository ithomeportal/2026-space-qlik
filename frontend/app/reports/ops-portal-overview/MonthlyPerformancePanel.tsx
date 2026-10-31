"use client"

import { useState } from "react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtUsdSigned,
  useOppTeamPerformance,
  type OppFilters,
} from "@/lib/ops-portal-overview-api"
import { TeamWeeklyModal } from "./TeamWeeklyModal"
import { TeamMonthlyModal } from "./TeamMonthlyModal"
import { PanelCard, Row, AttritionRow } from "./PanelShared"

// Moved verbatim out of SidePanels.tsx (layout 2026-10-28) — one panel per file.

// ---------------------------------------------------------------------------
// §5 — Team Monthly Performance
// ---------------------------------------------------------------------------

export function TeamPerformance({ filters, lockedTeam }: { filters: OppFilters; lockedTeam?: string }) {
  const { data, isLoading, error } = useOppTeamPerformance(filters)
  const v = data?.data
  const [weeklyOpen, setWeeklyOpen] = useState(false)
  const [monthlyOpen, setMonthlyOpen] = useState(false)
  // Bruno round-2 (2026-05-13): OTP/OTD coloured bands + highlight Volume/Profit/Margin.
  // Bruno R4 (2026-05-27): "+" opens the Team Weekly Performance modal.
  // Bruno R6/R7: "+" relabelled "Week"; new "Team" button opens the monthly modal.
  // R12: Cost x Load = total_cost / volume (guard div-by-zero).
  const costXLoad = v && v.volume ? v.total_cost / v.volume : 0
  return (
    <PanelCard
      title="Monthly Performance"
      icon="📈"
      loading={isLoading}
      error={error}
      action={
        <span className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => setWeeklyOpen(true)}
            title="Weekly Performance — last 5 weeks"
            className="flex h-5 items-center justify-center rounded border border-[#BFDBFE] bg-white px-1.5 text-[10px] font-semibold text-[#2563EB] hover:bg-[#EFF6FF]"
            aria-label="Open Weekly Performance"
          >
            Week
          </button>
          {/* Bruno (2026-06-26): cross-team breakdown is meaningless on the
              single-team CORP copies (T1–T4) — hide the button when locked. */}
          {!lockedTeam && (
            <button
              type="button"
              onClick={() => setMonthlyOpen(true)}
              title="Monthly Performance — by team"
              className="flex h-5 items-center justify-center rounded border border-[#BFDBFE] bg-white px-1.5 text-[10px] font-semibold text-[#2563EB] hover:bg-[#EFF6FF]"
              aria-label="Open Monthly Performance"
            >
              Team
            </button>
          )}
        </span>
      }
    >
      <table className="w-full text-xs">
        <tbody>
          <Row label="Customers"   value={v ? fmtCount(v.customers)   : "—"} />
          <Row label="Lanes"       value={v ? fmtCount(v.lanes)       : "—"} />
          <Row label="Volume"      value={v ? fmtCount(v.volume)      : "—"} highlight />
          <Row label="Revenue"     value={v ? fmtUsd(v.revenue)       : "—"} />
          <Row label="Total Cost"  value={v ? fmtUsd(v.total_cost)    : "—"} />
          <Row label="Profit"      value={v ? fmtUsd(v.profit)        : "—"} signed numeric={v?.profit ?? 0} highlight />
          <Row label="Margin P %"  value={v ? fmtPct(v.margin_pct)    : "—"} signed numeric={v?.margin_pct ?? 0} highlight />
          <Row label="Rev. x L."   value={v ? fmtUsd(v.rev_x_l)       : "—"} />
          <Row label="Prf. X L."   value={v ? fmtUsd(v.prof_x_l)      : "—"} signed numeric={v?.prof_x_l ?? 0} />
          <Row label="Cost x Load" value={v ? fmtUsd(costXLoad)       : "—"} />
          <Row label="Team Ut."    value={v ? fmtPct(v.team_ut)       : "—"} />
          <Row label="OTP."        value={v ? fmtPct(v.otp_pct)       : "—"} bandPct={v?.otp_pct} />
          <Row label="Lates PU"    value={v ? fmtCount(v.lates_pu)    : "—"} />
          <Row label="OTD."        value={v ? fmtPct(v.otd_pct)       : "—"} bandPct={v?.otd_pct} />
          <Row label="Lates DEL."  value={v ? fmtCount(v.lates_del)   : "—"} />
          <Row label="Savings."    value={v ? fmtUsd(v.savings)       : "—"} />
          <Row label="Over Pay"    value={v ? fmtUsd(v.over_pay)      : "—"} signed numeric={v?.over_pay ?? 0} />
          <Row label="Net Savings" value={v ? fmtUsdSigned(v.net_savings) : "—"} signed numeric={v?.net_savings ?? 0} />
          <Row label="Loads w/ Loss." value={v ? fmtCount(v.loss_loads) : "—"} />
          {/* Bruno (PDF 2026-08-31) R3 rename; R6 made this the exact sum of
              the orders counted by "Loads w/ Loss." above, which is also the
              Margin-distribution "< 0%" tile's profit (§96). */}
          <Row label="Total Negative Loads Losses" value={v ? fmtUsdSigned(v.profit_loss) : "—"} signed numeric={v?.profit_loss ?? 0} />
          <Row label="AVG Days (Billed)" value={v ? v.avg_days_billed.toFixed(1) : "—"} />
          <Row label="AVG Days (Not Billed)" value={v ? v.avg_days_not_billed.toFixed(1) : "—"} />
          <Row label="% Del vs Bill" value={v ? fmtPct(v.pct_del_bill) : "—"} />
          {/* Bruno (PDF 2026-08-31) R3: these ARE the attrition-wow report's
              "% Δ" cards — same windows, same weekly-average denominator, same
              inverted colours. ⚠ Signed: negative = the active roster GREW.
              ⚠ They ignore the Date filter (fixed completed ISO weeks) and add
              attrition-wow's %UNILINK% exclusion, so their denominators are
              NOT the Customers / Lanes rows at the top of this panel (§95). */}
          <AttritionRow label="Cust. Attrition %" pct={v?.cust_attr_pct} />
          <AttritionRow label="Lane Attrition %" pct={v?.lane_attr_pct} />
        </tbody>
      </table>
      {weeklyOpen && <TeamWeeklyModal filters={filters} onClose={() => setWeeklyOpen(false)} />}
      {monthlyOpen && <TeamMonthlyModal filters={filters} onClose={() => setMonthlyOpen(false)} />}
    </PanelCard>
  )
}
