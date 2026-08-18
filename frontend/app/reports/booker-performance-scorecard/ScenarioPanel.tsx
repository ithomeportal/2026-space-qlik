"use client"

import { FlaskConical } from "lucide-react"
import {
  SCENARIO_STEPS,
  fmtUsd,
  useBookerSummary,
  type BookerFilters,
  type BookerScopeFilters,
  type ScenarioStep,
} from "@/lib/booker-scorecard-api"
import { KpiCards } from "./KpiCards"
import { OrdersTable } from "./OrdersTable"
import { WeeklyChart } from "./WeeklyChart"

interface Props {
  /** The Scorecard tab's filters, WITHOUT any adjustment. */
  filters: BookerFilters
  scope: BookerScopeFilters
  step: ScenarioStep
  onStepChange: (step: ScenarioStep) => void
}

/**
 * Scenario tab (Bruno PDF 2026-08-18 R1/R2).
 *
 * The whole Scorecard tab re-rendered against what-if numbers: each order's
 * profit is raised by the selected step and its carrier cost cut by the same
 * amount, then every derived figure — margin, avg margin per load, broken
 * threshold, cost saving, the Totals row — is recomputed from those adjusted
 * orders.
 *
 * The adjustment is applied SERVER-side, in the same code path the Scorecard
 * tab uses, for two reasons: the Totals row and every KPI are full-universe
 * aggregates that a paginated client could not recompute, and sharing the code
 * path is what guarantees the Scenario tab at step 0 is arithmetically the
 * Scorecard tab (§69).
 *
 * Revenue deliberately does NOT move: carrier cost is derived as
 * `revenue − profit`, so the two deltas cancel. This models negotiating carrier
 * pay down, not charging the customer more.
 *
 * The chart is shown for fidelity with the original tab and costs nothing: it
 * carries no money, so its query key is unchanged and React Query serves the
 * Scorecard tab's cached response rather than issuing a second scan.
 */
export function ScenarioPanel({ filters, scope, step, onStepChange }: Props) {
  const scenarioFilters: BookerFilters = { ...filters, adjustment: step }

  // The unadjusted numbers, for the "vs actual" deltas. Same query key as the
  // Scorecard tab's KPI row, so switching tabs costs no extra request.
  const { data: baseRes } = useBookerSummary(filters)
  const baseline = baseRes?.data ?? null

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-[#FDE68A] bg-[#FFFBEB] px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-[#B45309]" />
            <span className="text-xs font-semibold uppercase tracking-wider text-[#B45309]">
              Scenario — hypothetical numbers
            </span>
          </div>

          <div className="flex rounded-lg border border-[#FDE68A] bg-white text-xs">
            {SCENARIO_STEPS.map((s) => (
              <button
                key={s}
                onClick={() => onStepChange(s)}
                aria-pressed={step === s}
                className={`px-4 py-1.5 font-semibold first:rounded-l-lg last:rounded-r-lg ${
                  step === s
                    ? "bg-[#B45309] text-white"
                    : "text-[#92400E] hover:bg-[#FEF3C7]"
                }`}
              >
                {s}
              </button>
            ))}
          </div>

          <span className="text-xs text-[#92400E]">
            Every order: profit <strong>+{fmtUsd(step)}</strong>, carrier cost{" "}
            <strong>−{fmtUsd(step)}</strong>. Revenue is unchanged.
          </span>
        </div>
        <p className="mt-2 text-[11px] text-[#B45309]">
          These figures are a what-if projection, not booked results. Orders with
          no margin recorded in McLeod are left untouched rather than given one.
        </p>
      </div>

      <KpiCards filters={scenarioFilters} baseline={baseline} />
      <WeeklyChart scope={scope} />
      <OrdersTable filters={scenarioFilters} />
    </div>
  )
}
