"use client"

import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useBookerOrders,
  type BookerFilters,
  type BookerOrdersSort,
} from "@/lib/booker-scorecard-api"

interface Props {
  filters: BookerFilters
}

const PAGE_SIZE = 200

/** Column key -> (asc sort, desc sort) understood by the backend whitelist. */
const SORTS: Record<string, [BookerOrdersSort, BookerOrdersSort]> = {
  order_id: ["order_asc", "order_desc"],
  posted_date: ["posted_asc", "posted_desc"],
  revenue: ["revenue_asc", "revenue_desc"],
  carrier_cost: ["cost_asc", "cost_desc"],
  profit: ["profit_asc", "profit_desc"],
}

function OnTime({ ok }: { ok: boolean }) {
  return (
    <span
      className={`rounded-full px-1.5 py-px text-[10px] font-semibold ${
        ok ? "bg-[#D1FAE5] text-[#065F46]" : "bg-[#FEE2E2] text-[#991B1B]"
      }`}
    >
      {ok ? "On time" : "Late"}
    </span>
  )
}

/**
 * Sorting is SERVER-side: the table paginates, and sorting only the current
 * page would reorder 200 rows out of thousands while looking like it sorted
 * everything.
 */
function Th({
  label,
  columnKey,
  sort,
  setSort,
  align = "left",
}: {
  label: string
  columnKey?: string
  sort: BookerOrdersSort
  setSort: (s: BookerOrdersSort) => void
  align?: "left" | "right"
}) {
  const pair = columnKey ? SORTS[columnKey] : undefined
  const active = pair ? pair.includes(sort) : false
  const arrow = !active ? "↕" : sort === pair?.[0] ? "▲" : "▼"
  const cls = `px-3 py-1.5 font-semibold ${align === "right" ? "text-right" : "text-left"}`

  if (!pair) return <th className={cls}>{label}</th>

  return (
    <th className={cls}>
      <button
        type="button"
        onClick={() => setSort(sort === pair[1] ? pair[0] : pair[1])}
        className={`flex w-full items-center gap-1 ${
          align === "right" ? "justify-end" : "justify-start"
        } hover:text-[#111827] ${active ? "text-[#1B3A5C]" : ""}`}
        title="Sort"
      >
        <span>{label}</span>
        <span className="text-[9px] leading-none text-[#9CA3AF]">{arrow}</span>
      </button>
    </th>
  )
}

