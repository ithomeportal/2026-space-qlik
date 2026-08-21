"use client"

import { ReportGuard } from "@/components/ReportGuard"
import { OpsPortalOverviewContent } from "@/components/OpsPortalOverviewContent"

/**
 * Ops Managers Portal – DFW (Bruno PDF "space -- Ops Portal DFW", 2026-08-20).
 *
 * The DFW division copy of Ops Portal Overview. Unlike the four CORP-T pages
 * this is NOT scope-locked to one team: it covers the whole DFW division, with
 * TM1–TM5 as its team pills. The backend router pins `team_id = 'TEAM-DFW'`
 * and reads the sub-team from `v4.team`, so the Team column shows TM1..TM5
 * (Request 3).
 *
 * Every budget control is off (Requests 5, 6, 8) because DFW genuinely has no
 * budget: 0 of its 15 YTD customers appear in `daily_production_budget_report`.
 * Customer Monthly Variance is month-over-month instead (Request 7), which the
 * panel labels — its sign convention is the opposite of the CORP one.
 */
export default function OpsManagersPortalDfwPage() {
  return (
    <ReportGuard reportKey="ops-managers-portal-dfw">
      <OpsPortalOverviewContent
        apiPrefix="custom/ops-portal-overview-dfw"
        title="Ops Managers Portal – DFW"
        badge="DFW"
        hideBonusNav
        hideGoTo
        hideBudget
        customerVarianceBasis="mom"
      />
    </ReportGuard>
  )
}
