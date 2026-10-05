"use client"

import {
  CalendarCheck,
  Camera,
  GitCompareArrows,
  ListChecks,
  Loader2,
  Truck,
} from "lucide-react"

import { SortableTh, useSortable } from "@/components/SortableTable"
import {
  formatCurrency,
  formatPct,
  useArchives,
  type Archive,
} from "@/lib/division-payment-api"
import { CutoffMonths } from "./CutoffMonths"
import { DPC, MONO } from "./theme"

// Bruno PDF 2026-10-05 — the cutoff model replaces the vendor's "30 days later,
// TMS data arrives" story, which no system ever implemented.
const STEPS = [
  { n: 1, icon: Truck, text: "Month runs — orders post to v4" },
  { n: 2, icon: CalendarCheck, text: "On the 10th of the next month the month closes" },
  { n: 3, icon: Camera, text: "Orders are frozen as the cutoff snapshot" },
  { n: 4, icon: GitCompareArrows, text: "Later changes are compared against the snapshot" },
  { n: 5, icon: ListChecks, text: "Changed orders are listed here (25% Corporate / 75% A&O)" },
]

/** Recalculations tab — PDF Requests 1 and 2. The month list (Bruno PDF
 *  2026-10-05) reads `GET /cutoffs`; the old `/recalcs` vendor records are no
 *  longer shown (the hook stays in the api file). */
export function RecalculationsTab() {
  const archivesQ = useArchives()

  return (
    <div className="space-y-4">
      <HowItWorks />
      <CutoffMonths />
      <ApprovedArchives rows={archivesQ.data ?? []} loading={archivesQ.isLoading} />
    </div>
  )
}

function HowItWorks() {
  return (
    <section
      className="rounded-xl p-4 text-white"
      style={{
        background: `linear-gradient(135deg, ${DPC.container}, ${DPC.containerTo})`,
        borderLeft: `4px solid ${DPC.gold}`,
      }}
    >
      <h3 className="text-base font-bold">How Recalculations Work</h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {STEPS.map((s) => {
          const Icon = s.icon
          return (
            <div key={s.n}>
              <div className="flex items-center gap-2">
                <span
                  className="grid h-6 w-6 place-items-center rounded-full text-[11px] font-bold"
                  style={{ background: `${DPC.gold}33`, color: DPC.gold }}
                >
                  {s.n}
                </span>
                <Icon className="h-3.5 w-3.5 text-white/40" />
              </div>
              <p className="mt-2 text-[11px] leading-snug text-white/70">{s.text}</p>
            </div>
          )
        })}
      </div>
    </section>
  )
}

/** PDF Recalculations Request 2 — the approved-archive table. */
function ApprovedArchives({ rows, loading }: { rows: Archive[]; loading: boolean }) {
  // §38 — reuse the shared sortable helpers rather than a local implementation.
  // Money columns that can go negative start ascending so the worst row is on
  // top, which is what someone clicking "Net Payment" is looking for.
  const state = useSortable<Archive>(rows, null, "desc", (key) =>
    key === "net_payment" || key === "profit" || key === "margin_pct" ? "asc" : "desc",
  )

  if (loading) return <PanelSkeleton label="Loading approved archives…" />

  return (
    <section className="rounded-xl border bg-white" style={{ borderColor: DPC.border }}>
      <header className="border-b px-4 py-3" style={{ borderColor: DPC.border }}>
        <h3 className="flex items-center gap-2 text-base font-bold" style={{ color: DPC.navy }}>
          <Camera className="h-4 w-4 text-[#94a3b8]" />
          Approved Archives
        </h3>
        <p className="text-[11px] text-[#94a3b8]">
          These are the original approved calculations that were paid. Each snapshot is the
          baseline for recalculation comparisons.
        </p>
      </header>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-xs">
          <thead>
            <tr className="border-b text-[10px] uppercase tracking-wide text-[#64748b]"
                style={{ borderColor: DPC.border }}>
              <SortableTh label="Month" columnKey="month_label" state={state} />
              <SortableTh label="Revenue" columnKey="revenue" state={state} align="right" />
              <SortableTh label="Carrier Cost" columnKey="carrier_cost" state={state} align="right" />
              <SortableTh label="Profit" columnKey="profit" state={state} align="right" />
              <SortableTh label="Margin" columnKey="margin_pct" state={state} align="right" />
              <SortableTh label="GL Deduct." columnKey="gl_deductions" state={state} align="right" />
              <SortableTh label="Tariff" columnKey="penalty_fee" state={state} align="right" />
              <SortableTh label="Corp. Gain" columnKey="corporate_gain" state={state} align="right" />
              <SortableTh label="Net Payment" columnKey="net_payment" state={state} align="right" />
            </tr>
          </thead>
          <tbody>
            {state.sorted.map((r) => (
              <tr
                key={`${r.year}-${r.month}`}
                className="border-b last:border-0"
                style={{ borderColor: "#f1f5f9" }}
              >
                <td className="px-3 py-2 font-semibold" style={{ color: DPC.navy }}>
                  {r.month_label}
                </td>
                <td className={`px-3 py-2 text-right ${MONO}`}>{formatCurrency(r.revenue)}</td>
                <td className={`px-3 py-2 text-right ${MONO}`}>{formatCurrency(r.carrier_cost)}</td>
                <td className={`px-3 py-2 text-right ${MONO}`}>{formatCurrency(r.profit)}</td>
                <td
                  className={`px-3 py-2 text-right ${MONO}`}
                  style={{ color: r.margin_pct >= 10 ? DPC.positive : DPC.danger }}
                >
                  {formatPct(r.margin_pct)}
                </td>
                <td className={`px-3 py-2 text-right ${MONO}`}>{formatCurrency(r.gl_deductions)}</td>
                <td className={`px-3 py-2 text-right ${MONO}`}>{formatCurrency(r.penalty_fee)}</td>
                <td className={`px-3 py-2 text-right ${MONO}`} style={{ color: DPC.gold }}>
                  {formatCurrency(r.corporate_gain)}
                </td>
                <td
                  className={`px-3 py-2 text-right font-semibold ${MONO}`}
                  style={{ color: r.net_payment >= 0 ? DPC.navy : DPC.danger }}
                >
                  {formatCurrency(r.net_payment)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function PanelSkeleton({ label }: { label: string }) {
  return (
    <div
      className="flex items-center gap-2 rounded-xl border bg-white px-4 py-6 text-sm text-[#94a3b8]"
      style={{ borderColor: DPC.border }}
    >
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  )
}
