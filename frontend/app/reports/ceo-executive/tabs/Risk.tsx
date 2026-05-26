"use client"

import { Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useCeoRisk,
  type CeoFilters,
  type CeoNegCustomer,
  type CeoNegOrder,
  type CeoWorstLane,
} from "@/lib/ceo-api"
import { CeoErrorBanner } from "../ErrorBanner"
import { SortableTh, useSortable } from "../sortable"
import { CustomerLink } from "../customer-cell"

interface Props {
  filters: CeoFilters
  onCustomerSelect?: (customer: string) => void
}

export function Risk({ filters, onCustomerSelect }: Props) {
  const { data, isLoading, error } = useCeoRisk(filters)
  const d = data?.data

  // Bruno R7 (2026-05-26): table order — NegCustomers, WorstLanes, NegOrders.
  return (
    <div className="space-y-6">
      <CeoErrorBanner label="Risk" errors={[error]} />

      <NegCustomersTable rows={d?.neg_customers ?? []} loading={isLoading} onCustomerSelect={onCustomerSelect} />
      <WorstLanesTable rows={d?.worst_lanes ?? []} loading={isLoading} onCustomerSelect={onCustomerSelect} />
      <NegOrdersTable rows={d?.neg_orders ?? []} loading={isLoading} onCustomerSelect={onCustomerSelect} />
    </div>
  )
}

