"use client"

import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react"
import { useEffect, useState } from "react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useXrayDfwAllOrders,
  type XrayDfwAllOrdersSort,
  type XrayDfwFilters,
} from "@/lib/xray-dfw-api"
import { useSortable, SortableTh } from "@/components/SortableTable"
import { ClickName } from "./ClickName"

/**
 * The "All Orders" table, shared by the Contract vs Spot tab and the GM tab
 * (Bruno PDF 2026-09-15 R2 asked for the second one to be a duplicate of the
 * first). Extracted rather than copied: the two differ only in four props, and
 * a copy would have to be kept in step every time a column moves.
 *
 * ⚠ Sorting here is TWO mechanisms, deliberately:
 *   - `sort` is the SERVER's ORDER BY over the whole universe, which is the
 *     only thing that can express a default order across a paginated table;
 *   - `useSortable` re-orders the rows already on screen when a header is
 *     clicked. That is a within-page convenience — with 500 rows per page and
 *     4,111 GM orders in scope it does NOT reorder the table, which is why the
 *     caption says which order the page arrived in.
 */
interface Props {
  filters: XrayDfwFilters
  entityLabel?: string
  onCustomerClick?: (name: string) => void
  onLaneClick?: (lane: string) => void
  /** Server-side default order. */
  sort?: XrayDfwAllOrdersSort
  /** Human-readable twin of `sort`, for the caption. */
  sortLabel?: string
  /** Show the BOL / PO columns (Bruno PDF 2026-09-15 R4). */
  showRefs?: boolean
  /** Drop the `total_charge <> 0` filter (R3). */
  includeZeroCharge?: boolean
  onError?: (err: unknown) => void
}

