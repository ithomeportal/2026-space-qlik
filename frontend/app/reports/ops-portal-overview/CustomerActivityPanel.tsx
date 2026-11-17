"use client"

// Bruno PDF "Ops Portal Updates" 2026-11-17 R3 — a container LEFT of
// "# Service Incident by Customer", same design: a header toggle
// "New Customer" | "Deactivated" (default New), one table at a time, scroll in
// the panel, expand → modal.
//
// New Customer — first load in the Date window after > 75 days of silence, or
//   the customer's first load ever (Diego 2026-11-17: the PDF's literal "gap
//   between the two most recent loads" dropped a new customer on its 2nd load).
//   Vol / Prof / M % / Lanes over the Date window; First Load = first ever.
// Deactivated — no load for > 75 days as of today. Ignores the Date filter
//   (under MTD it would always be empty). Profit = the last 10 trips.
// Both: Team + Customer filters apply; lane / carrier / load type do not (a
// customer is not new or gone on one lane). The captions say so.

import { useEffect, useMemo, useState, type ReactNode } from "react"
import { Loader2, Maximize2, X } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useOppCustomerActivity,
  type OppCustomerActivityKind,
  type OppDeactivatedRow,
  type OppFilters,
  type OppNewCustomerRow,
} from "@/lib/ops-portal-overview-api"
import { parseLocalDate } from "@/lib/local-date"
import { SortableTh, useSortable } from "@/components/SortableTable"

interface Props {
  filters: OppFilters
  onPickCustomer?: (customer: string) => void
}

const KINDS: ReadonlyArray<{ key: OppCustomerActivityKind; label: string; icon: string }> = [
  { key: "new", label: "New Customer", icon: "🆕" },
  { key: "deactivated", label: "Deactivated", icon: "💤" },
]

const TH_CLS = "px-2 py-1 text-[10px] font-normal uppercase tracking-normal"
const CAPTION: Record<OppCustomerActivityKind, string> = {
  new: "First load in the period after 75+ days with no load (or first load ever). Vol, Prof, M % and Lanes cover the period; First Load is the first ever. Lane, carrier and load-type filters do not apply.",
  deactivated: "No load for 75+ days as of today — not affected by the Date filter. Profit = the customer's last 10 trips. Lane, carrier and load-type filters do not apply.",
}

/** "2026-11-03" → "11/03/26" in local time (never `new Date(iso)`, §116). */
function fmtDay(iso: string | null): string {
  if (!iso) return "—"
  const d = parseLocalDate(iso)
  const mm = String(d.getMonth() + 1).padStart(2, "0")
  const dd = String(d.getDate()).padStart(2, "0")
  return `${mm}/${dd}/${String(d.getFullYear()).slice(-2)}`
}

export function CustomerActivityPanel({ filters, onPickCustomer }: Props) {
  const [kind, setKind] = useState<OppCustomerActivityKind>("new")
  const [expanded, setExpanded] = useState(false)
  const current = KINDS.find((k) => k.key === kind) ?? KINDS[0]
  const { data, isLoading, error } = useOppCustomerActivity(filters, kind)
  const rows = data?.data ?? []
  const table = (
    <ActivityTable key={kind} kind={kind} rows={rows} onPickCustomer={onPickCustomer} />
  )

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-2 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2 text-sm font-semibold text-[#3B82F6]">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          title="Expand full table"
          aria-label="Expand full table"
          className="flex h-5 w-5 items-center justify-center rounded border border-[#BFDBFE] bg-white text-[#2563EB] hover:bg-[#EFF6FF]"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
        <span aria-hidden>{current.icon}</span>
        <KindToggle value={kind} onChange={setKind} />
        {!isLoading && !error && (
          <span className="text-[11px] font-normal text-[#6B7280]">{fmtCount(rows.length)}</span>
        )}
        {isLoading && <Loader2 className="ml-auto h-3 w-3 animate-spin text-[#6B7280]" />}
      </div>
      {error ? (
        <div className="px-3 py-3 text-xs text-[#DC2626]">Failed to load</div>
      ) : (
        <div className="[contain:paint] max-h-[460px] overflow-x-hidden overflow-y-auto px-3 py-2">
          {table}
        </div>
      )}
      <p className="border-t border-[#F3F4F6] px-3 py-1.5 text-[10px] text-[#6B7280]">{CAPTION[kind]}</p>
      {expanded && (
        <ActivityModal title={current.label} icon={current.icon} onClose={() => setExpanded(false)}>
          <ActivityTable kind={kind} rows={rows} onPickCustomer={onPickCustomer} wide />
          <p className="mt-2 text-[11px] text-[#6B7280]">{CAPTION[kind]}</p>
        </ActivityModal>
      )}
    </section>
  )
}

