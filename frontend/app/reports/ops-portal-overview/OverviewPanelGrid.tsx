"use client"

import type { ReactNode } from "react"
import type { OppFilters } from "@/lib/ops-portal-overview-api"
import { TeamBudgetVariance } from "./BudgetMonthlyVariancePanel"
import { CustomerVariance } from "./CustomerMonthlyVariancePanel"
import { CustomerLosses } from "./CustomerMonthlyLossesPanel"
import { CustomerOverPay } from "./OverPayPanel"
import { TeamPerformance } from "./MonthlyPerformancePanel"
import { TeamProjection } from "./MonthlyProjectionPanel"
import { ServiceIncidentTables } from "./ServiceIncidentTables"
import { CustomerActivityPanel } from "./CustomerActivityPanel"
import { MarginDistribution } from "./MarginDistribution"

/**
 * Layout 2026-10-28 (business screenshot) — the top three rows of every Ops
 * Portal (CORP overview, T1–T4, DFW, Executive). Replaces the old 1.5fr | 1fr
 * split with the chart on the left and a two-column side stack on the right.
 *
 *   xl:  Row 1  Monthly Performance | KPI chart (wide)     | Projection
 *                                   |                       | Customer Monthly Variance
 *        Row 2  New / Deactivated   | Service Incident      | By Carrier   (3 EQUAL)
 *        Row 3  Budget Var | Customer Losses | Over Pay | Margin distribution
 *
 * Row 2 (Bruno PDF 2026-11-17 R3): New Customer | Deactivated left, Service
 * Incident + By Carrier right. Ops Portal Updates PDF 2026-11-18 R1: the three
 * are EQUAL sections — Row 2 is its own `xl:grid-cols-3` grid (it used to sit
 * in Row 1's 1fr | 2.4fr | 1fr tracks, so the pair got ~1.7 columns each).
 * The pair spans 2 tracks; its inner grid uses the SAME gap (gap-4), so each
 * of the two is exactly one track wide. Items stretch to one row height.
 * Below xl everything stacks in DOM order: Performance, chart, Projection,
 * Customer Variance, New/Deactivated, Service Incident, By Carrier, Budget,
 * Losses, Over Pay, Margin distribution.
 *
 * ⚠ `min-w-0` on every grid child: grid items default to `min-width: auto`, so
 * one wide table/chart would push the whole page into horizontal scroll.
 */
export const ROW1_GRID_CLS =
  "grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2.4fr)_minmax(0,1fr)] xl:items-start"

// ⚠ gap-4 must match ServiceIncidentTables' inner gap, or the pair stops
// being exactly two tracks of this grid.
export const ROW2_GRID_CLS = "grid grid-cols-1 gap-4 xl:grid-cols-3 [&>*]:min-w-0"

interface Props {
  filters: OppFilters
  /** The KPI MANAGEMENT combo chart (with its working-days strip + gauge). */
  chart: ReactNode
  /** R9 (Bruno): customer-name cells drill to that customer. */
  onPickCustomer?: (customer: string) => void
  /** Bruno (PDF 2026-07-23) R3: a By Carrier click applies that carrier filter. */
  onPickCarrier?: (carrier: string) => void
  /**
   * Bruno (2026-06-26): per-team CORP copies (T1–T4) lock to one team, so the
   * cross-team "Team" breakdown buttons are hidden.
   */
  lockedTeam?: string
  /**
   * Bruno (PDF 2026-08-20) DFW R6: drops the Budget Monthly Variance panel.
   * DFW has no budget rows at all, so it would render zeros.
   */
  hideBudget?: boolean
  /**
   * Bruno (PDF 2026-08-20) DFW R7: how Customer Monthly Variance is computed.
   * "budget" = actual − budget · "mom" = last month − this month.
   */
  customerVarianceBasis?: "budget" | "mom"
}

export function OverviewPanelGrid({
  filters,
  chart,
  onPickCustomer,
  onPickCarrier,
  lockedTeam,
  hideBudget = false,
  customerVarianceBasis = "budget",
}: Props) {
  return (
    <>
      {/* Row 1 */}
      <div className={ROW1_GRID_CLS}>
        <div className="min-w-0">
          <TeamPerformance filters={filters} lockedTeam={lockedTeam} />
        </div>
        <div className="min-w-0">{chart}</div>
        <div className="min-w-0 space-y-4">
          <TeamProjection filters={filters} lockedTeam={lockedTeam} />
          <CustomerVariance
            filters={filters}
            onPickCustomer={onPickCustomer}
            basis={customerVarianceBasis}
          />
        </div>
      </div>

      {/* Row 2 — three equal sections (PDF 2026-11-18 R1). */}
      <div className={ROW2_GRID_CLS}>
        <div>
          <CustomerActivityPanel filters={filters} onPickCustomer={onPickCustomer} />
        </div>
        <ServiceIncidentTables
          filters={filters}
          onPickCustomer={onPickCustomer}
          onPickCarrier={onPickCarrier}
          className="xl:col-span-2"
        />
      </div>

      {/* Row 3 — four equal columns; three when DFW drops the budget panel. */}
      <div
        className={`grid grid-cols-1 gap-4 md:grid-cols-2 [&>*]:min-w-0 ${
          hideBudget ? "xl:grid-cols-3" : "xl:grid-cols-4"
        }`}
      >
        {!hideBudget && <TeamBudgetVariance filters={filters} lockedTeam={lockedTeam} />}
        <CustomerLosses filters={filters} onPickCustomer={onPickCustomer} />
        <CustomerOverPay filters={filters} onPickCustomer={onPickCustomer} />
        <MarginDistribution filters={filters} compact />
      </div>
    </>
  )
}
