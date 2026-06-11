"use client"

import { useEffect, useState } from "react"
import { Loader2, Maximize2, Package } from "lucide-react"
import {
  adminCashflowCsvUrl,
  useDeliveredNotBilled,
  type AdminCashflowFilters,
  type DeliveredNotBilledRow,
} from "@/lib/admin-cashflow-api"
import { useDebounce } from "@/lib/use-debounce"
import { DownloadCsvButton } from "./DownloadCsvButton"
import { fmtCount, fmtDate, fmtUsd } from "./format"
import {
  ColumnFilters,
  DaysBadge,
  Pager,
  SortableTh,
  UnbilledExpandModal,
} from "./UnbilledShared"

const PAGE_SIZE = 25
const EXPANDED_PAGE_SIZE = 100

interface Props {
  filters: AdminCashflowFilters
}

// Presentational thead + tbody — shared by the inline card and the pop-up.
function DeliveredTable({
  rows,
  loading,
  sort,
  onSort,
}: {
  rows: DeliveredNotBilledRow[]
  loading: boolean
  sort: string
  onSort: (s: string) => void
}) {
  return (
    <div className="overflow-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
          <tr className="border-b border-[#E5E7EB]">
            <SortableTh label="Order" col="id_asc" colDesc="id_desc" current={sort} onChange={onSort} />
            <SortableTh label="Customer" col="customer_asc" colDesc="customer_desc" current={sort} onChange={onSort} />
            <SortableTh label="Orig Sched Early" col="ship_asc" colDesc="ship_desc" current={sort} onChange={onSort} />
            <SortableTh label="Ship Date" col="ship_asc" colDesc="ship_desc" current={sort} onChange={onSort} />
            <SortableTh label="Delivered" col="delivered_asc" colDesc="delivered_desc" current={sort} onChange={onSort} />
            <SortableTh label="Days" col="days_asc" colDesc="days_desc" current={sort} onChange={onSort} align="right" />
            <SortableTh label="$ Revenue" col="revenue_asc" colDesc="revenue_desc" current={sort} onChange={onSort} align="right" />
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={7} className="py-8 text-center">
                <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
              </td>
            </tr>
          ) : rows.length === 0 ? (
            <tr>
              <td colSpan={7} className="py-8 text-center text-[#9CA3AF]">
                No delivered-but-unbilled loads in current filters 🎉
              </td>
            </tr>
          ) : (
            rows.map((r) => (
              <tr
                key={`${r.company_id}-${r.id}`}
                className="border-b border-[#F3F4F6] last:border-0"
              >
                <td className="px-2 py-1.5 font-mono text-[11px]">{r.id}</td>
                <td className="max-w-[200px] truncate px-2 py-1.5" title={r.customer_name}>
                  {r.customer_name || "—"}
                </td>
                <td className="px-2 py-1.5">{fmtDate(r.orig_sched_early)}</td>
                <td className="px-2 py-1.5">{fmtDate(r.ship_date)}</td>
                <td className="px-2 py-1.5">{fmtDate(r.dest_actual_arrival)}</td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  <DaysBadge days={r.days_since_delivery} />
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  {fmtUsd(r.total_charge)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

// Pop-up body — its own page state at a larger page size; reuses the
// presentational table + the shared column filters/sort from the card.
function DeliveredExpanded({
  filters,
  sort,
  onSort,
  orderQ,
  customerQ,
}: {
  filters: AdminCashflowFilters
  sort: string
  onSort: (s: string) => void
  orderQ: string
  customerQ: string
}) {
  const [page, setPage] = useState(1)
  useEffect(() => setPage(1), [sort, orderQ, customerQ])
  const { data, isLoading } = useDeliveredNotBilled(filters, {
    sort,
    page,
    limit: EXPANDED_PAGE_SIZE,
    orderQ,
    customerQ,
  })
  const rows = data?.data ?? []
  const total = data?.meta?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / EXPANDED_PAGE_SIZE))
  return (
    <>
      <DeliveredTable rows={rows} loading={isLoading} sort={sort} onSort={onSort} />
      <Pager page={page} pages={pages} total={total} size={EXPANDED_PAGE_SIZE} onChange={setPage} />
    </>
  )
}

export function DeliveredNotBilledCard({ filters }: Props) {
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<string>("delivered_asc")
  const [orderQ, setOrderQ] = useState("")
  const [customerQ, setCustomerQ] = useState("")
  const [expanded, setExpanded] = useState(false)
  const dOrderQ = useDebounce(orderQ, 300)
  const dCustomerQ = useDebounce(customerQ, 300)

  // Any filter/sort change resets to the first page so the user isn't stranded
  // on an out-of-range page.
  useEffect(() => setPage(1), [sort, dOrderQ, dCustomerQ])

  const { data, isLoading } = useDeliveredNotBilled(filters, {
    sort,
    page,
    limit: PAGE_SIZE,
    orderQ: dOrderQ,
    customerQ: dCustomerQ,
  })
  const rows = data?.data ?? []
  const total = data?.meta?.total ?? 0
  const grand = data?.meta?.grand_total_revenue ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const csvHref = adminCashflowCsvUrl("delivered-not-billed", filters, {
    sort,
    orderQ: dOrderQ,
    customerQ: dCustomerQ,
  })

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Package className="h-4 w-4 text-[#B45309]" />
          <div className="text-sm font-semibold text-[#1B3A5C]">
            Delivered but not billed
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-[#6B7280]">
          <span>{fmtCount(total)} loads · {fmtUsd(grand)}</span>
          <button
            onClick={() => setExpanded(true)}
            title="Expand to view all orders"
            className="inline-flex items-center gap-1 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-[11px] text-[#374151] hover:bg-[#F9FAFB] hover:text-[#1B3A5C]"
          >
            <Maximize2 className="h-3 w-3" />
            Expand
          </button>
          <DownloadCsvButton
            href={csvHref}
            title="Download all delivered-but-not-billed rows in current filters as CSV"
          />
        </div>
      </div>
      <ColumnFilters
        orderQ={orderQ}
        customerQ={customerQ}
        onOrder={setOrderQ}
        onCustomer={setCustomerQ}
      />
      <DeliveredTable rows={rows} loading={isLoading} sort={sort} onSort={setSort} />
      <Pager page={page} pages={pages} total={total} size={PAGE_SIZE} onChange={setPage} />

      {expanded && (
        <UnbilledExpandModal
          title="Delivered but not billed"
          subtitle={`${fmtCount(total)} loads · ${fmtUsd(grand)} — all orders in current filters`}
          onClose={() => setExpanded(false)}
        >
          <ColumnFilters
            orderQ={orderQ}
            customerQ={customerQ}
            onOrder={setOrderQ}
            onCustomer={setCustomerQ}
          />
          <DeliveredExpanded
            filters={filters}
            sort={sort}
            onSort={setSort}
            orderQ={dOrderQ}
            customerQ={dCustomerQ}
          />
        </UnbilledExpandModal>
      )}
    </div>
  )
}
