/**
 * XRay DFW — "Profit — This Month" goal (Bruno PDF 2026-11-02, Overview R1).
 *
 *   All (no team picked, or the RUAN view)  → $500,000
 *   TM1 / TM2 / TM3 / TM4                   → $100,000 each
 *
 * Several teams picked multiply ($100k × N), so all four picked by hand reads
 * $400,000 — deliberately NOT the $500,000 division target, which is a
 * division-level stretch, not a sum of team goals (decision 2026-11-02).
 *
 * ⚠ A scope-locked clone (`/reports/xray-dfw-tm1` …) sends NO `subTeams` — the
 * backend hard-locks the team instead — so it must pass `lockedTeam`, or it
 * reads as "All" and shows the division goal. That was live until 2026-11-02:
 * every TM clone showed the old All figure ($220,000).
 */
export const DFW_PROFIT_GOAL_ALL = 500_000
export const DFW_PROFIT_GOAL_PER_TEAM = 100_000

export function dfwProfitGoal(opts: {
  subTeams?: string[]
  lockedTeam?: string
}): number {
  if (opts.lockedTeam) return DFW_PROFIT_GOAL_PER_TEAM
  const picked = opts.subTeams?.length ?? 0
  return picked > 0 ? DFW_PROFIT_GOAL_PER_TEAM * picked : DFW_PROFIT_GOAL_ALL
}
