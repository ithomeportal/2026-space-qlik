"use client"

import { Fragment, useEffect, useState } from "react"
import { ChevronDown, ChevronRight, Loader2 } from "lucide-react"

import {
  formatCurrency,
  formatSignedCurrency,
  useCutoffOrders,
  useCutoffs,
  useSaveCutoffNote,
  type CutoffMonth,
  type CutoffOrderChange,
  type CutoffStatus,
  type OrderMoney,
} from "@/lib/division-payment-api"
import { parseLocalDate } from "@/lib/local-date"
import { DPC, MONO } from "./theme"

/** Month-list columns. The expanded detail row spans `MONTH_COLUMNS.length`
 *  — derived, never hardcoded, so adding a column cannot misalign it (§61). */
const MONTH_COLUMNS: { key: string; label: string; right?: boolean }[] = [
  { key: "month", label: "Month" },
  { key: "cutoff", label: "Cutoff" },
  { key: "revenue", label: "Revenue", right: true },
  { key: "carrier_cost", label: "Carrier Cost", right: true },
  { key: "profit", label: "Profit", right: true },
  { key: "status", label: "Status" },
  { key: "changed", label: "Changed orders", right: true },
  { key: "delta_profit", label: "Δ Profit", right: true },
  { key: "ao", label: "A&O 75%", right: true },
  { key: "corp", label: "Corp 25%", right: true },
]

const ORDER_COLUMNS: { key: string; label: string; right?: boolean }[] = [
  { key: "order", label: "Order" },
  { key: "customer", label: "Customer" },
  { key: "change", label: "Change" },
  { key: "revenue", label: "Revenue", right: true },
  { key: "carrier_pay", label: "Carrier Pay", right: true },
  { key: "margin", label: "Margin", right: true },
  { key: "delta_margin", label: "Δ Margin", right: true },
]
/** The totals label spans every column before the first money column. */
const ORDER_TOTALS_SPAN = ORDER_COLUMNS.findIndex((c) => c.key === "revenue")

const STATUS_STYLE: Record<CutoffStatus, { bg: string; fg: string }> = {
  open: { bg: "#dbeafe", fg: "#1d4ed8" },
  before_tracking: { bg: "#f1f5f9", fg: "#64748b" },
  snapshot_pending: { bg: "#fef3c7", fg: "#b45309" },
  tracked: { bg: "#dcfce7", fg: "#15803d" },
}

const CHANGE_STYLE: Record<CutoffOrderChange["change_type"], { bg: string; fg: string }> = {
  modified: { bg: "#dbeafe", fg: "#1d4ed8" },
  added: { bg: "#dcfce7", fg: "#15803d" },
  removed: { bg: "#fee2e2", fg: "#b91c1c" },
}

/** "2026-10-10" → "Oct 10, 2026". parseLocalDate, never `new Date(str)` —
 *  a date-only string is UTC midnight and would print Oct 9 in CST (§116). */