function KindToggle({
  value,
  onChange,
}: {
  value: OppCustomerActivityKind
  onChange: (v: OppCustomerActivityKind) => void
}) {
  return (
    <div
      role="group"
      aria-label="Customer list"
      className="inline-flex overflow-hidden rounded-md border border-[#BFDBFE] text-[11px] font-medium"
    >
      {KINDS.map((k) => {
        const active = k.key === value
        return (
          <button
            key={k.key}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(k.key)}
            className={
              active
                ? "bg-[#2563EB] px-2 py-0.5 text-white"
                : "bg-white px-2 py-0.5 text-[#2563EB] hover:bg-[#EFF6FF]"
            }
          >
            {k.label}
          </button>
        )
      })}
    </div>
  )
}

function ActivityTable({
  kind,
  rows,
  onPickCustomer,
  wide = false,
}: {
  kind: OppCustomerActivityKind
  rows: OppNewCustomerRow[] | OppDeactivatedRow[]
  onPickCustomer?: (customer: string) => void
  wide?: boolean
}) {
  return kind === "new" ? (
    <NewTable rows={rows as OppNewCustomerRow[]} onPickCustomer={onPickCustomer} wide={wide} />
  ) : (
    <DeactivatedTable rows={rows as OppDeactivatedRow[]} onPickCustomer={onPickCustomer} />
  )
}

function CustomerCell({ name, onPick }: { name: string; onPick?: (c: string) => void }) {
  return (
    <td className="truncate px-2 py-1 text-[#374151]" title={name}>
      {onPick ? (
        <button
          type="button"
          onClick={() => onPick(name)}
          className="truncate text-left text-[#2563EB] hover:underline"
          title={name}
        >
          {name}
        </button>
      ) : (
        name
      )}
    </td>
  )
}

function EmptyRow({ span, text }: { span: number; text: string }) {
  return (
    <tr>
      <td colSpan={span} className="px-2 py-3 text-center text-[#9CA3AF]">
        {text}
      </td>
    </tr>
  )
}

type NewRowView = OppNewCustomerRow & { lanes_label: string }

