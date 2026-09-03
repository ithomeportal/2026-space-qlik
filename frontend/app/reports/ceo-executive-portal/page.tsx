"use client"

import { useState } from "react"

import { ReportGuard } from "@/components/ReportGuard"
import { OpsPortalOverviewContent } from "@/components/OpsPortalOverviewContent"

/**
 * CEO Executive Portal (Bruno PDF "BRUNO -- Exec Portal", 2026-09-03).
 *
 * Request 1: a duplicate of /reports/ops-portal-overview for the CEO.
 * Request 2: it must also cover `team_id = 'TEAM-DFW'`.
 * Request 3: a "Division" filter chooses which of the two it is showing.
 *
 * So this is the same engine as every other Ops portal, with the division
 * chosen by the reader instead of pinned by the router. It is the only report
 * where that is true; access is `ceo-executive-portal`, seeded to the CEO
 * TagRole (Erick Mendoza + admins).
 *
 * ⚠ The division rides in the API PREFIX, not in a query param.
 *
 * Two things fall out of that, and both matter:
 *
 *   1. The backend route is `/{division}/…`, a required path segment. A
 *      defaulted scope is how the DFW Bonus Calculator served the CORPORATE
 *      report for weeks without erroring (§100) — a segment cannot default.
 *   2. `prefix` is already part of every queryKey in `ops-portal-overview-api`,
 *      so changing it re-keys all 29 caches at once. There is no window in
 *      which a CORP panel is on screen under a DFW heading, and no per-hook
 *      queryKey to remember to update.
 *
 * ⚠ `hideBudget` / `customerVarianceBasis` track the division rather than the
 * report. DFW has no budget at all (0 of its 15 YTD customers appear in
 * `daily_production_budget_report`), so its budget endpoints 404 by design and
 * Customer Monthly Variance is month-over-month with the OPPOSITE sign
 * convention — the panel labels which one it is showing (§69).
 */
const DIVISIONS = [
  { key: "corp", label: "CORP" },
  { key: "dfw", label: "DFW" },
] as const

type DivisionKey = (typeof DIVISIONS)[number]["key"]

export default function CeoExecutivePortalPage() {
  // CORP first — it is the report Request 1 says to duplicate. This is a UI
  // starting point, not a server default: the prefix below always names a
  // division explicitly, so nothing is ever fetched without one.
  const [division, setDivision] = useState<DivisionKey>("corp")
  const isDfw = division === "dfw"

  return (
    <ReportGuard reportKey="ceo-executive-portal">
      <OpsPortalOverviewContent
        apiPrefix={`custom/ceo-executive-portal/${division}`}
        title="CEO Executive Portal"
        badge={isDfw ? "DFW" : "CORP"}
        hideBonusNav
        hideGoTo
        hideBudget={isDfw}
        customerVarianceBasis={isDfw ? "mom" : "budget"}
        divisions={DIVISIONS}
        division={division}
        onDivisionChange={(k) => setDivision(k as DivisionKey)}
      />
    </ReportGuard>
  )
}
