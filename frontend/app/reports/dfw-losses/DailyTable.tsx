"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { Loader2 } from "lucide-react"
import {
  useDfwLossesDaily,
  dfwLossesOrdersHref,
  type DfwLossesFilters,
  type DfwLossesDailyRow,
} from "@/lib/dfw-losses-api"
import { SortableTh, type SortDir, type SortState } from "@/components/SortableTable"
import { DfwLossesErrorBanner } from "./ErrorBanner"
import { fmtUsd, fmtCount, fmtLossCell } from "./format"

const CUSTOMER_KEY_PREFIX = "cust:"

/**
 * Sort value for a column key. The per-customer cells live inside the nested
 * `by_customer` map, which is exactly code-rule §38's "cells aren't flat
 * scalars" case — so this table keeps local sort state + a metric-aware
 * comparator instead of `useSortable`, and still feeds a `SortState` to
 * `<SortableTh>` so the header affordance stays identical to every other report.
 *
 * Day and Month both sort chronologically off the real ISO date, not the
 * day-of-month integer — a range may span months (and weekends are absent, R1).
 */
function sortValue(r: DfwLossesDailyRow, key: string): string | number | null {
  if (key === "date") return r.date
  if (key === "month") return r.date.slice(0, 7) // yyyy-MM sorts chronologically
  if (key === "loads") return r.loads
  if (key === "amount_lost") return r.amount_lost
  if (key === "loss_per_load") return r.loss_per_load
  if (key.startsWith(CUSTOMER_KEY_PREFIX)) {
    // A customer with no loss that day shows as 0 — sort it as 0, not empty.
    return r.by_customer[key.slice(CUSTOMER_KEY_PREFIX.length)] ?? 0
  }
  return null
}

/**
 * Direction the FIRST click on a column uses. Every money column here is <= 0
 * (losses), so "desc" would put the least-bad day on top — the opposite of what
 * someone clicking "Amount Lost" wants. Worse on a customer column: a day where
 * that customer lost nothing maps to 0, which is the *maximum* of a non-positive
 * column, so a "desc" first click would fill the screen with `—` cells.
 */
function firstClickDir(key: string): SortDir {
  if (key === "date" || key === "month") return "asc" // chronological
  if (key === "loads") return "desc" // busiest day first
  return "asc" // amount_lost, loss_per_load, cust:* — worst (most negative) first
}

function compare(a: string | number | null, b: string | number | null): number {
  if (typeof a === "number" && typeof b === "number") return a - b
  return String(a).localeCompare(String(b), undefined, { numeric: true })
}