function WorstLanesTable({
  rows,
  loading,
  onCustomerSelect,
}: {
  rows: CeoWorstLane[]
  loading?: boolean
  onCustomerSelect?: (customer: string) => void
}) {
  const { sorted, sortKey, sortDir, toggle } = useSortable<CeoWorstLane>(rows, "profit", "asc")
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

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="bg-[#FEE2E2] px-3 py-2 text-sm font-semibold text-[#991B1B]">
        Worst Margins by Lanes <span className="text-xs font-normal opacity-75">· margin_amt &lt; 0 · click headers to sort</span>
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full min-w-[1100px] text-[12.5px] tabular-nums">
            <thead className="sticky top-0 bg-[#FEE2E2] text-[#991B1B]">
              <tr>
                <SortableTh<CeoWorstLane> columnKey="customer" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Customer</SortableTh>
                <SortableTh<CeoWorstLane> columnKey="origin" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Origin</SortableTh>
                <SortableTh<CeoWorstLane> columnKey="destination" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Destination</SortableTh>
                <SortableTh<CeoWorstLane> columnKey="loads" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}># Loads</SortableTh>
                <SortableTh<CeoWorstLane> columnKey="revenue" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Revenue</SortableTh>
                <SortableTh<CeoWorstLane> columnKey="profit" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Profit</SortableTh>
                <SortableTh<CeoWorstLane> columnKey="margin_pct" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Margin %</SortableTh>
                <SortableTh<CeoWorstLane> columnKey="diff_15" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>15% Diff+</SortableTh>
                <SortableTh<CeoWorstLane> columnKey="diff_18" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>18% Diff+</SortableTh>
                <SortableTh<CeoWorstLane> columnKey="diff_20" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>20% Diff+</SortableTh>
              </tr>
            </thead>
            <tbody>
              <tr className="sticky top-[26px] bg-[#FECACA] font-semibold">
                <td className="px-2 py-1" colSpan={3}>Totals</td>
                <td className="px-1 py-1 text-right">{fmtCount(tot.loads)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.revenue)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.profit)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(totMargin)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_15)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_18)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_20)}</td>
              </tr>
              {sorted.map((r, i) => (
                <tr key={i} className="border-t border-[#F3F4F6]">
                  <td className="px-2 py-1">
                    <CustomerLink name={r.customer} onSelect={onCustomerSelect} className="block truncate max-w-[180px]" />
                  </td>
                  <td className="px-2 py-1 truncate max-w-[160px]">{r.origin}</td>
                  <td className="px-2 py-1 truncate max-w-[160px]">{r.destination}</td>
                  <td className="px-1 py-1 text-right">{fmtCount(r.loads)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.revenue)}</td>
                  <td className="px-1 py-1 text-right text-[#991B1B] font-semibold">{fmtUsd(r.profit)}</td>
                  <td className="px-1 py-1 text-right text-[#991B1B] font-semibold">{fmtPct(r.margin_pct)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.diff_15)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.diff_18)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.diff_20)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function NegOrdersTable({
  rows,
  loading,
  onCustomerSelect,
}: {
  rows: CeoNegOrder[]
  loading?: boolean
  onCustomerSelect?: (customer: string) => void
}) {
  const { sorted, sortKey, sortDir, toggle } = useSortable<CeoNegOrder>(rows, "profit", "asc")
  const tot = rows.reduce(
    (acc, r) => ({
      revenue: acc.revenue + (r.revenue ?? 0),
      profit: acc.profit + (r.profit ?? 0),
      conc_pct: acc.conc_pct + (r.conc_pct ?? 0),
    }),
    { revenue: 0, profit: 0, conc_pct: 0 },
  )
  const totMargin = tot.revenue > 0 ? (tot.profit / tot.revenue) * 100 : 0

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="bg-[#FEE2E2] px-3 py-2 text-sm font-semibold text-[#991B1B]">
        Negative Loads Totals by Order <span className="text-xs font-normal opacity-75">· margin_amt &lt; 0 · click headers to sort</span>
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[480px] overflow-auto">
          {/* Bruno R7: Order · Team · Departure · Contract Type · Customer · … */}
          <table className="w-full min-w-[1200px] text-[12.5px] tabular-nums">
            <thead className="sticky top-0 bg-[#FEE2E2] text-[#991B1B]">
              <tr>
                <SortableTh<CeoNegOrder> columnKey="id" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Order</SortableTh>
                <SortableTh<CeoNegOrder> columnKey="team" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Team</SortableTh>
                <SortableTh<CeoNegOrder> columnKey="departure" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Departure</SortableTh>
                <SortableTh<CeoNegOrder> columnKey="contract_type" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Contract Type</SortableTh>
                <SortableTh<CeoNegOrder> columnKey="customer" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Customer</SortableTh>
                <SortableTh<CeoNegOrder> columnKey="carrier" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Carrier</SortableTh>
                <SortableTh<CeoNegOrder> columnKey="origin" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Origin</SortableTh>
                <SortableTh<CeoNegOrder> columnKey="destination" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Destination</SortableTh>
                <SortableTh<CeoNegOrder> columnKey="revenue" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Revenue</SortableTh>
                <SortableTh<CeoNegOrder> columnKey="profit" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Profit</SortableTh>
                <SortableTh<CeoNegOrder> columnKey="margin_pct" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Margin %</SortableTh>
                <SortableTh<CeoNegOrder> columnKey="conc_pct" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Conc %</SortableTh>
              </tr>
            </thead>
            <tbody>
              <tr className="sticky top-[28px] bg-[#FECACA] font-semibold">
                <td className="px-2 py-1" colSpan={8}>Totals ({rows.length})</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.revenue)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.profit)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(totMargin)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(tot.conc_pct)}</td>
              </tr>
              {sorted.map((r) => (
                <tr key={r.id} className="border-t border-[#F3F4F6]">
                  <td className="px-2 py-1">{r.id}</td>
                  <td className="px-2 py-1 whitespace-nowrap">{r.team}</td>
                  <td className="px-2 py-1 whitespace-nowrap">{r.departure ? r.departure.slice(0, 10) : "—"}</td>
                  <td className="px-2 py-1 whitespace-nowrap">{r.contract_type || "—"}</td>
                  <td className="px-2 py-1">
                    <CustomerLink name={r.customer} onSelect={onCustomerSelect} className="block truncate max-w-[180px]" />
                  </td>
                  <td className="px-2 py-1 truncate max-w-[160px]">{r.carrier}</td>
                  <td className="px-2 py-1 truncate max-w-[130px]">{r.origin}</td>
                  <td className="px-2 py-1 truncate max-w-[130px]">{r.destination}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.revenue)}</td>
                  <td className="px-1 py-1 text-right text-[#991B1B] font-semibold">{fmtUsd(r.profit)}</td>
                  <td className="px-1 py-1 text-right text-[#991B1B] font-semibold">{fmtPct(r.margin_pct)}</td>
                  <td className="px-1 py-1 text-right">{fmtPct(r.conc_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function NegCustomersTable({
  rows,
  loading,
  onCustomerSelect,
}: {
  rows: CeoNegCustomer[]
  loading?: boolean
  onCustomerSelect?: (customer: string) => void
}) {
  const { sorted, sortKey, sortDir, toggle } = useSortable<CeoNegCustomer>(rows, "profit", "asc")
  const tot = rows.reduce(
    (acc, r) => ({
      loads: acc.loads + (r.loads ?? 0),
      revenue: acc.revenue + (r.revenue ?? 0),
      profit: acc.profit + (r.profit ?? 0),
      conc_pct: acc.conc_pct + (r.conc_pct ?? 0),
    }),
    { loads: 0, revenue: 0, profit: 0, conc_pct: 0 },
  )
  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="bg-[#FEE2E2] px-3 py-2 text-sm font-semibold text-[#991B1B]">
        Negative Loads Total Amount by Customer <span className="text-xs font-normal opacity-75">· margin_amt &lt; 0 · click headers to sort</span>
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[440px] overflow-auto">
          <table className="w-full text-[12.5px] tabular-nums">
            <thead className="sticky top-0 bg-[#FEE2E2] text-[#991B1B]">
              <tr>
                <SortableTh<CeoNegCustomer> columnKey="customer" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Customer</SortableTh>
                <SortableTh<CeoNegCustomer> columnKey="loads" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}># Loads</SortableTh>
                <SortableTh<CeoNegCustomer> columnKey="revenue" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Revenue</SortableTh>
                <SortableTh<CeoNegCustomer> columnKey="profit" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>$ Profit</SortableTh>
                <SortableTh<CeoNegCustomer> columnKey="conc_pct" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Conc %</SortableTh>
              </tr>
            </thead>
            <tbody>
              <tr className="sticky top-[26px] bg-[#FECACA] font-semibold">
                <td className="px-2 py-1">Totals</td>
                <td className="px-1 py-1 text-right">{fmtCount(tot.loads)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.revenue)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.profit)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(tot.conc_pct)}</td>
              </tr>
              {sorted.map((r) => (
                <tr key={r.customer} className="border-t border-[#F3F4F6]">
                  <td className="px-2 py-1">
                    <CustomerLink name={r.customer} onSelect={onCustomerSelect} className="block truncate max-w-[260px]" />
                  </td>
                  <td className="px-1 py-1 text-right">{fmtCount(r.loads)}</td>
                  <td className="px-1 py-1 text-right">{fmtUsd(r.revenue)}</td>
                  <td className="px-1 py-1 text-right text-[#991B1B] font-semibold">{fmtUsd(r.profit)}</td>
                  <td className="px-1 py-1 text-right">{fmtPct(r.conc_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
