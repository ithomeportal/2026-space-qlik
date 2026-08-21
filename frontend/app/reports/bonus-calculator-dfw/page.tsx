"use client"

import { BonusCalculatorPage } from "@/components/BonusCalculatorContent"

/**
 * Bonus Calculator – DFW (Bruno PDF "space --Bonus HR", 2026-08-20).
 *
 * Same engine, same rules, same UI. Two things differ, both server-side:
 *   • the MARGIN ladder — 15/16/17/18/19% → 70/90/100/110/120%, against
 *     corporate's 18.5/20/21/22/23% → 70/100/110/120/130% (Request 3);
 *   • the universe — team_id='TEAM-DFW', sub-teams TM1–TM4.
 *
 * ⚠ Every bracket the UI shows comes from `report.criteria` on the wire, so
 * this page needs no numbers of its own — that is what lets one component
 * serve both ladders without either drifting.
 *
 * ⚠ Its roster, afterhours, FX and month lock live in separate `bonus_dfw_*`
 * tables. `apiPrefix` is what routes there, and it also namespaces the React
 * Query cache — sharing a cache entry would show one division's payroll on the
 * other's page.
 */
export default function BonusCalculatorDfwPage() {
  return (
    <BonusCalculatorPage
      reportKey="bonus-calculator-dfw"
      apiPrefix="custom/bonus-calculator-dfw"
      title="Bonus Calculator – DFW"
      eyebrow="DFW Bonus Module"
    />
  )
}
