"use client"

import { useEffect, useMemo, useState } from "react"
import Link from "next/link"
import { ArrowLeft, Calculator, LayoutGrid, Loader2, RefreshCw } from "lucide-react"

import { ReportGuard } from "@/components/ReportGuard"
import { usePeriods, useSummary } from "@/lib/division-payment-api"
import { CalculatorTab } from "./CalculatorTab"
import { DashboardTab } from "./DashboardTab"
import { RecalculationsTab } from "./RecalculationsTab"
import { DPC } from "./theme"

type TabId = "dashboard" | "calculator" | "recalculations"

const TABS: { id: TabId; label: string; icon: typeof LayoutGrid }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutGrid },
  { id: "calculator", label: "Calculator", icon: Calculator },
  { id: "recalculations", label: "Recalculations", icon: RefreshCw },
]

/**
 * Division Payment Calculator — Bruno PDF 2026-08-13.
 *
 * Three tabs (Dashboard · Calculator · Recalculations). The selected period is
 * held here and shared by the first two, so switching tabs keeps the month —
 * the prototype reset to its default month on every tab change.
 */
export default function DivisionPaymentCalculatorPage() {
  return (
    <ReportGuard reportKey="division-payment-calculator">
      <DivisionPaymentCalculator />
    </ReportGuard>
  )
}

function DivisionPaymentCalculator() {
  const [tab, setTab] = useState<TabId>("dashboard")
  const [year, setYear] = useState<number | null>(null)
  const [month, setMonth] = useState<string | null>(null)

  const periodsQ = usePeriods()
  const periods = periodsQ.data

  // Default to the most recent month the portal has data for. Deriving it from
  // the payload rather than hardcoding is what stops the prototype's cold-open
  // bug, where the dropdown said "July 2026" over May's numbers.
  const latest = useMemo(() => {
    const months = periods?.months ?? []
    if (months.length === 0) return null
    const newestYear = Math.max(...months.map((m) => m.year))
    const inYear = months.filter((m) => m.year === newestYear)
    return inYear[inYear.length - 1]
  }, [periods])

  useEffect(() => {
    if (latest && year === null) {
      setYear(latest.year)
      setMonth(latest.month)
    }
  }, [latest, year])

  const summaryQ = useSummary(year, month)
  const summary = summaryQ.data

  const handlePeriodChange = (nextYear: number, nextMonth: string) => {
    setYear(nextYear)
    setMonth(nextMonth)
  }

  return (
    <div className="min-h-screen" style={{ background: DPC.offWhite }}>
      <div className="mx-auto max-w-[1400px] px-4 py-5 sm:px-6">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <Link
              href="/"
              className="mb-1.5 inline-flex items-center gap-1.5 text-xs text-[#6B7280] hover:text-[#111827]"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Back to reports
            </Link>
            <h1 className="text-xl font-bold sm:text-2xl" style={{ color: DPC.navy }}>
              Division Payment Calculator
            </h1>
            <p className="text-xs text-[#6B7280]">
              Monthly payment owed to the A&amp;O division — profit, GL deductions, tariff and
              corporate gain
            </p>
          </div>
        </header>

        <nav
          className="mb-4 flex gap-1 overflow-x-auto border-b"
          style={{ borderColor: DPC.border }}
          aria-label="Report sections"
        >
          {TABS.map((t) => {
            const Icon = t.icon
            const active = tab === t.id
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setTab(t.id)}
                aria-current={active ? "page" : undefined}
                className="flex shrink-0 items-center gap-2 border-b-2 px-4 py-2.5 text-sm font-semibold transition"
                style={{
                  borderColor: active ? DPC.gold : "transparent",
                  color: active ? DPC.navy : "#94a3b8",
                }}
              >
                <Icon className="h-4 w-4" style={{ color: active ? DPC.gold : "#cbd5e1" }} />
                {t.label}
              </button>
            )
          })}
        </nav>

        {tab === "recalculations" ? (
          <RecalculationsTab />
        ) : summaryQ.isError ? (
          <ErrorState onRetry={() => summaryQ.refetch()} />
        ) : !summary ? (
          <LoadingState />
        ) : tab === "dashboard" ? (
          <DashboardTab
            summary={summary}
            periods={periods}
            year={year}
            month={month}
            onPeriodChange={handlePeriodChange}
            onOpenCalculator={() => setTab("calculator")}
            onOpenRecalculations={() => setTab("recalculations")}
          />
        ) : (
          <CalculatorTab
            summary={summary}
            periods={periods}
            year={year}
            month={month}
            onPeriodChange={handlePeriodChange}
            onBackToDashboard={() => setTab("dashboard")}
          />
        )}
      </div>
    </div>
  )
}

function LoadingState() {
  return (
    <div className="flex items-center justify-center gap-2 rounded-xl border bg-white py-20 text-sm text-[#94a3b8]"
         style={{ borderColor: DPC.border }}>
      <Loader2 className="h-5 w-5 animate-spin" />
      Loading division payment data…
    </div>
  )
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="rounded-xl border bg-white px-6 py-16 text-center" style={{ borderColor: DPC.border }}>
      <p className="text-sm font-semibold" style={{ color: DPC.navy }}>
        Could not load this month
      </p>
      <p className="mt-1 text-xs text-[#94a3b8]">
        The backend may be waking up — this usually clears in under a minute.
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 rounded-lg px-4 py-2 text-sm font-semibold text-white"
        style={{ background: DPC.navy }}
      >
        Retry
      </button>
    </div>
  )
}
