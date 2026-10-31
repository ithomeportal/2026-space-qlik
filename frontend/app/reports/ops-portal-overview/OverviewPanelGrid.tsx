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
import { MarginDistribution } from "./MarginDistribution"

/**
 * Layout 2026-10-28 (business screenshot) — the top three rows of every Ops
 * Portal (CORP overview, T1–T4, DFW, Executive). Replaces the old 1.5fr | 1fr
 * split with the chart on the left and a two-column side stack on the right.
 *
 *   xl:  Row 1  Monthly Performance | KPI chart (wide)     | Projection
 *                                   |                       | Customer Monthly Variance
 *        Row 2  Service Incident    | By Carrier            | (free)
 *        Row 3  Budget Var | Customer Losses | Over Pay | Margin distribution
 *
 * Row 2 is a grid item spanning the left + centre columns, so the right column
 * under Customer Monthly Variance stays empty rather than stretching the tables.
 * Below xl everything stacks in DOM order: Performance, chart, Projection,
 * Customer Variance, Service Incident, By Carrier, Budget, Losses, Over Pay,
 * Margin distribution.
 *
 * ⚠ `min-w-0` on every grid child: grid items default to `min-width: auto`, so
 * one wide table/chart would push the whole page into horizontal scroll.
 */
export const ROW1_GRID_CLS =
  "grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2.4fr)_minmax(0,1fr)] xl:items-start"

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
      {/* Row 1 (+ Row 2 under the left + centre columns) */}
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