function formatDay(isoDate: string): string {
  return parseLocalDate(isoDate).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

/** captured_at is shown as the server sent it (to the minute) — reformatting a
 *  timestamp whose zone we do not know would invent an hour. */
function formatCaptured(ts: string | null | undefined): string {
  return ts ? ts.replace("T", " ").slice(0, 16) : "—"
}

function statusLabel(m: CutoffMonth): string {
  switch (m.status) {
    case "open":
      return `Open — closes ${formatDay(m.cutoff_date)}`
    case "before_tracking":
      return "No cutoff data"
    case "snapshot_pending":
      return "Snapshot pending"
    case "tracked":
      return "Tracked"
  }
}

const deltaColor = (v: number | null | undefined) =>
  v === null || v === undefined || v === 0 ? "#94a3b8" : v > 0 ? DPC.positive : DPC.danger

/**
 * "Recalculations" — Bruno PDF 2026-10-05. Replaces the vendor's fake
 * `/recalcs` records with the backend's cutoff model: a month closes on the
 * 10th of the following month, its v4 orders are frozen as a snapshot, and
 * every later change is listed here with its 25% / 75% split. All figures —
 * live, delta and the shares — come from the backend; nothing is derived here.
 */
export function CutoffMonths() {
  const q = useCutoffs()
  const [expanded, setExpanded] = useState<string | null>(null)
  const months = q.data?.months ?? []

  return (
    <section className="rounded-xl border bg-white" style={{ borderColor: DPC.border }}>
      <header className="border-b px-4 py-3" style={{ borderColor: DPC.border }}>
        <h3 className="text-base font-bold" style={{ color: DPC.navy }}>
          Recalculations
        </h3>
        <p className="text-[11px] text-[#94a3b8]">
          Orders that changed after each month&apos;s cutoff (10th of the following month).
          Tracking starts with September 2026 — earlier months have no cutoff snapshot.
        </p>
      </header>

      {q.isLoading ? (
        <p className="flex items-center gap-2 px-4 py-6 text-sm text-[#94a3b8]">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading recalculations…
        </p>
      ) : q.isError ? (
        <div className="px-4 py-6 text-sm text-[#64748b]">
          Could not load the cutoff months.{" "}
          <button type="button" onClick={() => q.refetch()} className="font-semibold underline"
                  style={{ color: DPC.navy }}>
            Retry
          </button>
        </div>
      ) : months.length === 0 ? (
        <p className="px-4 py-6 text-sm text-[#94a3b8]">No months yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1100px] text-xs">
            <thead>
              <tr className="border-b text-[10px] uppercase tracking-wide text-[#64748b]"
                  style={{ borderColor: DPC.border }}>
                {MONTH_COLUMNS.map((c) => (
                  <th key={c.key}
                      className={`px-3 py-2 font-semibold ${c.right ? "text-right" : "text-left"}`}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {months.map((m) => {
                const key = `${m.year}-${m.month}`
                const open = expanded === key
                return (
                  <Fragment key={key}>
                    <MonthRow month={m} open={open}
                              onToggle={() => setExpanded((p) => (p === key ? null : key))} />
                    {open && m.status === "tracked" ? (
                      <tr className="border-b" style={{ borderColor: DPC.border }}>
                        <td colSpan={MONTH_COLUMNS.length} className="bg-[#f8fafc] px-4 py-3">
                          <CutoffDetail month={m} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function MonthRow({
  month: m, open, onToggle,
}: {
  month: CutoffMonth
  open: boolean
  onToggle: () => void
}) {
  const tracked = m.status === "tracked"
  const st = STATUS_STYLE[m.status]
  const signed = (v: number | null | undefined, bold?: boolean) => (
    <td className={`px-3 py-2 text-right ${MONO} ${bold ? "font-semibold" : ""}`}
        style={{ color: tracked ? deltaColor(v) : "#94a3b8" }}>
      {tracked ? formatSignedCurrency(v) : "—"}
    </td>
  )
  return (
    <tr className="border-b" style={{ borderColor: "#f1f5f9" }}>
      <td className="px-3 py-2">
        {tracked ? (
          <button type="button" onClick={onToggle} aria-expanded={open}
                  className="flex items-center gap-1.5 font-semibold" style={{ color: DPC.navy }}>
            {open ? <ChevronDown className="h-4 w-4 text-[#94a3b8]" />
                  : <ChevronRight className="h-4 w-4 text-[#94a3b8]" />}
            {m.month_label}
          </button>
        ) : (
          <span className="pl-[22px] font-semibold" style={{ color: DPC.navy }}>
            {m.month_label}
          </span>
        )}
      </td>
      <td className="px-3 py-2 text-[#475569]">{formatDay(m.cutoff_date)}</td>
      <td className={`px-3 py-2 text-right ${MONO}`}>{formatCurrency(m.live.revenue)}</td>
      <td className={`px-3 py-2 text-right ${MONO}`}>{formatCurrency(m.live.carrier_cost)}</td>
      <td className={`px-3 py-2 text-right ${MONO}`}>{formatCurrency(m.live.profit)}</td>
      <td className="px-3 py-2">
        <span className="whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-semibold"
              style={{ background: st.bg, color: st.fg }}
              title={m.snapshot ? `Snapshot captured ${formatCaptured(m.snapshot.captured_at)}` : undefined}>
          {statusLabel(m)}
        </span>
      </td>
      <td className={`px-3 py-2 text-right ${MONO}`}>
        {tracked && m.changed_count !== null ? m.changed_count : "—"}
      </td>
      {signed(m.delta?.profit, true)}
      {signed(m.ao_share, true)}
      {signed(m.corporate_share)}
    </tr>
  )
}

/** Lazy-loaded order changes + the Refacturación note for one tracked month. */
function CutoffDetail({ month: m }: { month: CutoffMonth }) {
  const q = useCutoffOrders(m.year, m.month, true)

  return (
    <div className="space-y-3">
      {q.isLoading ? (
        <p className="flex items-center gap-2 text-xs text-[#94a3b8]">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading changed orders…
        </p>
      ) : q.isError || !q.data ? (
        <p className="text-xs text-[#b91c1c]">Could not load the changed orders for this month.</p>
      ) : q.data.changes.length === 0 ? (
        <p className="text-xs text-[#64748b]">No orders changed since the cutoff.</p>
      ) : (
        <OrderChanges changes={q.data.changes} totals={q.data.totals} />
      )}
      <NoteEditor month={m} />
    </div>
  )
}

function OrderChanges({ changes, totals }: { changes: CutoffOrderChange[]; totals: OrderMoney }) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-white" style={{ borderColor: DPC.border }}>
      <table className="w-full min-w-[860px] text-xs">
        <thead>
          <tr className="border-b text-[10px] uppercase tracking-wide text-[#64748b]"
              style={{ borderColor: DPC.border, background: "#f8fafc" }}>
            {ORDER_COLUMNS.map((c) => (
              <th key={c.key}
                  className={`px-3 py-2 font-semibold ${c.right ? "text-right" : "text-left"}`}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {changes.map((c) => (
            <tr key={`${c.company_id}-${c.order_id}`} className="border-b last:border-0"
                style={{ borderColor: "#f1f5f9" }}>
              <td className={`px-3 py-2 ${MONO}`}>{c.order_id}</td>
              <td className="px-3 py-2">{c.customer_name}</td>
              <td className="px-3 py-2">
                <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold capitalize"
                      style={{ background: CHANGE_STYLE[c.change_type].bg,
                               color: CHANGE_STYLE[c.change_type].fg }}>
                  {c.change_type}
                </span>
              </td>
              <BeforeAfter before={c.before?.total_charge} after={c.after?.total_charge} />
              <BeforeAfter before={c.before?.total_carrier_pay} after={c.after?.total_carrier_pay} />
              <BeforeAfter before={c.before?.margin_amt} after={c.after?.margin_amt} />
              <td className={`px-3 py-2 text-right font-semibold ${MONO}`}
                  style={{ color: deltaColor(c.delta.margin_amt) }}>
                {formatSignedCurrency(c.delta.margin_amt)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t" style={{ borderColor: DPC.border, background: "#f8fafc" }}>
            <td colSpan={ORDER_TOTALS_SPAN} className="px-3 py-2 font-semibold"
                style={{ color: DPC.navy }}>
              Total change ({changes.length} orders)
            </td>
            {[totals.total_charge, totals.total_carrier_pay].map((v, i) => (
              <td key={i} className={`px-3 py-2 text-right ${MONO}`} style={{ color: deltaColor(v) }}>
                {formatSignedCurrency(v)}
              </td>
            ))}
            <td />
            <td className={`px-3 py-2 text-right font-bold ${MONO}`}
                style={{ color: deltaColor(totals.margin_amt) }}>
              {formatSignedCurrency(totals.margin_amt)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}

function BeforeAfter({ before, after }: { before?: number; after?: number }) {
  return (
    <td className={`whitespace-nowrap px-3 py-2 text-right ${MONO}`}>
      <span className="text-[#94a3b8]">{formatCurrency(before)}</span>
      <span className="mx-1 text-[#cbd5e1]">→</span>
      <span style={{ color: DPC.navy }}>{formatCurrency(after)}</span>
    </td>
  )
}

function NoteEditor({ month: m }: { month: CutoffMonth }) {
  const [note, setNote] = useState(m.note)
  const save = useSaveCutoffNote()
  const id = `cutoff-note-${m.year}-${m.month}`

  // Re-seed when the server's note changes (after a save, or another user's).
  useEffect(() => {
    setNote(m.note)
  }, [m.note])

  return (
    <div>
      <label htmlFor={id} className="text-[10px] font-semibold uppercase tracking-wide text-[#64748b]">
        Refacturación notes
      </label>
      <textarea id={id} value={note} onChange={(e) => setNote(e.target.value)} rows={2}
                placeholder="Why these orders changed after the cutoff…"
                className="mt-1 w-full rounded-lg border bg-white px-3 py-2 text-xs"
                style={{ borderColor: DPC.border }} />
      <button type="button" disabled={note === m.note || save.isPending}
              onClick={() => save.mutate({ year: m.year, month: m.month, note })}
              className="mt-1.5 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
              style={{ background: DPC.navy }}>
        {save.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : null}
        Save note
      </button>
    </div>
  )
}
