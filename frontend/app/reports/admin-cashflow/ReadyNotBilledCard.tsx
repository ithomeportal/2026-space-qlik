"use client"

import { useEffect, useState } from "react"
import { Loader2, Maximize2, Stamp } from "lucide-react"
import {
  adminCashflowCsvUrl,
  useReadyNotBilled,
  type AdminCashflowFilters,
  type ReadyNotBilledRow,
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
  CustomerFilterLink,
} from "./UnbilledShared"

const PAGE_SIZE = 25
const EXPANDED_PAGE_SIZE = 100

interface Props {
  filters: AdminCashflowFilters
  // Bruno (PDF 2026-08-27) R1: click a customer name to filter the page.
  onCustomerClick?: (name: string) => void
}

function ReadyTable({
  rows,
  loading,
  sort,
  onSort,
  onCustomerClick,
}: {
  rows: ReadyNotBilledRow[]
  loading: boolean
  sort: string
  onSort: (s: string) => void
  onCustomerClick?: (name: string) => void
}) {
  return (
    <div className="overflow-auto">
      <table className="w-full text-xs">
        <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
          <tr className="border-b border-[#E5E7EB]">
            <SortableTh label="Order" col="id_asc" colDesc="id_desc" current={sort} onChange={onSort} />
            <SortableTh label="Customer" col="customer_asc" colDesc="customer_desc" current={sort} onChange={onSort} />
            <SortableTh label="Ship Date" col="ship_asc" colDesc="ship_desc" current={sort} onChange={onSort} />
            <SortableTh label="Orig Sched Early" col="ship_asc" colDesc="ship_desc" current={sort} onChange={onSort} />
            <SortableTh label="BOL Recv" col="bol_asc" colDesc="bol_desc" current={sort} onChange={onSort} />
            <SortableTh label="Status" col="status_asc" colDesc="status_desc" current={sort} onChange={onSort} />
            <SortableTh label="Days" col="days_asc" colDesc="days_desc" current={sort} onChange={onSort} align="right" />
            <SortableTh label="$ Revenue" col="revenue_asc" colDesc="revenue_desc" current={sort} onChange={onSort} align="right" />
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={8} className="py-8 text-center">
                <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
              </td>
            </tr>
          ) : rows.length === 0 ? (
            <tr>
              <td colSpan={8} className="py-8 text-center text-[#9CA3AF]">
                No ready-but-unbilled loads in current filters 🎉
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
                  <CustomerFilterLink
                    name={r.customer_name}
                    onClick={onCustomerClick}
                    className="block max-w-full truncate"
                  />
                </td>
                <td className="px-2 py-1.5">{fmtDate(r.ship_date)}</td>
                <td className="px-2 py-1.5">{fmtDate(r.orig_sched_early)}</td>
                <td className="px-2 py-1.5">{fmtDate(r.bol_recv_date)}</td>
                <td className="px-2 py-1.5">
                  <span className="rounded bg-[#F3F4F6] px-1.5 py-0.5 text-[10px] text-[#374151]">
                    {r.status}
                  </span>
                </td>
                <td className="px-2 py-1.5 text-right tabular-nums">
                  <DaysBadge days={r.days_since_bol_recv} />
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

function ReadyExpanded({
  filters,
  sort,
  onSort,
  orderQ,
  customerQ,
  onCustomerClick,
}: {
  filters: AdminCashflowFilters
  sort: string
  onSort: (s: string) => void
  orderQ: string
  customerQ: string
  onCustomerClick?: (name: string) => void
}) {
  const [page, setPage] = useState(1)
  useEffect(() => setPage(1), [sort, orderQ, customerQ])
  const { data, isLoading } = useReadyNotBilled(filters, {
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
      <ReadyTable
        rows={rows}
        loading={isLoading}
        sort={sort}
        onSort={onSort}
        onCustomerClick={onCustomerClick}
      />
      <Pager page={page} pages={pages} total={total} size={EXPANDED_PAGE_SIZE} onChange={setPage} />
    </>
  )
}

export function ReadyNotBilledCard({ filters, onCustomerClick }: Props) {
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<string>("ship_asc")
  const [orderQ, setOrderQ] = useState("")
  const [customerQ, setCustomerQ] = useState("")
  const [expanded, setExpanded] = useState(false)
  const dOrderQ = useDebounce(orderQ, 300)
  const dCustomerQ = useDebounce(customerQ, 300)

  useEffect(() => setPage(1), [sort, dOrderQ, dCustomerQ])

  const { data, isLoading } = useReadyNotBilled(filters, {
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

  const csvHref = adminCashflowCsvUrl("ready-not-billed", filters, {
    sort,
    orderQ: dOrderQ,
    customerQ: dCustomerQ,
  })

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Stamp className="h-4 w-4 text-[#B45309]" />
          <div className="text-sm font-semibold text-[#1B3A5C]">
            Ready to bill but not billed
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
            title="Download all ready-but-not-billed rows in current filters as CSV"
          />
        </div>
      </div>
      <div className="mb-1 text-[10px] text-[#6B7280]">Days = Today − BOL Recv</div>
      <ColumnFilters
        orderQ={orderQ}
        customerQ={customerQ}
        onOrder={setOrderQ}
        onCustomer={setCustomerQ}
      />
      <ReadyTable
        rows={rows}
        loading={isLoading}
        sort={sort}
        onSort={setSort}
        onCustomerClick={onCustomerClick}
      />
      <Pager page={page} pages={pages} total={total} size={PAGE_SIZE} onChange={setPage} />

      {expanded && (
        <UnbilledExpandModal
          title="Ready to bill but not billed"
          subtitle={`${fmtCount(total)} loads · ${fmtUsd(grand)} — all orders in current filters`}
          onClose={() => setExpanded(false)}
        >
          <ColumnFilters
            orderQ={orderQ}
            customerQ={customerQ}
            onOrder={setOrderQ}
            onCustomer={setCustomerQ}
          />
          <ReadyExpanded
            filters={filters}
            sort={sort}
            onSort={setSort}
            orderQ={dOrderQ}
            customerQ={dCustomerQ}
            onCustomerClick={onCustomerClick}
          />
        </UnbilledExpandModal>
      )}
    </div>
  )
}
