"use client"

import { useState } from "react"

import type { Periods, Summary } from "@/lib/division-payment-api"
import { DeductionsBreakdown, NetPaymentBreakdown, TariffBreakdown } from "./Breakdowns"
import { CalculatorCard } from "./CalculatorCard"
import { KpiCards, type BreakdownSection } from "./KpiCards"
import { PaymentHero } from "./PaymentHero"
import { PeriodFilters } from "./PeriodFilters"

interface Props {
  summary: Summary
  periods: Periods | undefined
  year: number | null
  month: string | null
  onPeriodChange: (year: number, month: string) => void
  onOpenCalculator: () => void
  onOpenRecalculations: () => void
}

/**
 * Dashboard tab — PDF Requests 1-6.
 *
 * Layout: the payment hero with the year / month filters top-right, then the
 * read-only calculator card on the left and the four KPI cards on the right,
 * then whichever breakdown the user opened.
 */
export function DashboardTab({
  summary, periods, year, month, onPeriodChange, onOpenCalculator, onOpenRecalculations,
}: Props) {
  const [open, setOpen] = useState<BreakdownSection>(null)

  const toggle = (section: Exclude<BreakdownSection, null>) =>
    setOpen((prev) => (prev === section ? null : section))

  return (
    <div className="space-y-4">
      <PaymentHero
        summary={summary}
        layout="stacked"
        filters={
          <PeriodFilters
            periods={periods}
            year={year}
            month={month}
            onChange={onPeriodChange}
          />
        }
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(280px,1fr)_2fr]">
        <CalculatorCard
          summary={summary}
          editable={false}
          onOpenCalculator={onOpenCalculator}
          onViewRecalculations={onOpenRecalculations}
        />
        <KpiCards summary={summary} open={open} onToggle={toggle} />
      </div>

      {open === "tariff" ? (
        <TariffBreakdown summary={summary} onClose={() => setOpen(null)} />
      ) : null}
      {open === "deductions" ? (
        <DeductionsBreakdown summary={summary} onClose={() => setOpen(null)} />
      ) : null}
      {open === "net" ? (
        <NetPaymentBreakdown summary={summary} onClose={() => setOpen(null)} />
      ) : null}
    </div>
  )
}