export function AllOrdersTable({
  filters,
  entityLabel = "Customer",
  onCustomerClick,
  onLaneClick,
  sort = "departure_desc",
  sortLabel = "most recent departure first",
  showRefs = false,
  includeZeroCharge = false,
  onError,
}: Props) {
  // Bruno 2026-06-03: server-paginated, 500/page. Reset to page 1 whenever the
  // filter scope changes — page 7 of the old result set means nothing against
  // the new one.
  const [page, setPage] = useState(1)
  const filterKey = JSON.stringify(filters)
  useEffect(() => {
    setPage(1)
  }, [filterKey])

  const { data: ordersRes, isLoading: loadingOrd, error: ordErr } = useXrayDfwAllOrders(
    filters,
    page,
    true,
    { sort, includeZeroCharge },
  )
  // ⚠ MIRROR the hook's error, never latch it. `if (ordErr) onError?.(ordErr)`
  // is a one-way latch: when React Query clears `error` on a successful
  // refetch the `if` skips, the parent keeps the dead Error, and the banner
  // stays red forever — while `XrayDfwErrorBanner` keeps printing an inflated
  // "N queries failed". This endpoint carries XRAY_DFW_RETRY precisely because
  // Render cold-start 502/503s are routine, so "fails once then succeeds" is
  // the NORMAL path here, not the rare one. Both callers pass a `useState`
  // setter, so the identity is stable and this cannot loop.
  useEffect(() => {
    onError?.(ordErr ?? null)
  }, [ordErr, onError])

  const ordersPage = ordersRes?.data
  const orders = ordersPage?.rows ?? []
  const ordersTotals = ordersPage?.totals

  const totalOrders = ordersPage?.total ?? 0
  const pageSize = ordersPage?.page_size ?? 500
  const pageCount = Math.max(1, Math.ceil(totalOrders / pageSize))

  const orderSort = useSortable(orders)

  // Columns left of $ Revenue, so the Totals row's colSpan follows the table
  // instead of being a literal that silently shifts when a column is added.
  const leadCols = 7 + (showRefs ? 2 : 0)

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E5E7EB] bg-[#FEF3C7] px-3 py-2 text-sm font-semibold text-[#111827]">
        <div>
          All Orders
          <span className="ml-2 text-xs font-normal text-[#6B7280]">
            {fmtCount(totalOrders)} orders
            {/* ⚠ Bruno PDF 2026-09-15 R3 drops the `total_charge <> 0` filter,
                which admits real moving loads whose revenue has not posted yet
                — `margin_amt = −carrier_pay` on every one of them. Saying how
                many there are is what keeps the Totals profit legible as a
                billing lag instead of a collapse. Decision: Diego,
                2026-09-15. */}
            {includeZeroCharge && ordersTotals
              ? ` · ${fmtCount(ordersTotals.unbilled)} unbilled`
              : ""}{" "}
            · 500 per page · {sortLabel}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs font-normal text-[#374151]">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="inline-flex items-center rounded border border-[#E5E7EB] bg-white px-2 py-1 disabled:opacity-40"
          >
            <ChevronLeft className="h-3.5 w-3.5" /> Prev
          </button>
          <span>
            Page {page} of {fmtCount(pageCount)}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
            disabled={page >= pageCount}
            className="inline-flex items-center rounded border border-[#E5E7EB] bg-white px-2 py-1 disabled:opacity-40"
          >
            Next <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      {includeZeroCharge && (ordersTotals?.unbilled ?? 0) > 0 && (
        <p className="border-b border-[#FDE68A] bg-[#FFFBEB] px-3 py-1.5 text-[11px] text-[#92400E]">
          Includes {fmtCount(ordersTotals?.unbilled)} unbilled order
          {(ordersTotals?.unbilled ?? 0) === 1 ? "" : "s"} — revenue has not posted yet, so
          their carrier pay counts against Profit below.
        </p>
      )}
      {loadingOrd && orders.length === 0 ? (
        <div className="flex justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[500px] overflow-auto">
          <table className="w-full text-xs tabular-nums">
            <thead className="sticky top-0 bg-[#FEF3C7] text-[#6B7280]">
              <tr>
                <SortableTh label="Team" columnKey="team" state={orderSort} />
                <SortableTh label="Order" columnKey="id" state={orderSort} />
                <SortableTh label={entityLabel} columnKey="customer" state={orderSort} />
                <SortableTh label="Carrier" columnKey="carrier" state={orderSort} />
                <SortableTh label="Origin" columnKey="origin" state={orderSort} />
                <SortableTh label="Destination" columnKey="destination" state={orderSort} />
                <SortableTh label="Departure" columnKey="departure" state={orderSort} />
                {showRefs && <SortableTh label="BOL" columnKey="bol" state={orderSort} />}
                {showRefs && <SortableTh label="PO" columnKey="po" state={orderSort} />}
                <SortableTh label="$ Revenue" columnKey="revenue" state={orderSort} align="right" />
                <SortableTh label="$ Profit" columnKey="profit" state={orderSort} align="right" />
                <SortableTh label="Margin %" columnKey="margin_pct" state={orderSort} align="right" />
                <SortableTh label="Contract / Spot" columnKey="contract_type" state={orderSort} />
                <SortableTh label="Equip" columnKey="equipment_group" state={orderSort} />
              </tr>
            </thead>
            <tbody>
              {/* Bruno 2026-06-03: universe Totals row (all pages, not just the
                  visible one). */}
              {ordersTotals && (
                <tr className="sticky top-[29px] z-10 bg-[#FDE68A] font-semibold">
                  <td className="px-3 py-1.5" colSpan={leadCols}>
                    Totals ({fmtCount(ordersTotals.loads)} orders)
                  </td>
                  <td className="px-3 py-1.5 text-right">{fmtUsd(ordersTotals.revenue)}</td>
                  <td
                    className={`px-3 py-1.5 text-right ${
                      ordersTotals.profit < 0 ? "text-[#DC2626]" : ""
                    }`}
                  >
                    {fmtUsd(ordersTotals.profit)}
                  </td>
                  <td
                    className={`px-3 py-1.5 text-right ${
                      ordersTotals.margin_pct < 0 ? "text-[#DC2626]" : ""
                    }`}
                  >
                    {fmtPct(ordersTotals.margin_pct)}
                  </td>
                  <td className="px-3 py-1.5" />
                  <td className="px-3 py-1.5" />
                </tr>
              )}
              {/* ⚠ Keyed on id + company_id. `id` ALONE is not unique — v4
                  holds 281,951 rows over 247,882 distinct ids — and React
                  mis-reconciles duplicate keys, which would visually merge
                  twin rows on the one tab that promises every order. */}
              {orderSort.sorted.map((r) => (
                <tr
                  key={`${r.id}-${r.company_id}`}
                  className="border-t border-[#F3F4F6] hover:bg-[#FEFCE8]"
                >
                  <td className="px-3 py-1.5">{r.team}</td>
                  <td className="px-3 py-1.5">{r.id}</td>
                  <td className="px-3 py-1.5">
                    <ClickName value={r.customer} onClick={onCustomerClick} />
                  </td>
                  <td className="px-3 py-1.5">{r.carrier}</td>
                  <td className="px-3 py-1.5">{r.origin}</td>
                  <td className="px-3 py-1.5">
                    <ClickName
                      value={`${r.origin} - ${r.destination}`}
                      display={r.destination}
                      onClick={onLaneClick}
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    {r.departure ? r.departure.substring(0, 16).replace("T", " ") : "—"}
                  </td>
                  {showRefs && <td className="px-3 py-1.5">{r.bol ?? "—"}</td>}
                  {showRefs && <td className="px-3 py-1.5">{r.po ?? "—"}</td>}
                  <td className="px-3 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                  <td
                    className={`px-3 py-1.5 text-right ${r.profit < 0 ? "text-[#DC2626]" : ""}`}
                  >
                    {fmtUsd(r.profit)}
                  </td>
                  <td
                    className={`px-3 py-1.5 text-right ${
                      r.margin_pct < 0 ? "text-[#DC2626]" : ""
                    }`}
                  >
                    {fmtPct(r.margin_pct)}
                  </td>
                  <td className="px-3 py-1.5">{r.contract_type}</td>
                  <td className="px-3 py-1.5">{r.equipment_group}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