export function DailyTable({ filters }: { filters: DfwLossesFilters }) {
  const { data, isLoading, isFetching, error } = useDfwLossesDaily(filters)
  const d = data?.data
  const customers = d?.customers ?? []
  // Memoised because it feeds the sort useMemo's dep array.
  const rows = useMemo(() => d?.rows ?? [], [d])
  const summary = d?.summary
  const totals = d?.totals

  const [sortKey, setSortKey] = useState<string | null>("date")
  const [sortDir, setSortDir] = useState<SortDir>("asc")

  const sortState: SortState = {
    sortKey,
    sortDir,
    toggleSort: (key: string) => {
      if (sortKey === key) {
        setSortDir((dir) => (dir === "asc" ? "desc" : "asc"))
      } else {
        setSortKey(key)
        setSortDir(firstClickDir(key))
      }
    },
  }

  const sorted = useMemo(() => {
    if (!sortKey) return rows
    const copy = [...rows]
    copy.sort((a, b) => {
      const av = sortValue(a, sortKey)
      const bv = sortValue(b, sortKey)
      // Null always sorts last. `loss_per_load` is the only nullable key, and
      // since R3 put `total_charge <> 0` in the WHERE every day-row has at
      // least one load — so this is defensive only (the wire type stays
      // `number | null`), not a case you can reach today.
      if (av === null && bv === null) return 0
      if (av === null) return 1
      if (bv === null) return -1
      const c = compare(av, bv)
      if (c !== 0) return sortDir === "asc" ? c : -c
      // Stable, meaningful tiebreak: chronological.
      return a.date.localeCompare(b.date)
    })
    return copy
  }, [rows, sortKey, sortDir])

  return (
    <section className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-[#E5E7EB] px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-[#1B3A5C]">DFW Losses — Daily</h2>
          {d?.customers_truncated && (
            <span className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[10px] text-[#92400E]">
              Top {customers.length} customers shown
            </span>
          )}
        </div>
        {isFetching && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
      </div>

      <div className="px-4 pt-3">
        <DfwLossesErrorBanner errors={[error]} label="Daily" />
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
        </div>
      ) : rows.length === 0 ? (
        <div className="px-4 py-12 text-center text-sm text-[#6B7280]">
          No activity in the selected window.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-[#E5E7EB] bg-[#F9FAFB] text-left text-[#6B7280]">
                <SortableTh
                  label="Day"
                  columnKey="date"
                  state={sortState}
                  className="sticky left-0 z-10 bg-[#F9FAFB]"
                />
                <SortableTh label="Month" columnKey="month" state={sortState} />
                <SortableTh label="Loads" columnKey="loads" state={sortState} align="right" />
                <SortableTh
                  label="Amount Lost"
                  columnKey="amount_lost"
                  state={sortState}
                  align="right"
                />
                <SortableTh
                  label="Loss / Load"
                  columnKey="loss_per_load"
                  state={sortState}
                  align="right"
                />
                {customers.map((c) => (
                  <SortableTh
                    key={c}
                    /* `title` on the label span, not the th: SortableTh hard-codes
                       title="Sort" on its button, so without this a truncated
                       customer name would be unreadable on hover. */
                    label={
                      <span className="block max-w-[140px] truncate" title={c}>
                        {c}
                      </span>
                    }
                    columnKey={`${CUSTOMER_KEY_PREFIX}${c}`}
                    state={sortState}
                    align="right"
                    className="max-w-[140px]"
                  />
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr
                  key={r.date}
                  className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]"
                >
                  <td className="sticky left-0 z-10 bg-white px-3 py-1.5 font-medium text-[#111827]">
                    {r.day}
                  </td>
                  <td className="px-3 py-1.5 text-[#374151]">{r.month}</td>
                  {/* Bruno 2026-08-03 R1: the Loads count drills through to
                      that day's orders in a NEW tab. The drill carries the
                      contract/customer filters, so its row count always equals
                      the number rendered here. */}
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#111827]">
                    <Link
                      href={dfwLossesOrdersHref(r.date, filters)}
                      target="_blank"
                      rel="noopener noreferrer"
                      title={`Open the ${r.loads} order${r.loads === 1 ? "" : "s"} for ${r.month} ${r.day} in a new tab`}
                      className="rounded font-medium text-[#1D4ED8] underline decoration-dotted underline-offset-2 hover:text-[#1E40AF] hover:decoration-solid focus:outline-none focus-visible:ring-2 focus-visible:ring-[#1D4ED8]"
                    >
                      {fmtCount(r.loads)}
                    </Link>
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#DC2626]">
                    {fmtUsd(r.amount_lost)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-[#B45309]">
                    {fmtUsd(r.loss_per_load)}
                  </td>
                  {customers.map((c) => {
                    const v = r.by_customer[c] ?? 0
                    return (
                      <td
                        key={c}
                        className={`px-3 py-1.5 text-right tabular-nums ${
                          v < 0 ? "text-[#DC2626]" : "text-[#9CA3AF]"
                        }`}
                      >
                        {fmtLossCell(v)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
            {(summary || totals) && (
              /* Pinned server-side rows — kept outside the sorted map (§38/§44). */
              <tfoot>
                {summary && (
                  <tr className="border-t-2 border-[#E5E7EB] bg-[#F3F4F6] font-semibold text-[#111827]">
                    <td className="sticky left-0 z-10 bg-[#F3F4F6] px-3 py-2">Avg</td>
                    <td className="px-3 py-2" />
                    <td className="px-3 py-2 text-right tabular-nums">
                      {fmtCount(Math.round(summary.loads_avg))}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-[#DC2626]">
                      {fmtUsd(summary.amount_lost_avg)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-[#B45309]">
                      {fmtUsd(summary.loss_per_load_avg)}
                    </td>
                    {customers.map((c) => (
                      <td key={c} className="px-3 py-2" />
                    ))}
                  </tr>
                )}
                {/* Bruno 2026-08-03 R2 — Totals. Server-side over the FULL
                    filtered universe (§44), never a reduce over `sorted`.
                    Loss/Load here is total lost / total loads (ratio of sums,
                    §33) and so legitimately differs from the Avg row above,
                    which is the mean of the per-day ratios. */}
                {totals && (
                  <tr className="border-t border-[#E5E7EB] bg-[#E5E7EB] font-semibold text-[#111827]">
                    <td className="sticky left-0 z-10 bg-[#E5E7EB] px-3 py-2">Totals</td>
                    <td className="px-3 py-2" />
                    <td className="px-3 py-2 text-right tabular-nums">
                      {fmtCount(totals.loads)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-[#DC2626]">
                      {fmtUsd(totals.amount_lost)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-[#B45309]">
                      {fmtUsd(totals.loss_per_load)}
                    </td>
                    {customers.map((c) => {
                      const v = totals.by_customer[c] ?? 0
                      return (
                        <td
                          key={c}
                          className={`px-3 py-2 text-right tabular-nums ${
                            v < 0 ? "text-[#DC2626]" : "text-[#9CA3AF]"
                          }`}
                        >
                          {fmtLossCell(v)}
                        </td>
                      )
                    })}
                  </tr>
                )}
              </tfoot>
            )}
          </table>
        </div>
      )}
    </section>
  )
}
