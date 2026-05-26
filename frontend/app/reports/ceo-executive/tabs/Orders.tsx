"use client"

import { useEffect, useState } from "react"
import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useCeoOrders,
  type CeoAllOrder,
  type CeoFilters,
  type CeoLaneAnalysis,
} from "@/lib/ceo-api"
import { CeoErrorBanner } from "../ErrorBanner"
import { marginCellClass } from "../margin-color"
import { SortableTh, useSortable } from "../sortable"
import { CustomerLink } from "../customer-cell"

interface Props {
  filters: CeoFilters
  onCustomerSelect?: (customer: string) => void
}

export function Orders({ filters, onCustomerSelect }: Props) {
  // Bruno R7 (2026-05-26): All Orders is server-paginated. Reset to page 1
  // whenever the filter set changes so we never page past a shrunken result.
  const [page, setPage] = useState(1)
  useEffect(() => {
    setPage(1)
  }, [filters])

  const { data, isLoading, error } = useCeoOrders(filters, page)
  const d = data?.data

  return (
    <div className="space-y-6">
      <CeoErrorBanner label="Orders" errors={[error]} />
      <LanePanel rows={d?.lane_analysis ?? []} loading={isLoading} onCustomerSelect={onCustomerSelect} />
      <AllOrdersPanel
        rows={d?.all_orders ?? []}
        loading={isLoading}
        total={d?.all_orders_total ?? 0}
        page={d?.page ?? page}
        pageSize={d?.page_size ?? 100}
        onPageChange={setPage}
        onCustomerSelect={onCustomerSelect}
      />
    </div>
  )
}

