"use client"

import { Loader2 } from "lucide-react"
import {
  fmtDay,
  fmtUsd,
  signTone,
  useThisWeek,
  weekLabel,
  type ThisWeek,
} from "@/lib/collections-settlement-forecast-api"

function Line({ label, value, hint, strong }: { label: string; value: string; hint?: string; strong?: boolean }) {
  return (
    <div className={`flex items-baseline justify-between gap-3 py-1 ${strong ? "border-t border-[#E5E7EB] pt-2" : ""}`}>
      <span className={`text-xs ${strong ? "font-semibold text-[#111827]" : "text-[#4B5563]"}`} title={hint}>
        {label}
      </span>
      <span className={`tabular-nums ${strong ? "text-sm font-semibold text-[#1B3A5C]" : "text-xs text-[#111827]"}`}>
        {value}
      </span>
    </div>
  )
}

function NetCard({ label, value, sub }: { label: string; value: number | null; sub: string }) {
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${signTone(value)}`}>{fmtUsd(value)}</div>
      <div className="mt-1 text-[11px] text-[#6B7280]">{sub}</div>
    </div>
  )
}

function CashIn({ d }: { d: ThisWeek }) {
  const i = d.cash_in
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#047857]">Cash in</h3>
      <Line label="Collected so far" value={fmtUsd(i.collected_so_far)}
        hint="Cash applied with a GL date in this week (Cash Receipts register + McLeod intraday reconcile)" />
      <Line label={`Still due this week${i.due_customers ? ` (${i.due_customers} customers)` : ""}`}
        value={fmtUsd(i.remaining_due)} hint="Open on invoices whose terms fall due this week, after this week's payments on them" />
      <Line label="Past due, still open" value={fmtUsd(i.remaining_past_due)} />
      <Line strong label="Committed in (Daniela)" value={fmtUsd(i.committed)}
        hint="Collected + still due + ALL past due — the AR Collections Weekly Review 'Projected'" />
      <div className="mt-3" />
      <Line strong label="Expected in (Bruce)" value={fmtUsd(i.expected)}
        hint="Every shipped load's revenue on its bill date + the customer's McLeod average days to pay; unshipped weeks use the 3-week run-rate" />
      <Line label="… of which still to come" value={fmtUsd(i.still_expected)} />
      <div className="mt-3 space-y-0.5 text-[11px] text-[#6B7280]">
        <div>Typical collected week (last 8 weeks, benchmark): {fmtUsd(i.typical_week)}</div>
        {!i.receipts_included && <div className="text-[#B45309]">Receipts unavailable — committed basis unknown.</div>}
      </div>
    </div>
  )
}

function CashOut({ d }: { d: ThisWeek }) {
  const o = d.cash_out
  const runs = o.settlement_pay_dates.map(fmtDay).join(", ")
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-[#B91C1C]">Cash out</h3>
      <Line label={`Carrier settlements${runs ? ` (pay run ${runs})` : ""}`} value={fmtUsd(o.settlements)}
        hint="Settlement Projections — the pay run dated inside this week only, never the later weeks" />
      <Line label="Vendor AP due (incl. past due ≤ 4 weeks)" value={fmtUsd(o.ap_due)}
        hint="McLeod AP open items, the Financial Portal's vendor exclusion applied; a weekend due date is paid the Friday before" />
      <Line strong label="Total out" value={fmtUsd(o.total)} />
      <div className="mt-3 space-y-0.5 text-[11px] text-[#6B7280]">
        <div>AP past due more than 4 weeks, not netted: {fmtUsd(o.ap_past_due_older)}</div>
        <div>AP with no due date, not netted: {fmtUsd(o.ap_undated)}</div>
        <div>Payroll, loans, rent and other recurring obligations are not in McLeod AP — ask Finance (fin:) for them.</div>
      </div>
    </div>
  )
}

export function ThisWeekPanel() {
  const { data, isLoading, error } = useThisWeek()
  if (error) {
    return <ErrorBox error={error} />
  }
  if (isLoading || !data) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
      </div>
    )
  }
  const d = data.data
  return (
    <div className="space-y-4">
      <div className="text-xs text-[#6B7280]">
        Finance week {weekLabel(d.week_start, d.week_end)} (Saturday → Friday, UNILINK US / {d.company})
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <NetCard label="Net — committed basis" value={d.net.committed}
          sub="Every past-due dollar collected this week (Daniela's method)" />
        <NetCard label="Net — expected basis" value={d.net.expected}
          sub="Customers pay on their average days to pay (Bruce's method)" />
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <CashIn d={d} />
        <CashOut d={d} />
      </div>
    </div>
  )
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-xs text-[#991B1B]">
      Could not load: {error instanceof Error ? error.message : "unknown error"}
    </div>
  )
}