export function OrdersTable({ filters }: Props) {
  const [sort, setSort] = useState<BookerOrdersSort>("posted_desc")
  const [page, setPage] = useState(1)

  // Any scope change invalidates the current page number — page 7 of the old
  // result set is meaningless against the new one.
  useEffect(() => {
    setPage(1)
  }, [filters, sort])

  const { data, isLoading, error, isFetching } = useBookerOrders(
    filters,
    sort,
    page,
    PAGE_SIZE,
  )
  const rows = data?.data?.rows ?? []
  const totals = data?.data?.totals
  const total = data?.meta?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const thresholdsAvailable = data?.data?.thresholds_available ?? true

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-sm font-semibold text-[#1B3A5C]">Orders</div>
        <div className="flex items-center gap-3 text-[10px] text-[#9CA3AF]">
          {!thresholdsAvailable && (
            <span className="text-[#B45309]">
              Threshold source unavailable — Threshold column shows —
            </span>
          )}
          <span>
            {fmtCount(total)} order{total === 1 ? "" : "s"}
          </span>
          {isFetching && <Loader2 className="h-3 w-3 animate-spin" />}
        </div>
      </div>

      {error ? (
        <div className="py-8 text-center text-xs text-[#991B1B]">
          Could not load orders:{" "}
          {error instanceof Error ? error.message : "unknown error"}
        </div>
      ) : (
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                <Th label="Order" columnKey="order_id" sort={sort} setSort={setSort} />
                <Th label="Team" sort={sort} setSort={setSort} />
                <Th label="Customer" sort={sort} setSort={setSort} />
                <Th label="Posted By" sort={sort} setSort={setSort} />
                <Th label="Posted" columnKey="posted_date" sort={sort} setSort={setSort} />
                <Th label="Revenue" columnKey="revenue" sort={sort} setSort={setSort} align="right" />
                <Th label="Carrier Cost" columnKey="carrier_cost" sort={sort} setSort={setSort} align="right" />
                <Th label="Profit" columnKey="profit" sort={sort} setSort={setSort} align="right" />
                <Th label="OTP" sort={sort} setSort={setSort} />
                <Th label="OTD" sort={sort} setSort={setSort} />
                <Th label="Threshold" sort={sort} setSort={setSort} align="right" />
              </tr>
            </thead>
            <tbody>
              {isLoading && rows.length === 0 ? (
                <tr>
                  <td colSpan={11} className="py-8 text-center">
                    <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={11} className="py-8 text-center text-[#9CA3AF]">
                    No orders in this window.
                  </td>
                </tr>
              ) : (
                rows.map((r) => {
                  // Highlight the row the Broken Threshold KPI is counting, so
                  // the number on the card is traceable to the rows below it.
                  const broken =
                    r.threshold !== null &&
                    r.carrier_cost !== null &&
                    r.carrier_cost > r.threshold
                  return (
                    <tr
                      key={r.order_id}
                      className="border-b border-[#F3F4F6] last:border-0 hover:bg-[#F9FAFB]"
                    >
                      <td className="px-3 py-1.5 font-mono">{r.order_id}</td>
                      <td className="px-3 py-1.5">{r.team ?? "—"}</td>
                      <td className="px-3 py-1.5">{r.customer ?? "—"}</td>
                      <td className="px-3 py-1.5">{r.posted_by ?? "—"}</td>
                      <td className="px-3 py-1.5 text-[#6B7280]">
                        {r.posted_date ? r.posted_date.slice(0, 10) : "—"}
                      </td>
                      <td className="px-3 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                      <td className="px-3 py-1.5 text-right">
                        {fmtUsd(r.carrier_cost)}
                      </td>
                      <td
                        className={`px-3 py-1.5 text-right ${
                          (r.profit ?? 0) < 0 ? "text-[#991B1B]" : ""
                        }`}
                      >
                        {fmtUsd(r.profit)}
                      </td>
                      <td className="px-3 py-1.5">
                        <OnTime ok={r.otp_on_time} />
                      </td>
                      <td className="px-3 py-1.5">
                        <OnTime ok={r.otd_on_time} />
                      </td>
                      <td
                        className={`px-3 py-1.5 text-right ${
                          broken ? "font-semibold text-[#B45309]" : ""
                        }`}
                        title={broken ? "Carrier cost exceeds the threshold" : undefined}
                      >
                        {fmtUsd(r.threshold)}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
            {totals && (
              <tfoot>
                {/* Server-side aggregate over EVERY matching order, not a sum of
                    the visible page (§44). */}
                <tr className="border-t-2 border-[#E5E7EB] bg-[#F9FAFB] font-semibold">
                  <td className="px-3 py-1.5" colSpan={5}>
                    Totals — all {fmtCount(totals.orders)} orders
                  </td>
                  <td className="px-3 py-1.5 text-right">{fmtUsd(totals.revenue)}</td>
                  <td className="px-3 py-1.5 text-right">
                    {fmtUsd(totals.carrier_cost)}
                  </td>
                  <td className="px-3 py-1.5 text-right">{fmtUsd(totals.profit)}</td>
                  <td className="px-3 py-1.5">{fmtPct(totals.otp_pct)}</td>
                  <td className="px-3 py-1.5">{fmtPct(totals.otd_pct)}</td>
                  <td className="px-3 py-1.5 text-right text-[10px] font-normal text-[#6B7280]">
                    {totals.broken_threshold === null
                      ? "—"
                      : `${fmtCount(totals.broken_threshold)} broken / ${fmtCount(
                          totals.threshold_orders,
                        )}`}
                  </td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}

      {pages > 1 && (
        <div className="mt-3 flex items-center justify-end gap-2 text-xs">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded-md border border-[#E5E7EB] px-2 py-1 disabled:opacity-40"
          >
            Prev
          </button>
          <span className="text-[#6B7280]">
            Page {page} of {pages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(pages, p + 1))}
            disabled={page >= pages}
            className="rounded-md border border-[#E5E7EB] px-2 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