function LanePanel({
  rows,
  loading,
  onCustomerSelect,
}: {
  rows: CeoLaneAnalysis[]
  loading?: boolean
  onCustomerSelect?: (customer: string) => void
}) {
  const { sorted, sortKey, sortDir, toggle } = useSortable<CeoLaneAnalysis>(rows, "profit", "desc")
  const tot = rows.reduce(
    (acc, r) => ({
      loads: acc.loads + (r.loads ?? 0),
      revenue: acc.revenue + (r.revenue ?? 0),
      profit: acc.profit + (r.profit ?? 0),
      diff_15: acc.diff_15 + (r.diff_15 ?? 0),
      diff_18: acc.diff_18 + (r.diff_18 ?? 0),
      diff_20: acc.diff_20 + (r.diff_20 ?? 0),
    }),
    { loads: 0, revenue: 0, profit: 0, diff_15: 0, diff_18: 0, diff_20: 0 },
  )
  const totMargin = tot.revenue > 0 ? (tot.profit / tot.revenue) * 100 : 0
  const rpl = tot.loads > 0 ? tot.revenue / tot.loads : 0
  const ppl = tot.loads > 0 ? tot.profit / tot.loads : 0

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="bg-[#EDE9FE] px-3 py-2 text-sm font-semibold text-[#5B21B6]">
        Lane Production Analysis <span className="text-xs font-normal opacity-75">· click headers to sort</span>
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[540px] overflow-auto">
          <table className="w-full min-w-[1400px] text-[11px] tabular-nums">
            <thead className="sticky top-0 bg-[#EDE9FE] text-[#5B21B6]">
              <tr>
                <SortableTh<CeoLaneAnalysis> columnKey="customer" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Customer</SortableTh>
                <SortableTh<CeoLaneAnalysis> columnKey="origin" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Origin</SortableTh>
                <SortableTh<CeoLaneAnalysis> columnKey="destination" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Destination</SortableTh>
                <SortableTh<CeoLaneAnalysis> columnKey="conc_pct" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Conc %</SortableTh>
                <SortableTh<CeoLaneAnalysis> columnKey="loads" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}># Loads</SortableTh>
                <SortableTh<CeoLaneAnalysis> columnKey="revenue" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Revenue</SortableTh>
                <SortableTh<CeoLaneAnalysis> columnKey="profit" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Profit</SortableTh>
                <SortableTh<CeoLaneAnalysis> columnKey="margin_pct" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Margin %</SortableTh>
                <th className="px-1 py-1 text-right">AVG R / L</th>
                <th className="px-1 py-1 text-right">AVG P / L</th>
                <SortableTh<CeoLaneAnalysis> columnKey="diff_15" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>15% Diff+</SortableTh>
                <SortableTh<CeoLaneAnalysis> columnKey="diff_18" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>18% Diff+</SortableTh>
                <SortableTh<CeoLaneAnalysis> columnKey="diff_20" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>20% Diff+</SortableTh>
              </tr>
            </thead>
            <tbody>
              <tr className="sticky top-[26px] bg-[#DDD6FE] font-semibold">
                <td className="px-2 py-1" colSpan={3}>Totals</td>
                <td className="px-1 py-1 text-right">100.00%</td>
                <td className="px-1 py-1 text-right">{fmtCount(tot.loads)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.revenue)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.profit)}</td>
                <td className={`px-1 py-1 text-right ${marginCellClass(totMargin)}`}>{fmtPct(totMargin)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(rpl)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(ppl)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_15)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_18)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_20)}</td>
              </tr>
              {sorted.map((r, i) => {
                const avgRpl = r.loads > 0 ? r.revenue / r.loads : 0
                const avgPpl = r.loads > 0 ? r.profit / r.loads : 0
                return (
                  <tr key={i} className="border-t border-[#F3F4F6]">
                    <td className="px-2 py-1">
                      <CustomerLink name={r.customer} onSelect={onCustomerSelect} className="block truncate max-w-[200px]" />
                    </td>
                    <td className="px-2 py-1 truncate max-w-[140px]">{r.origin}</td>
                    <td className="px-2 py-1 truncate max-w-[140px]">{r.destination}</td>
                    <td className="px-1 py-1 text-right">{fmtPct(r.conc_pct)}</td>
                    <td className="px-1 py-1 text-right">{fmtCount(r.loads)}</td>
                    <td className="px-1 py-1 text-right">{fmtUsd(r.revenue)}</td>
                    <td className="px-1 py-1 text-right">{fmtUsd(r.profit)}</td>
                    <td className={`px-1 py-1 text-right ${marginCellClass(r.margin_pct)}`}>{fmtPct(r.margin_pct)}</td>
                    <td className="px-1 py-1 text-right">{fmtUsd(avgRpl)}</td>
                    <td className="px-1 py-1 text-right">{fmtUsd(avgPpl)}</td>
                    <td className="px-1 py-1 text-right">{fmtUsd(r.diff_15)}</td>
                    <td className="px-1 py-1 text-right">{fmtUsd(r.diff_18)}</td>
                    <td className="px-1 py-1 text-right">{fmtUsd(r.diff_20)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function AllOrdersPanel({
  rows,
  loading,
  total,
  page,
  pageSize,
  onPageChange,
  onCustomerSelect,
}: {
  rows: CeoAllOrder[]
  loading?: boolean
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number) => void
  onCustomerSelect?: (customer: string) => void
}) {
  // Sorting acts on the current page only (rows are server-paginated).
  const { sorted, sortKey, sortDir, toggle } = useSortable<CeoAllOrder>(rows, "departure", "desc")
  const fmtDeparture = (iso: string | null) => {
    if (!iso) return "—"
    const d = new Date(iso)
    return `${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}/${String(d.getFullYear()).slice(2)} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
  }
  const tot = rows.reduce(
    (acc, r) => ({
      revenue: acc.revenue + (r.revenue ?? 0),
      profit: acc.profit + (r.profit ?? 0),
      diff_15: acc.diff_15 + (r.diff_15 ?? 0),
      diff_18: acc.diff_18 + (r.diff_18 ?? 0),
      diff_20: acc.diff_20 + (r.diff_20 ?? 0),
    }),
    { revenue: 0, profit: 0, diff_15: 0, diff_18: 0, diff_20: 0 },
  )
  const totMargin = tot.revenue > 0 ? (tot.profit / tot.revenue) * 100 : 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const firstRow = total === 0 ? 0 : (page - 1) * pageSize + 1
  const lastRow = Math.min(page * pageSize, total)

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 bg-[#FEF3C7] px-3 py-2 text-[#92400E]">
        <div className="text-sm font-semibold">
          All Orders{" "}
          <span className="text-xs font-normal opacity-75">
            · {firstRow.toLocaleString()}–{lastRow.toLocaleString()} of {total.toLocaleString()} · by departure desc · click headers to sort
          </span>
        </div>
        <PageControls page={page} totalPages={totalPages} disabled={loading} onPageChange={onPageChange} />
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[600px] overflow-auto">
          {/* Bruno R7: Team · Contract Type · Order · Departure · Customer · … */}
          <table className="w-full min-w-[1600px] text-[11px] tabular-nums">
            <thead className="sticky top-0 bg-[#FEF3C7] text-[#92400E]">
              <tr>
                <SortableTh<CeoAllOrder> columnKey="team" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Team</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="contract_type" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Contract Type</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="id" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Order</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="departure" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Departure</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="customer" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Customer</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="carrier" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Carrier</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="origin" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Origin</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="destination" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Destination</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="revenue" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Revenue</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="profit" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Profit</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="margin_pct" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Margin %</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="diff_15" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>15% Diff+</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="diff_18" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>18% Diff+</SortableTh>
                <SortableTh<CeoAllOrder> columnKey="diff_20" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>20% Diff+</SortableTh>
              </tr>
            </thead>
            <tbody>
              <tr className="sticky top-[26px] bg-[#FDE68A] font-semibold">
                <td className="px-2 py-1" colSpan={8}>Page total ({rows.length})</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.revenue)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.profit)}</td>
                <td className={`px-1 py-1 text-right ${marginCellClass(totMargin)}`}>{fmtPct(totMargin)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_15)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_18)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_20)}</td>
              </tr>
              {sorted.map((r) => (
                <tr key={r.id} className="border-t border-[#F3F4F6]">
                  <td className="px-2 py-1">{r.team}</td>
                  <td className="px-2 py-1 whitespace-nowrap">{r.contract_type || "—"}</td>
                  <td className="px-2 py-1">{r.id}</td>
                  <td className="px-2 py-1">{fmtDeparture(r.departure)}</td>
                  <td className="px-2 py-1">
                    <CustomerLink name={r.customer} onSelect={onCustomerSelect} className="block truncate max-w-[180px]" />
                  </td>
                  <td className="px-2 py-1 truncate max-w-[160px]">{r.carrier}</td>
                  <td className="px-2 py-1 truncate max-w-[130px]">{r.origin}</td>
                  <td className="px-2 py-1 truncate max-w-[130px]">{r.destination}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.revenue)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.profit)}</td>
                  <td className={`px-1 py-1 text-right ${marginCellClass(r.margin_pct)}`}>{fmtPct(r.margin_pct)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.diff_15)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.diff_18)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.diff_20)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex items-center justify-end border-t border-[#F3F4F6] bg-[#FFFBEB] px-3 py-2">
        <PageControls page={page} totalPages={totalPages} disabled={loading} onPageChange={onPageChange} />
      </div>
    </section>
  )
}

function PageControls({
  page,
  totalPages,
  disabled,
  onPageChange,
}: {
  page: number
  totalPages: number
  disabled?: boolean
  onPageChange: (page: number) => void
}) {
  const btn =
    "flex items-center gap-1 rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs text-[#374151] hover:bg-[#F3F4F6] disabled:cursor-not-allowed disabled:opacity-40"
  return (
    <div className="flex items-center gap-2 text-xs text-[#6B7280]">
      <button
        type="button"
        className={btn}
        disabled={disabled || page <= 1}
        onClick={() => onPageChange(Math.max(1, page - 1))}
      >
        <ChevronLeft className="h-3.5 w-3.5" />
        Prev
      </button>
      <span className="tabular-nums">
        Page {page} of {totalPages}
      </span>
      <button
        type="button"
        className={btn}
        disabled={disabled || page >= totalPages}
        onClick={() => onPageChange(Math.min(totalPages, page + 1))}
      >
        Next
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