function NewTable({
  rows,
  onPickCustomer,
  wide,
}: {
  rows: OppNewCustomerRow[]
  onPickCustomer?: (customer: string) => void
  wide: boolean
}) {
  const view = useMemo<NewRowView[]>(
    () => rows.map((r) => ({ ...r, lanes_label: r.lanes.join(" · ") })),
    [rows],
  )
  const state = useSortable(view, "last_load", "desc")
  return (
    <table className={`w-full text-xs ${wide ? "" : "table-fixed"}`}>
      {!wide && (
        <colgroup>
          <col className="w-[26%]" />
          <col className="w-[9%]" />
          <col className="w-[14%]" />
          <col className="w-[12%]" />
          <col className="w-[12%]" />
          <col className="w-[10%]" />
          <col className="w-[17%]" />
        </colgroup>
      )}
      <thead className="sticky top-0 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
        <tr>
          <SortableTh label="Name" columnKey="customer_name" state={state} className={TH_CLS} />
          <SortableTh label="Vol" columnKey="vol" state={state} align="right" className={TH_CLS} />
          <SortableTh label="Prof" columnKey="prof" state={state} align="right" className={TH_CLS} />
          <SortableTh label="First Load" columnKey="first_load" state={state} align="right" className={TH_CLS} />
          <SortableTh label="Last Load" columnKey="last_load" state={state} align="right" className={TH_CLS} />
          <SortableTh label="M %" columnKey="margin_pct" state={state} align="right" className={TH_CLS} />
          <SortableTh label="Lanes" columnKey="lanes_label" state={state} className={TH_CLS} />
        </tr>
      </thead>
      <tbody>
        {state.sorted.length === 0 ? (
          <EmptyRow span={7} text="No new customers in this period" />
        ) : (
          state.sorted.map((r) => (
            <tr key={r.customer_name} className="border-t border-[#F3F4F6]">
              <CustomerCell name={r.customer_name} onPick={onPickCustomer} />
              <td className="px-2 py-1 text-right tabular-nums">{fmtCount(r.vol)}</td>
              <td className={`px-2 py-1 text-right tabular-nums ${r.prof < 0 ? "text-[#DC2626]" : ""}`}>
                {fmtUsd(r.prof)}
              </td>
              <td className="px-2 py-1 text-right tabular-nums" title={r.gap_days ? `${r.gap_days} days with no load before this period` : "First load ever"}>
                {fmtDay(r.first_load)}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">{fmtDay(r.last_load)}</td>
              <td className={`px-2 py-1 text-right tabular-nums ${(r.margin_pct ?? 0) < 0 ? "text-[#DC2626]" : ""}`}>
                {r.margin_pct === null ? "—" : fmtPct(r.margin_pct)}
              </td>
              <td className={`px-2 py-1 text-[#374151] ${wide ? "whitespace-normal" : "truncate"}`} title={r.lanes.join("\n")}>
                {wide ? r.lanes_label : `${fmtCount(r.lanes.length)} · ${r.lanes[0] ?? ""}`}
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  )
}

function DeactivatedTable({
  rows,
  onPickCustomer,
}: {
  rows: OppDeactivatedRow[]
  onPickCustomer?: (customer: string) => void
}) {
  const state = useSortable(rows, "last_load", "desc")
  return (
    <table className="w-full table-fixed text-xs">
      <colgroup>
        <col className="w-[52%]" />
        <col className="w-[24%]" />
        <col className="w-[24%]" />
      </colgroup>
      <thead className="sticky top-0 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
        <tr>
          <SortableTh label="Name" columnKey="customer_name" state={state} className={TH_CLS} />
          <SortableTh label="Profit" columnKey="profit" state={state} align="right" className={TH_CLS} />
          <SortableTh label="Last Load Date" columnKey="last_load" state={state} align="right" className={TH_CLS} />
        </tr>
      </thead>
      <tbody>
        {state.sorted.length === 0 ? (
          <EmptyRow span={3} text="No deactivated customers" />
        ) : (
          state.sorted.map((r) => (
            <tr key={r.customer_name} className="border-t border-[#F3F4F6]">
              <CustomerCell name={r.customer_name} onPick={onPickCustomer} />
              <td
                className={`px-2 py-1 text-right tabular-nums ${r.profit < 0 ? "text-[#DC2626]" : ""}`}
                title={`Last ${r.trips} trip${r.trips === 1 ? "" : "s"}`}
              >
                {fmtUsd(r.profit)}
              </td>
              <td
                className="px-2 py-1 text-right tabular-nums"
                title={r.days_since === null ? undefined : `${r.days_since} days ago`}
              >
                {fmtDay(r.last_load)}
              </td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  )
}

function ActivityModal({
  title,
  icon,
  onClose,
  children,
}: {
  title: string
  icon: string
  onClose: () => void
  children: ReactNode
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6" onMouseDown={onClose}>
      <div
        className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#E5E7EB] bg-[#F0F9FF] px-4 py-3">
          <div className="flex items-center gap-2">
            <span aria-hidden>{icon}</span>
            <div className="text-sm font-semibold text-[#1B3A5C]">{title}</div>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-[#6B7280] hover:bg-white hover:text-[#111827]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4">{children}</div>
      </div>
    </div>
  )
}
