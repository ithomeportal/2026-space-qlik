"use client"

/**
 * DFW Losses — day drill-down (Bruno PDF 2026-08-03 R1).
 *
 * Opened in a NEW TAB from the Daily table's `Loads` cell, so it is a real
 * route with the day and filters in the URL — shareable, refreshable, and
 * back-button friendly. It is a sub-route of an existing report, not a new
 * report: same `reportKey`, same backend `require_report_access("dfw-losses")`,
 * so there is no 4-place mirror / `role_report_access` change to make.
 *
 * The row count here always equals the Loads number that was clicked — the
 * endpoint reuses the Daily query's `_scope_where()` and deliberately does NOT
 * filter to losing orders (§16).
 */

import { Suspense, useMemo, useState } from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { ArrowLeft, Loader2, TrendingDown } from "lucide-react"
import {
  useDfwLossesOrders,
  type DfwLossesOrdersSort,
} from "@/lib/dfw-losses-api"
import { ReportGuard } from "@/components/ReportGuard"
import { SortableTh, type SortDir, type SortState } from "@/components/SortableTable"
import { DfwLossesErrorBanner } from "../ErrorBanner"
import { fmtUsd, fmtCount } from "../format"

const PAGE_SIZE = 200

const CONTRACT_LABELS: Record<string, string> = { C: "Contract", S: "Spot" }

/** Repeated `?customer=A&customer=B` params — never a comma-split, since real
 *  customer names contain commas ("CONAGRA FOODS PACKAGED FOODS, LLC"). */
function readMulti(sp: URLSearchParams, key: string): string[] {
  return sp
    .getAll(key)
    .map((s) => s.trim())
    .filter(Boolean)
}

