"use client"

import { useState } from "react"
import {
  ArrowRight,
  BarChart3,
  Calculator,
  Camera,
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
} from "lucide-react"

import { SortableTh, useSortable } from "@/components/SortableTable"
import {
  formatCurrency,
  formatPct,
  useArchives,
  useRecalcs,
  useSaveRecalcNote,
  type Archive,
  type Recalc,
} from "@/lib/division-payment-api"
import { DPC, MONO } from "./theme"

const STEPS = [
  { n: 1, icon: Calculator, text: "Calculate & approve the month" },
  { n: 2, icon: Camera, text: "Archive is taken & payments made" },
  { n: 3, icon: RefreshCw, text: "30 days later, TMS data arrives" },
  { n: 4, icon: BarChart3, text: "Compare archive vs new TMS data" },
  { n: 5, icon: ArrowRight, text: "Differential applied to current month" },
]

/** Recalculations tab — PDF Requests 1 and 2, plus the recalculation records
 *  the Dashboard's "View Recalculations (N)" button points at. */
export function RecalculationsTab() {
  const archivesQ = useArchives()
  const recalcsQ = useRecalcs()

  return (
    <div className="space-y-4">
      <HowItWorks />
      <RecalcRecords recalcs={recalcsQ.data ?? []} loading={recalcsQ.isLoading} />
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

function RecalcRecords({ recalcs, loading }: { recalcs: Recalc[]; loading: boolean }) {
  const [expanded, setExpanded] = useState<string | null>(null)

  if (loading) return <PanelSkeleton label="Loading recalculations…" />
  if (recalcs.length === 0) return null

  return (
    <section className="rounded-xl border bg-white" style={{ borderColor: DPC.border }}>
      <header className="border-b px-4 py-3" style={{ borderColor: DPC.border }}>
        <h3 className="text-base font-bold" style={{ color: DPC.navy }}>
          Recalculations
        </h3>
        <p className="text-[11px] text-[#94a3b8]">
          The tariff stays fixed from the approved archive — only the profit delta is split,
          25% to Corporate and 75% to A&amp;O.
        </p>
      </header>

      <div className="divide-y" style={{ borderColor: DPC.border }}>
        {recalcs.map((r) => (
          <RecalcRow
            key={r.recalc_key}
            recalc={r}
            open={expanded === r.recalc_key}
            onToggle={() =>
              setExpanded((prev) => (prev === r.recalc_key ? null : r.recalc_key))
            }
          />
        ))}
      </div>
    </section>
  )
}

function RecalcRow({
  recalc, open, onToggle,
}: {
  recalc: Recalc
  open: boolean
  onToggle: () => void
}) {
  const positive = recalc.diff.profit >= 0
  const [note, setNote] = useState(recalc.note)
  const saveNote = useSaveRecalcNote()

  return (
    <div>
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full flex-wrap items-center gap-3 px-4 py-3 text-left hover:bg-[#f8fafc]"
      >
        {open ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-[#94a3b8]" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-[#94a3b8]" />
        )}
        <span className="text-sm font-semibold" style={{ color: DPC.navy }}>
          {recalc.month_label}
        </span>
        <span className="text-[11px] text-[#94a3b8]">
          → applied to {recalc.applied_to_month_label}
        </span>
        <span
          className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
          style={
            recalc.status === "applied"
              ? { background: "#dcfce7", color: "#15803d" }
              : { background: "#fef3c7", color: "#b45309" }
          }
        >
          {recalc.status === "applied" ? "Applied" : "Pending"}
        </span>
        {recalc.previously_recalculated ? (
          <span
            className="rounded-full px-2 py-0.5 text-[10px] font-semibold"
            style={{ background: "#f3e8ff", color: "#7c3aed" }}
          >
            2nd recalc
          </span>
        ) : null}
        <span
          className={`ml-auto text-sm font-bold ${MONO}`}
          style={{ color: positive ? DPC.positive : DPC.danger }}
        >
          {positive ? "+" : "−"}
          {formatCurrency(Math.abs(recalc.diff.net_payment))}
        </span>
      </button>

      {open ? (
        <div className="space-y-3 px-4 pb-4">
          <div className="grid gap-3 lg:grid-cols-3">
            <SideCard title="Original Archive" side={recalc.snapshot} />
            <SideCard title="TMS Updated" side={recalc.tms_update} />
            <div className="rounded-lg border p-3" style={{ borderColor: DPC.border, background: "#f8fafc" }}>
              <p className="text-[10px] font-semibold uppercase tracking-wide text-[#64748b]">
                Differential
              </p>
              <dl className="mt-2 space-y-1 text-xs">
                <DiffRow label="Revenue" value={recalc.diff.revenue} />
                <DiffRow label="Carrier Cost" value={recalc.diff.carrier_cost} />
                <DiffRow label="Profit" value={recalc.diff.profit} bold />
                <DiffRow label="Deductions" value={0} note="unchanged" />
                <DiffRow label="Tariff" value={0} note="fixed from archive" />
                <DiffRow label="Corporate (25%)" value={recalc.corporate_share} />
                <DiffRow label="A&O (75%)" value={recalc.ao_share} bold />
              </dl>
            </div>
          </div>

          {recalc.previously_recalculated && recalc.prior_recalc_net_payment !== null ? (
            <p
              className="rounded-lg px-3 py-2 text-[11px]"
              style={{ background: "#f3e8ff", color: "#6b21a8" }}
            >
              Second recalculation — compared against the prior recalculation&apos;s result of{" "}
              <strong className={MONO}>{formatCurrency(recalc.prior_recalc_net_payment)}</strong>,
              not the original archive.
            </p>
          ) : null}

          {recalc.loads.length > 0 ? (
            <div className="overflow-x-auto rounded-lg border" style={{ borderColor: DPC.border }}>
              <table className="w-full min-w-[680px] text-xs">
                <thead>
                  <tr className="border-b text-[10px] uppercase tracking-wide text-[#64748b]"
                      style={{ borderColor: DPC.border, background: "#f8fafc" }}>
                    <th className="px-3 py-2 text-left font-semibold">Load</th>
                    <th className="px-3 py-2 text-left font-semibold">Customer</th>
                    <th className="px-3 py-2 text-left font-semibold">Change</th>
                    <th className="px-3 py-2 text-right font-semibold">Δ Revenue</th>
                    <th className="px-3 py-2 text-right font-semibold">Δ Carrier Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {recalc.loads.map((l) => (
                    <tr key={l.load_number} className="border-b last:border-0"
                        style={{ borderColor: "#f1f5f9" }}>
                      <td className={`px-3 py-2 ${MONO}`}>{l.load_number}</td>
                      <td className="px-3 py-2">{l.client}</td>
                      <td className="px-3 py-2 text-[#64748b]">{l.change_description}</td>
                      <td className={`px-3 py-2 text-right ${MONO}`}>
                        {formatCurrency(l.revenue_delta)}
                      </td>
                      <td className={`px-3 py-2 text-right ${MONO}`}>
                        {formatCurrency(l.cost_delta)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          <div>
            <label
              htmlFor={`note-${recalc.recalc_key}`}
              className="text-[10px] font-semibold uppercase tracking-wide text-[#64748b]"
            >
              Refacturación notes
            </label>
            <textarea
              id={`note-${recalc.recalc_key}`}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={2}
              className="mt-1 w-full rounded-lg border px-3 py-2 text-xs"
              style={{ borderColor: DPC.border }}
              placeholder="Why this recalculation happened…"
            />
            <button
              type="button"
              disabled={note === recalc.note || saveNote.isPending}
              onClick={() => saveNote.mutate({ key: recalc.recalc_key, note })}
              className="mt-1.5 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
              style={{ background: DPC.navy }}
            >
              {saveNote.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
              Save note
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function SideCard({ title, side }: { title: string; side: Recalc["snapshot"] }) {
  return (
    <div className="rounded-lg border p-3" style={{ borderColor: DPC.border }}>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-[#64748b]">{title}</p>
      <dl className="mt-2 space-y-1 text-xs">
        <Row label="Revenue" value={formatCurrency(side.revenue)} />
        <Row label="Carrier Cost" value={formatCurrency(side.carrier_cost)} />
        <Row label="Profit" value={formatCurrency(side.profit)} />
        <Row label="Margin" value={formatPct(side.margin_pct)} />
        <Row label="Deductions" value={formatCurrency(side.gl_deductions)} />
        <Row label="Tariff" value={formatCurrency(side.penalty_fee)} />
        <Row label="Corporate Gain" value={formatCurrency(side.corporate_gain)} />
        <Row label="Net Payment" value={formatCurrency(side.net_payment)} bold />
      </dl>
    </div>
  )
}

function Row({ label, value, bold }: { label: string; value: string; bold?: boolean }) {
  return (
    <div className="flex justify-between">
      <dt className="text-[#64748b]">{label}</dt>
      <dd className={`${MONO} ${bold ? "font-bold" : ""}`} style={{ color: DPC.navy }}>
        {value}
      </dd>
    </div>
  )
}

function DiffRow({
  label, value, bold, note,
}: {
  label: string
  value: number
  bold?: boolean
  note?: string
}) {
  const color = value === 0 ? "#94a3b8" : value > 0 ? DPC.positive : DPC.danger
  return (
    <div className="flex justify-between">
      <dt className="text-[#64748b]">{label}</dt>
      <dd className={`${MONO} ${bold ? "font-bold" : ""}`} style={{ color }}>
        {note ?? `${value > 0 ? "+" : value < 0 ? "−" : ""}${formatCurrency(Math.abs(value))}`}
      </dd>
    </div>
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
