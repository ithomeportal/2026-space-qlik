"use client"

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-08-19) R1 — the "Hold" board, below By Order.
//
// `on_hold='Y' AND status NOT IN ('V','A')`, CORP-scoped like every other panel
// on this page. Deliberately NOT date-windowed: holds sit for months (the
// oldest open one measured 8 months), so a date filter would hide exactly the
// stale rows this board exists to surface. It therefore ignores the page's
// range pills and reacts only to Team / Customer / Lane.
//
// Modelled on CoverTable (shared SortableTable + a DERIVED totals colSpan)
// rather than ByOrder's hand-rolled header with hardcoded literals (§61).
// ---------------------------------------------------------------------------

import { Loader2 } from "lucide-react"

import {
  fmtPct,
  fmtUsd,
  useOppHold,
  type OppFilters,
  type OppHoldRow,
  type OppHoldTotals,
} from "@/lib/ops-portal-overview-api"
import { SortableTh, useSortable, type SortDir } from "@/components/SortableTable"

const HOLD_COLUMNS: {
  label: string
  key: keyof OppHoldRow
  align: "left" | "right"
}[] = [
  { label: "Order", key: "order_id", align: "left" },
  { label: "Team", key: "team_id", align: "left" },
  // Bruno PDF 2026-08-20 R2: Departure out, Date in. Right-aligned
  // because it is a signed day count, not a date string.
  { label: "Date", key: "date_days", align: "right" },
  { label: "Carrier", key: "carrier", align: "left" },
  { label: "Lane", key: "lane", align: "left" },
  { label: "Revenue", key: "revenue", align: "right" },
  { label: "Carrier Cost", key: "carrier_cost", align: "right" },
  { label: "Profit", key: "profit", align: "right" },
  { label: "Margin %", key: "margin_pct", align: "right" },
  { label: "Status", key: "status", align: "left" },
  { label: "Hold", key: "on_hold", align: "right" },
  { label: "Hold Reason", key: "hold_reason", align: "left" },
  { label: "POD", key: "pod", align: "right" },
  { label: "POD Age", key: "pod_age_hours", align: "right" },
  { label: "Days to Bill", key: "days_to_bill", align: "right" },
  { label: "Bill Date", key: "bill_date", align: "left" },
]

// Money columns lead with desc (biggest first); text columns asc.
const MONEY_KEYS = new Set<keyof OppHoldRow>([
  "revenue", "carrier_cost", "profit", "margin_pct",
])
function holdDirForKey(key: string): SortDir {
  return MONEY_KEYS.has(key as keyof OppHoldRow) ? "desc" : "asc"
}

// The pinned TOTAL label spans everything left of the money block. Derived, not
// hardcoded: a hand-bumped literal silently shifts the whole totals row when a
// column is added (§61).
const MONEY_START = HOLD_COLUMNS.findIndex((c) => c.key === "revenue")
const TOTAL_LABEL_COLSPAN = MONEY_START
const TRAILING_COLSPAN = HOLD_COLUMNS.length - MONEY_START - MONEY_KEYS.size

// Compact POD-age label — same thresholds and shape as By Order's, so the two
// tables cannot read differently for the same order.
function fmtPodAge(hours: number): string {
  if (hours < 48) return `${Math.round(hours)}h`
  return `${Math.round(hours / 24)}d`
}