/** "2026-08-03" → "Monday, August 3, 2026" (parsed as local, not UTC). */
function longDay(iso: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso
  const d = new Date(`${iso}T00:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  })
}

/** Timestamp → "Aug 3, 14:05". Falls back to the raw string if unparseable. */
function fmtDeparture(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
}

const fmtPct1 = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : `${Number(v).toFixed(1)}%`

/**
 * First-click direction per column. Profit and Margin are the loss-bearing
 * columns, so they open ascending — worst order first. A "desc" first click
 * would lead with the most profitable order, which is the opposite of why
 * anyone drills into a losses report.
 */
function firstClickDir(key: string): SortDir {
  if (key === "profit" || key === "margin") return "asc"
  if (key === "revenue") return "desc"
  return "asc" // departure, order_id, customer
}

function OrdersContent() {
  const searchParams = useSearchParams()

  const day = searchParams.get("day") ?? ""
  const contractTypes = useMemo(
    () => readMulti(new URLSearchParams(searchParams.toString()), "contract"),
    [searchParams],
  )
  const customerNames = useMemo(
    () => readMulti(new URLSearchParams(searchParams.toString()), "customer"),
    [searchParams],
  )

  const [sort, setSort] = useState<DfwLossesOrdersSort>("profit_asc")
  const [page, setPage] = useState(1)

  const filters = useMemo(
    () => ({ contractTypes, customerNames }),
    [contractTypes, customerNames],
  )

  const { data, isLoading, isFetching, error } = useDfwLossesOrders(
    day,
    filters,
    sort,
    page,
    PAGE_SIZE,
  )

  const rows = data?.data?.rows ?? []
  const totals = data?.data?.totals
  const total = data?.meta?.total ?? 0
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  // Sorting is server-side (the endpoint owns the ORDER BY whitelist), but the
  // header affordance stays the shared <SortableTh> so it matches every other
  // table in the portal (§38).
  const [sortKey, sortDir] = useMemo(() => {
    const i = sort.lastIndexOf("_")
    return [sort.slice(0, i), sort.slice(i + 1) as SortDir] as const
  }, [sort])

  const sortState: SortState = {
    sortKey,
    sortDir,
    toggleSort: (key: string) => {
      setSort((prev) =>
        prev === `${key}_asc`
          ? (`${key}_desc` as DfwLossesOrdersSort)
          : prev === `${key}_desc`
            ? (`${key}_asc` as DfwLossesOrdersSort)
            : (`${key}_${firstClickDir(key)}` as DfwLossesOrdersSort),
      )
      setPage(1)
    },
  }

  return (
    <div className="flex min-h-[calc(100vh-64px)] flex-col bg-[#F9FAFB]">
      {/* Top bar */}
      <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-white px-4 py-2">
        <Link
          href="/reports/dfw-losses"
          className="flex items-center gap-1 text-sm text-[#6B7280] hover:text-[#111827]"
        >
          <ArrowLeft className="h-4 w-4" />
          DFW Losses
        </Link>
        <div className="h-4 w-px bg-[#E5E7EB]" />
        <div className="flex items-center gap-2">
          <TrendingDown className="h-4 w-4 text-[#DC2626]" />
          <h1 className="text-sm font-semibold text-[#1B3A5C]">Orders</h1>
          <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-xs text-[#1D4ED8]">
            TEAM-DFW
          </span>
        </div>
        <div className="ml-auto flex items-center gap-3 text-xs text-[#6B7280]">
          <span>
            {day ? longDay(day) : "No day selected"}
            {contractTypes.length
              ? ` · Contract: ${contractTypes
                  .map((c) => CONTRACT_LABELS[c] ?? c)
                  .join(", ")}`
              : ""}
            {customerNames.length
              ? ` · ${customerNames.length} customer${customerNames.length > 1 ? "s" : ""}`
              : ""}
          </span>
          {isFetching && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
        </div>
      </div>

      <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-4 px-6 py-4">
        <DfwLossesErrorBanner errors={[error]} label="Orders" />

        {!day ? (
          <div className="rounded-xl border border-[#E5E7EB] bg-white px-4 py-12 text-center text-sm text-[#6B7280]">
            No day selected. Open this page by clicking a{" "}
            <strong>Loads</strong> value in the DFW Losses daily table.
          </div>
        ) : (
          <section className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
            <div className="flex items-center justify-between border-b border-[#E5E7EB] px-4 py-3">
              <h2 className="text-sm font-semibold text-[#1B3A5C]">
                Orders — {longDay(day)}
              </h2>
              <span className="text-xs text-[#6B7280]">
                {fmtCount(total)} order{total === 1 ? "" : "s"}
              </span>
            </div>

            {isLoading ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
              </div>
            ) : rows.length === 0 ? (
              /* "Empty" and "the request failed" must not share a string — an
                 error already shows in the banner above, so say so here too. */
              <div className="px-4 py-12 text-center text-sm text-[#6B7280]">
                {error
                  ? "Could not load orders for this day."
                  : "No orders for this day."}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-[#E5E7EB] bg-[#F9FAFB] text-left text-[#6B7280]">
                      <SortableTh
                        label="Order ID"
                        columnKey="order_id"
                        state={sortState}
                      />
                      <SortableTh
                        label="Customer"
                        columnKey="customer"
                        state={sortState}
                      />
                      <SortableTh
                        label="Origin Actual Departure"
                        columnKey="departure"
                        state={sortState}
                      />
                      <SortableTh
                        label="Revenue"
                        columnKey="revenue"
                        state={sortState}
                        align="right"
                      />
                      <SortableTh
                        label="Profit"
                        columnKey="profit"
                        state={sortState}
                        align="right"
                      />
                      <SortableTh
                        label="Margin"
                        columnKey="margin"
                        state={sortState}
                        align="right"
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr
                        key={`${r.order_id}-${i}`}
                        className="border-b border-[#F3F4F6] hover:bg-[#F9FAFB]"
                      >
                        <td className="px-3 py-1.5 font-mono text-[#111827]">
                          {r.order_id || "—"}
                        </td>
                        <td className="px-3 py-1.5 text-[#374151]">
                          {r.customer ?? "—"}
                        </td>
                        <td className="px-3 py-1.5 tabular-nums text-[#374151]">
                          {fmtDeparture(r.origin_actual_departure)}
                        </td>
                        <td className="px-3 py-1.5 text-right tabular-nums text-[#111827]">
                          {fmtUsd(r.revenue)}
                        </td>
                        <td
                          className={`px-3 py-1.5 text-right tabular-nums font-medium ${
                            r.profit < 0 ? "text-[#DC2626]" : "text-[#111827]"
                          }`}
                        >
                          {fmtUsd(r.profit)}
                        </td>
                        <td
                          className={`px-3 py-1.5 text-right tabular-nums ${
                            (r.margin_pct ?? 0) < 0
                              ? "text-[#DC2626]"
                              : "text-[#7C3AED]"
                          }`}
                        >
                          {fmtPct1(r.margin_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  {totals && (
                    /* Server-side full-universe totals (§44) — every page shows
                       the same day-level figures, never a sum of this page. */
                    <tfoot>
                      <tr className="border-t-2 border-[#E5E7EB] bg-[#E5E7EB] font-semibold text-[#111827]">
                        <td className="px-3 py-2" colSpan={3}>
                          Totals ({fmtCount(totals.loads)} order
                          {totals.loads === 1 ? "" : "s"})
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          {fmtUsd(totals.revenue)}
                        </td>
                        <td
                          className={`px-3 py-2 text-right tabular-nums ${
                            totals.profit < 0 ? "text-[#DC2626]" : "text-[#111827]"
                          }`}
                        >
                          {fmtUsd(totals.profit)}
                        </td>
                        <td
                          className={`px-3 py-2 text-right tabular-nums ${
                            (totals.margin_pct ?? 0) < 0
                              ? "text-[#DC2626]"
                              : "text-[#7C3AED]"
                          }`}
                        >
                          {fmtPct1(totals.margin_pct)}
                        </td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            )}

            {total > PAGE_SIZE && (
              <div className="flex items-center justify-between border-t border-[#E5E7EB] px-4 py-3 text-xs">
                <div className="text-[#6B7280]">
                  Page {page} of {pageCount} · {fmtCount(total)} orders
                </div>
                <div className="flex gap-1">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="rounded border border-[#E5E7EB] bg-white px-3 py-1 disabled:opacity-40"
                  >
                    Prev
                  </button>
                  <button
                    onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                    disabled={page === pageCount}
                    className="rounded border border-[#E5E7EB] bg-white px-3 py-1 disabled:opacity-40"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </section>
        )}
      </div>
    </div>
  )
}

export default function DfwLossesOrdersPage() {
  return (
    <ReportGuard reportKey="dfw-losses">
      <Suspense
        fallback={
          <div className="flex min-h-[60vh] items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
          </div>
        }
      >
        <OrdersContent />
      </Suspense>
    </ReportGuard>
  )
}
