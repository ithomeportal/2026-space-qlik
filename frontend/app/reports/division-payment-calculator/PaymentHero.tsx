"use client"

import type { ReactNode } from "react"
import { ArrowDown, ArrowUp, CheckCircle2, Clock } from "lucide-react"

import { formatCurrency, formatPct, type Summary } from "@/lib/division-payment-api"
import { DPC, MONO } from "./theme"

interface Props {
  summary: Summary
  /** Dashboard stacks the formula under the value; Calculator puts it top-right
   *  (PDF Calculator Request 3). Same numbers, same source, two layouts. */
  layout?: "stacked" | "inline"
  filters?: ReactNode
}

/**
 * "Payment Due to A&O Division" — PDF Dashboard Request 1 / Calculator Request 3.
 *
 * ⚠ Renders `net_payment_adjusted` and the three formula terms exactly as the
 * server computed them. It derives nothing. The prototype had each page compute
 * its own net payment and they disagreed by $1,575 on May 2026.
 */
export function PaymentHero({ summary, layout = "stacked", filters }: Props) {
  const delta = summary.delta_vs_previous
  const up = (delta ?? 0) >= 0
  const inline = layout === "inline"

  const formula = (
    <div
      className={`flex flex-wrap items-center gap-x-3 gap-y-1 text-sm ${MONO}`}
      // The colours below are specified in the PDF, not chosen.
    >
      <span className="text-white/50">Profit</span>
      <span style={{ color: DPC.profit }}>{formatCurrency(summary.profit)}</span>
      <span className="text-white/40">−</span>
      <span className="text-white/50">Deductions</span>
      <span style={{ color: DPC.deduction }}>{formatCurrency(summary.gl_deductions)}</span>
      <span className="text-white/40">−</span>
      <span className="text-white/50">Corporate Gain</span>
      <span style={{ color: DPC.gold }}>{formatCurrency(summary.corporate_gain_total)}</span>
      <span className="text-white/40">=</span>
      <span className="text-white/50">Net Payment</span>
      <span className="font-semibold" style={{ color: DPC.profit }}>
        {formatCurrency(summary.net_payment_adjusted)}
      </span>
    </div>
  )

  return (
    <section
      className="overflow-hidden rounded-xl px-5 py-5 text-white shadow-sm"
      style={{ background: `linear-gradient(135deg, ${DPC.container}, ${DPC.containerTo})` }}
    >
      <div className={inline ? "flex flex-wrap items-start justify-between gap-4" : ""}>
        <div className={inline ? "min-w-[280px]" : ""}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <span
                className="grid h-8 w-8 place-items-center rounded-lg text-[11px] font-bold"
                style={{ background: `${DPC.gold}33`, color: DPC.gold }}
              >
                A&amp;O
              </span>
              <span className="text-xs font-semibold uppercase tracking-[0.14em] text-white/70">
                Payment Due to A&amp;O Division
              </span>
            </div>
            {!inline && filters ? <div className="shrink-0">{filters}</div> : null}
          </div>

          <div className={`mt-3 text-4xl font-bold sm:text-5xl ${MONO}`}>
            {formatCurrency(summary.net_payment_adjusted)}
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs">
            {delta !== null && summary.previous ? (
              <span
                className={`flex items-center gap-1 font-semibold ${MONO}`}
                style={{ color: up ? "#4ade80" : "#fca5a5" }}
              >
                {up ? <ArrowUp className="h-3.5 w-3.5" /> : <ArrowDown className="h-3.5 w-3.5" />}
                {formatCurrency(Math.abs(delta))}
                <span className="font-normal text-white/50">
                  vs {summary.previous.month_label}
                  {summary.delta_pct_vs_previous !== null
                    ? ` (${up ? "" : "−"}${formatPct(Math.abs(summary.delta_pct_vs_previous), 1)})`
                    : ""}
                </span>
              </span>
            ) : (
              <span className="text-white/40">No prior month to compare</span>
            )}

            <span
              className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium"
              style={
                summary.meets_target
                  ? { background: "#16a34a26", color: "#4ade80" }
                  : { background: "#f59e0b26", color: "#fcd34d" }
              }
            >
              <CheckCircle2 className="h-3 w-3" />
              {summary.meets_target ? "Margin target met" : "Below target — tariff applies"}
            </span>

            <span
              className="flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium"
              style={{ background: "#ffffff1a", color: "#e2e8f0" }}
            >
              <Clock className="h-3 w-3" />
              {summary.approved ? "Approved" : "Pending approval"}
            </span>
          </div>
        </div>

        {inline ? <div className="ml-auto max-w-full pt-1">{formula}</div> : null}
      </div>

      {!inline ? (
        <div className="mt-4 border-t border-white/10 pt-3">{formula}</div>
      ) : null}
    </section>
  )
}
