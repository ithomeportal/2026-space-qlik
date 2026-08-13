"use client"

import { useState } from "react"
import { ArrowLeft, Check, Loader2, Wallet } from "lucide-react"

import {
  formatCurrency,
  useApproveMonth,
  type Periods,
  type Summary,
} from "@/lib/division-payment-api"
import { DeductionsBreakdown, NetPaymentBreakdown, TariffBreakdown } from "./Breakdowns"
import { CalculatorCard } from "./CalculatorCard"
import { GlDeductionsTable } from "./GlDeductionsTable"
import { KpiCards, type BreakdownSection } from "./KpiCards"
import { PaymentHero } from "./PaymentHero"
import { PeriodFilters } from "./PeriodFilters"
import { DPC, MONO } from "./theme"

interface Props {
  summary: Summary
  periods: Periods | undefined
  year: number | null
  month: string | null
  onPeriodChange: (year: number, month: string) => void
  onBackToDashboard: () => void
}

/**
 * Calculator tab — PDF Requests 1-5.
 *
 * Request 2 duplicates the Dashboard's calculator card + KPI grid (editable
 * here); Request 3 duplicates the payment hero with the formula moved to the
 * upper-right; Request 4 is the Corporate Gain panel; Request 5 is the GL
 * deductions table.
 *
 * ⚠ Both tabs render the SAME `summary` object. That is the fix for the
 * prototype's $1,575 May 2026 discrepancy — there is no second computation for
 * them to disagree about.
 */
export function CalculatorTab({
  summary, periods, year, month, onPeriodChange, onBackToDashboard,
}: Props) {
  const [open, setOpen] = useState<BreakdownSection>(null)
  const approve = useApproveMonth(summary.year, summary.month)

  const toggle = (section: Exclude<BreakdownSection, null>) =>
    setOpen((prev) => (prev === section ? null : section))

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onBackToDashboard}
          className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium"
          style={{ borderColor: DPC.border, color: DPC.navy }}
        >
          <ArrowLeft className="h-4 w-4" /> Dashboard
        </button>
        <PeriodFilters
          periods={periods}
          year={year}
          month={month}
          onChange={onPeriodChange}
          label="Period"
        />
        <button
          type="button"
          onClick={() => approve.mutate()}
          disabled={approve.isPending}
          className="ml-auto flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
          style={{ background: summary.approved ? DPC.positive : DPC.gold }}
        >
          {approve.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Check className="h-4 w-4" />
          )}
          {summary.approved ? "Re-approve & Archive" : "Approve & Archive"}
        </button>
      </div>

      <PaymentHero summary={summary} layout="inline" />

      <div className="grid gap-4 lg:grid-cols-[minmax(280px,1fr)_2fr]">
        <CalculatorCard summary={summary} editable />
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

      <CorporateGainPanel summary={summary} />
      <GlDeductionsTable summary={summary} />
    </div>
  )
}

/** PDF Calculator Request 4 — 25% of actual profit + tariff = corporate gain. */
function CorporateGainPanel({ summary }: { summary: Summary }) {
  const hasAdjustment = summary.recalc_corporate_adjustment !== 0
  return (
    <section
      className="rounded-xl p-4 text-white"
      style={{ background: `linear-gradient(135deg, ${DPC.container}, ${DPC.navyDeep})` }}
    >
      <div className="flex items-center gap-2.5">
        <span
          className="grid h-8 w-8 place-items-center rounded-lg"
          style={{ background: "#ffffff1a" }}
        >
          <Wallet className="h-4 w-4" style={{ color: DPC.gold }} />
        </span>
        <div>
          <h3 className="text-sm font-bold">Corporate Gain</h3>
          <p className="text-[11px] text-white/60">25% of actual profit + tariff</p>
        </div>
      </div>

      <div className="mt-3 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
        <GainStat
          label="25% of Actual Profit"
          value={formatCurrency(summary.actual_fee)}
          note={`25% × ${formatCurrency(summary.profit)}`}
        />
        <GainStat
          label="Tariff"
          value={formatCurrency(summary.penalty_fee)}
          note={
            summary.penalty_fee > 0
              ? `Margin below ${summary.target_margin_pct}% target`
              : "Target met — no tariff"
          }
          accent
        />
        {hasAdjustment ? (
          <GainStat
            label="Recalculation (25%)"
            value={formatCurrency(summary.recalc_corporate_adjustment)}
            note="25% of the profit delta carried in"
          />
        ) : (
          <div />
        )}
        <div
          className="rounded-lg border p-3"
          style={{ background: `${DPC.gold}1a`, borderColor: `${DPC.gold}4d` }}
        >
          <p className="text-[10px] font-semibold uppercase tracking-wide text-white/70">
            Corporate Gain Total
          </p>
          <p className={`mt-1.5 text-xl font-bold ${MONO}`} style={{ color: DPC.gold }}>
            {formatCurrency(summary.corporate_gain_total)}
          </p>
          <p className="mt-1 text-[10px] text-white/50">
            {formatCurrency(summary.actual_fee)} + {formatCurrency(summary.penalty_fee)}
            {hasAdjustment
              ? ` ${summary.recalc_corporate_adjustment >= 0 ? "+" : "−"} ${formatCurrency(
                  Math.abs(summary.recalc_corporate_adjustment),
                )}`
              : ""}
          </p>
        </div>
      </div>
    </section>
  )
}

function GainStat({
  label, value, note, accent,
}: {
  label: string
  value: string
  note: string
  accent?: boolean
}) {
  return (
    <div className="rounded-lg border p-3" style={{ background: "#ffffff0d", borderColor: "#ffffff1a" }}>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-white/60">{label}</p>
      <p className={`mt-1.5 text-xl font-bold ${MONO}`} style={{ color: accent ? DPC.gold : "#ffffff" }}>
        {value}
      </p>
      <p className="mt-1 text-[10px] text-white/40">{note}</p>
    </div>
  )
}
