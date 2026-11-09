"use client"

import { OpsPortalOverviewContent } from "@/components/OpsPortalOverviewContent"

export type DfwTeam = "TM1" | "TM2" | "TM3" | "TM4"

/**
 * OPS Portal DFW TM1..TM4 (Bruno PDF "BRUNO -- Ops Portal DFW", 2026-11-09).
 *
 * The Ops Managers Portal – DFW, locked to one sub-team. One body for the four
 * pages (3rd copy ⇒ factory): every DFW-only prop the division page sets is set
 * here too — no budget, month-over-month Customer Variance, Actuals vs the same
 * days of last month — plus `lockedTeam`, which swaps the Teams pills for a
 * badge and hides the cross-team "Team" breakdown buttons.
 *
 * The backend router (`ops_portal_overview_dfw_team.py`) is the real lock: it
 * pins TEAM-DFW + the team server-side and never reads `?team=`.
 */
export function OpsPortalDfwTeamContent({ tm }: { tm: DfwTeam }) {
  return (
    <OpsPortalOverviewContent
      apiPrefix={`custom/ops-portal-overview-dfw-${tm.toLowerCase()}`}
      title={`OPS Portal DFW ${tm}`}
      lockedTeam={tm}
      badge={`DFW · ${tm}`}
      hideBonusNav
      hideGoTo
      hideBudget
      customerVarianceBasis="mom"
      actualsCompare="prior_month"
    />
  )
}