export function HoldTable({ filters }: { filters: OppFilters }) {
  const { data, isLoading, error } = useOppHold(filters)
  const rows: OppHoldRow[] = data?.data ?? []
  const totals = data?.meta?.totals as OppHoldTotals | undefined
  const unbilledFrom = (data?.meta as { unbilled_from?: string } | undefined)?.unbilled_from

  // Most-overdue first (the most negative Date). Mirrors the backend's
  // `date_asc` default so the first paint does not jump.
  const { sorted, ...sortState } = useSortable<OppHoldRow>(
    rows,
    "date_days",
    "asc",
    holdDirForKey,
  )

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
        <span className="rounded-md bg-[#1B3A5C] px-2 py-0.5 text-xs font-semibold uppercase text-white">
          Hold
        </span>
        <span className="text-[11px] text-[#6B7280]">
          Orders not yet billed in McLeod (excludes voided and pending-cover)
        </span>
        <span
          className="text-[10px] text-[#9CA3AF]"
          title="Unbilled orders routinely sit for months, so this board reads the whole table rather than the selected date range. Team, Customer and Lane filters still apply."
        >
          all dates
        </span>
        {/* ⚠ Never silent: the board excludes pre-2022 orders because McLeod's
            2021 feed never wrote bill_date at all (99.4% sentinel that year vs
            ~0.0% in 2022-2025), and without the floor ~58,500 phantom rows
            bury the real backlog. A worklist that drops rows must say so. */}
        {unbilledFrom && (
          <span
            className="rounded-full border border-[#E5E7EB] bg-white px-2 py-0.5 text-[10px] text-[#6B7280]"
            title={`Orders placed before ${unbilledFrom} are excluded: McLeod's 2021 feed never populated bill_date, so they are not genuinely unbilled.`}
          >
            from {unbilledFrom}
          </span>
        )}
        {isLoading && <Loader2 className="h-3 w-3 animate-spin text-[#6B7280]" />}
      </div>

      {error ? (
        <div className="px-3 py-6 text-center text-xs text-[#991B1B]">
          Could not load the Hold board:{" "}
          {error instanceof Error ? error.message : "unknown error"}
        </div>
      ) : (
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                {HOLD_COLUMNS.map((c) => (
                  <SortableTh
                    key={c.key}
                    label={c.label}
                    columnKey={c.key}
                    state={sortState}
                    align={c.align}
                  />
                ))}
              </tr>
              {/* §44: server-side full-universe aggregate, never a client
                  reduce() over a possibly LIMIT-capped list. */}
              {totals && (
                <tr className="border-b border-[#E5E7EB] bg-[#EFF6FF] font-semibold text-[#1B3A5C]">
                  <td className="px-2 py-1.5" colSpan={TOTAL_LABEL_COLSPAN}>
                    TOTAL · {totals.n_orders.toLocaleString()} on hold
                  </td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(totals.revenue)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(totals.carrier_cost)}</td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${totals.profit < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtUsd(totals.profit)}
                  </td>
                  <td className={`px-2 py-1.5 text-right tabular-nums ${totals.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
                    {fmtPct(totals.margin_pct)}
                  </td>
                  <td className="px-2 py-1.5" colSpan={TRAILING_COLSPAN} />
                </tr>
              )}
            </thead>
            <tbody>
              {isLoading && sorted.length === 0 ? (
                <tr>
                  <td colSpan={HOLD_COLUMNS.length} className="px-3 py-6 text-center">
                    <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                  </td>
                </tr>
              ) : sorted.length === 0 ? (
                <tr>
                  <td colSpan={HOLD_COLUMNS.length} className="px-3 py-6 text-center text-[#9CA3AF]">
                    No loads on hold
                  </td>
                </tr>
              ) : (
                sorted.map((r) => (
                  <tr key={r.order_id} className="border-b border-[#F3F4F6] hover:bg-[#FAFBFC]">
                    <td className="px-2 py-1.5 font-medium text-[#1B3A5C]">{r.order_id}</td>
                    <td className="px-2 py-1.5 text-[#374151]">{r.team_id}</td>
                    {/* Days. Negative = overdue against the scheduled
                        delivery (status P) — never a date, and never a value
                        when the source carried McLeod's 1900-01-01 sentinel,
                        which the backend maps to null. */}
                    <td
                      className={`px-2 py-1.5 text-right tabular-nums ${
                        r.date_days !== null && r.date_days < 0
                          ? "text-[#DC2626]"
                          : "text-[#374151]"
                      }`}
                      title={
                        r.status === "P"
                          ? "Scheduled delivery minus today. Negative = overdue."
                          : r.status === "D"
                            ? "Transit days: destination departure minus origin departure."
                            : ""
                      }
                    >
                      {r.date_days !== null && r.date_days !== undefined
                        ? r.date_days
                        : <span className="text-[#9CA3AF]">—</span>}
                    </td>
                    <td className="px-2 py-1.5 text-[#374151]">
                      {r.carrier || <span className="text-[#9CA3AF]">—</span>}
                    </td>
                    <td className="px-2 py-1.5 text-[#374151]">
                      {r.lane || <span className="text-[#9CA3AF]">—</span>}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(r.revenue)}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-[#374151]">
                      {fmtUsd(r.carrier_cost)}
                    </td>
                    <td
                      className={`px-2 py-1.5 text-right tabular-nums ${
                        r.profit < 0 ? "font-medium text-[#DC2626]" : "text-[#374151]"
                      }`}
                    >
                      {fmtUsd(r.profit)}
                    </td>
                    <td
                      className={`px-2 py-1.5 text-right tabular-nums ${
                        r.margin_pct < 0 ? "font-medium text-[#DC2626]" : "text-[#374151]"
                      }`}
                    >
                      {fmtPct(r.margin_pct)}
                    </td>
                    <td className="px-2 py-1.5 text-[#374151]">{r.status}</td>
                    {/* Bruno R1: "displayed as a checkmark". */}
                    <td className="px-2 py-1.5 text-right">
                      {r.on_hold ? (
                        <span className="font-semibold text-[#B45309]" aria-label="On hold">✓</span>
                      ) : (
                        <span className="sr-only">Not on hold</span>
                      )}
                    </td>
                    {/* Free text typed by ops — shown verbatim, never normalised. */}
                    <td className="px-2 py-1.5 text-[#374151]">
                      {r.hold_reason || <span className="text-[#9CA3AF]">—</span>}
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      {r.pod ? (
                        <span className="font-semibold text-[#16A34A]" aria-label="Has POD document">✓</span>
                      ) : (
                        <span className="sr-only">No POD document</span>
                      )}
                    </td>
                    {/* Only meaningful while the POD is still missing. */}
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {r.pod || r.pod_age_hours == null ? (
                        <span className="text-[#9CA3AF]">—</span>
                      ) : (
                        <span className={r.pod_age_hours < 24 ? "text-[#16A34A]" : "font-medium text-[#DC2626]"}>
                          {fmtPodAge(r.pod_age_hours)}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-[#374151]">
                      {r.days_to_bill == null ? (
                        <span className="text-[#9CA3AF]">—</span>
                      ) : (
                        r.days_to_bill
                      )}
                    </td>
                    <td className="px-2 py-1.5 tabular-nums text-[#6B7280]">
                      {r.bill_date ?? <span className="text-[#9CA3AF]">—</span>}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
