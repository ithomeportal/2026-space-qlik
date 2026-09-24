"use client"

import { useState } from "react"

import { ReportGuard } from "@/components/ReportGuard"
import {
  CORP_GO_TO_LINKS,
  OpsPortalOverviewContent,
  type GoToLink,
} from "@/components/OpsPortalOverviewContent"

/**
 * Executive OPS Portal (Bruno PDF "BRUNO -- Exec Portal", 2026-09-03) — was
 * "CEO Executive Portal" until 2026-09-24. The route keeps its old slug on
 * purpose: favourites, access_log and role_report_access hang off it.
 *
 * 2026-09-24 (Erick Mendoza): an ALL division (CORP's five teams + TEAM-DFW as
 * a sixth; no budget, like DFW), and the "Go to" row the OPS Managers Portal
 * has, following the selected division.
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
  { key: "all", label: "ALL" },
] as const

type DivisionKey = (typeof DIVISIONS)[number]["key"]

/** DFW's own copies of the CORP destinations, where one exists. */
const DFW_GO_TO_LINKS: readonly GoToLink[] = [
  { label: "Bonus Calculator – DFW", href: "/reports/bonus-calculator-dfw" },
  { label: "XRay DFW Mng", href: "/reports/xray-dfw-mng" },
  { label: "KAM Performance – DFW", href: "/reports/kam-performance-dfw" },
  { label: "DFW Losses", href: "/reports/dfw-losses" },
]

// ⚠ Every href here is granted to the CEO TagRole (verified 2026-09-24). The
// Executive TagRole, added the same day, lacks the two Bonus Calculators —
// those pills open onto ReportGuard's "no access" page for an Executive, which
// is the correct answer for payroll data, not a broken link.
const GO_TO_BY_DIVISION: Record<DivisionKey, readonly GoToLink[]> = {
  corp: CORP_GO_TO_LINKS,
  dfw: DFW_GO_TO_LINKS,
  all: [...CORP_GO_TO_LINKS, ...DFW_GO_TO_LINKS],
}

export default function CeoExecutivePortalPage() {
  // CORP first — it is the report Request 1 says to duplicate. This is a UI
  // starting point, not a server default: the prefix below always names a
  // division explicitly, so nothing is ever fetched without one.
  const [division, setDivision] = useState<DivisionKey>("corp")
  // DFW and ALL have no budget: the budget table is CORP-only, so under ALL a
  // variance would set CORP+DFW actuals against a CORP-only plan (§98).
  const hasBudget = division === "corp"
  const badge = DIVISIONS.find((d) => d.key === division)?.label ?? "CORP"

  return (
    <ReportGuard reportKey="ceo-executive-portal">
      <OpsPortalOverviewContent
        apiPrefix={`custom/ceo-executive-portal/${division}`}
        title="Executive OPS Portal"
        badge={badge}
        goToLinks={GO_TO_BY_DIVISION[division]}
        hideBudget={!hasBudget}
        customerVarianceBasis={hasBudget ? "budget" : "mom"}
        divisions={DIVISIONS}
        division={division}
        onDivisionChange={(k) => setDivision(k as DivisionKey)}
      />
    </ReportGuard>
  )
}
