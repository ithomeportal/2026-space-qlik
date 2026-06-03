"use client"

import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react"
import { useEffect, useState } from "react"
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useXrayDfwAllOrders,
  useXrayDfwContractSpot,
  useXrayDfwLaneAnalysis,
  type XrayDfwFilters,
} from "@/lib/xray-dfw-api"
import { useSortable, SortableTh } from "@/components/SortableTable"
import { XrayDfwErrorBanner } from "../ErrorBanner"

interface Props {
  filters: XrayDfwFilters
  entityLabel?: string
  onCustomerClick?: (name: string) => void
  onLaneClick?: (lane: string) => void
}

const fmtBucket = (s: string) => {
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return s
  return `${d.toLocaleString("en-US", { month: "short" })} ${String(d.getDate()).padStart(2, "0")}`
}

export function ContractSpot({
  filters,
  entityLabel = "Customer",
  onCustomerClick,
  onLaneClick,
}: Props) {
  const trioFilter = {
    subTeams: filters.subTeams,
    customers: filters.customers,
    lanes: filters.lanes,
    view: filters.view,
  }
  // Bruno 2026-06-03: All Orders is server-paginated, 500/page. Reset to
  // page 1 whenever the filter scope changes.
  const [page, setPage] = useState(1)
  const filterKey = JSON.stringify(filters)
  useEffect(() => {
    setPage(1)
  }, [filterKey])

  const { data: csRes, isLoading: loadingCs, error: csErr } = useXrayDfwContractSpot(trioFilter)
  const { data: ordersRes, isLoading: loadingOrd, error: ordErr } = useXrayDfwAllOrders(filters, page)
  const { data: laRes, isLoading: loadingLa, error: laErr } = useXrayDfwLaneAnalysis(filters)
  const cs = csRes?.data
  const ordersPage = ordersRes?.data
  const orders = ordersPage?.rows ?? []
  const ordersTotals = ordersPage?.totals
  const lanes = laRes?.data?.rows ?? []
  const laneTotals = laRes?.data?.totals

  const totalOrders = ordersPage?.total ?? 0
  const pageSize = ordersPage?.page_size ?? 500
  const pageCount = Math.max(1, Math.ceil(totalOrders / pageSize))

  const orderSort = useSortable(orders)
  const laneSort = useSortable(lanes)

  return (
    <div className="space-y-6">
      <XrayDfwErrorBanner label="Contract vs Spot" errors={[csErr, ordErr, laErr]} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <ChartCard title="% Contract — Revenue vs Loads" subtitle="Last 9 weeks" loading={loadingCs}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={cs?.contract ?? []} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
              <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} />
              <Tooltip labelFormatter={(v) => fmtBucket(String(v))} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey="revenue" name="$ Revenue" fill="#38BDF8" />
              <Line yAxisId="right" type="monotone" dataKey="loads" name="# Loads" stroke="#DC2626" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="% Contract — Profit vs Margin" subtitle="Last 9 weeks" loading={loadingCs}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={cs?.contract ?? []} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
              <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
              <Tooltip labelFormatter={(v) => fmtBucket(String(v))} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey="profit" name="$ Profit" fill="#CA8A04" />
              <Line yAxisId="right" type="monotone" dataKey="margin_pct" name="% Margin" stroke="#9333EA" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="% Spot — Revenue vs Loads" subtitle="Last 9 weeks" loading={loadingCs}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={cs?.spot ?? []} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
              <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} />
              <Tooltip labelFormatter={(v) => fmtBucket(String(v))} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey="revenue" name="$ Revenue" fill="#38BDF8" />
              <Line yAxisId="right" type="monotone" dataKey="loads" name="# Loads" stroke="#DC2626" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="% Spot — Profit vs Margin" subtitle="Last 9 weeks" loading={loadingCs}>
          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={cs?.spot ?? []} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} tickFormatter={fmtBucket} />
              <YAxis yAxisId="left" tick={{ fontSize: 10 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10 }} tickFormatter={(v) => `${v}%`} />
              <Tooltip labelFormatter={(v) => fmtBucket(String(v))} />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar yAxisId="left" dataKey="profit" name="$ Profit" fill="#CA8A04" />
              <Line yAxisId="right" type="monotone" dataKey="margin_pct" name="% Margin" stroke="#9333EA" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </ChartCard>
      </div>

      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E5E7EB] bg-[#FEF3C7] px-3 py-2 text-sm font-semibold text-[#111827]">
          <div>
            All Orders
            <span className="ml-2 text-xs font-normal text-[#6B7280]">
              {fmtCount(totalOrders)} orders · 500 per page · most recent departure first
            </span>
          </div>
          {/* Bruno 2026-06-03: server pagination, 500/page. */}
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
        {loadingOrd ? (
          <Spin />
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
                  <SortableTh label="$ Revenue" columnKey="revenue" state={orderSort} align="right" />
                  <SortableTh label="$ Profit" columnKey="profit" state={orderSort} align="right" />
                  <SortableTh label="Margin %" columnKey="margin_pct" state={orderSort} align="right" />
                  <SortableTh label="Diff 15%" columnKey="diff_15" state={orderSort} align="right" />
                  <SortableTh label="Diff 18%" columnKey="diff_18" state={orderSort} align="right" />
                  <SortableTh label="Diff 20%" columnKey="diff_20" state={orderSort} align="right" />
                </tr>
              </thead>
              <tbody>
                {/* Bruno 2026-06-03: universe Totals row (all pages, not just
                    the visible one). */}
                {ordersTotals && (
                  <tr className="sticky top-[29px] z-10 bg-[#FDE68A] font-semibold">
                    <td className="px-3 py-1.5" colSpan={7}>
                      Totals ({fmtCount(ordersTotals.loads)} orders)
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(ordersTotals.revenue)}</td>
                    <td className={`px-3 py-1.5 text-right ${ordersTotals.profit < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtUsd(ordersTotals.profit)}
                    </td>
                    <td className={`px-3 py-1.5 text-right ${ordersTotals.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtPct(ordersTotals.margin_pct)}
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(ordersTotals.diff_15)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(ordersTotals.diff_18)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(ordersTotals.diff_20)}</td>
                  </tr>
                )}
                {orderSort.sorted.map((r) => (
                  <tr key={r.id} className="border-t border-[#F3F4F6] hover:bg-[#FEFCE8]">
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
                    <td className="px-3 py-1.5">{r.departure ? r.departure.substring(0, 16).replace("T", " ") : "—"}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                    <td className={`px-3 py-1.5 text-right ${r.profit < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtUsd(r.profit)}
                    </td>
                    <td className={`px-3 py-1.5 text-right ${r.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtPct(r.margin_pct)}
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_15)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_18)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_20)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#E5E7EB] bg-[#EDE9FE] px-3 py-2 text-sm font-semibold text-[#111827]">
          Lane Production Analysis
          <span className="ml-2 text-xs text-[#6B7280]">sorted by profit concentration</span>
        </div>
        {loadingLa ? (
          <Spin />
        ) : (
          <div className="max-h-[500px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#EDE9FE] text-[#6B7280]">
                <tr>
                  <SortableTh label={entityLabel} columnKey="customer" state={laneSort} />
                  <SortableTh label="Origin" columnKey="origin" state={laneSort} />
                  <SortableTh label="Destination" columnKey="destination" state={laneSort} />
                  <SortableTh label="Conc %" columnKey="conc_pct" state={laneSort} align="right" />
                  <SortableTh label="# Loads" columnKey="loads" state={laneSort} align="right" />
                  <SortableTh label="$ Revenue" columnKey="revenue" state={laneSort} align="right" />
                  <SortableTh label="$ Profit" columnKey="profit" state={laneSort} align="right" />
                  <SortableTh label="Margin %" columnKey="margin_pct" state={laneSort} align="right" />
                  <SortableTh label="AVG R/L" columnKey="avg_r_per_l" state={laneSort} align="right" />
                  <SortableTh label="AVG P/L" columnKey="avg_p_per_l" state={laneSort} align="right" />
                  <SortableTh label="Diff 15%" columnKey="diff_15" state={laneSort} align="right" />
                  <SortableTh label="Diff 18%" columnKey="diff_18" state={laneSort} align="right" />
                  <SortableTh label="Diff 20%" columnKey="diff_20" state={laneSort} align="right" />
                </tr>
              </thead>
              <tbody>
                {/* Bruno 2026-06-03: universe Totals row over ALL lanes. */}
                {laneTotals && (
                  <tr className="sticky top-[29px] z-10 bg-[#DDD6FE] font-semibold">
                    <td className="px-3 py-1.5" colSpan={3}>Totals</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(laneTotals.conc_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(laneTotals.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(laneTotals.revenue)}</td>
                    <td className={`px-3 py-1.5 text-right ${laneTotals.profit < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtUsd(laneTotals.profit)}
                    </td>
                    <td className={`px-3 py-1.5 text-right ${laneTotals.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtPct(laneTotals.margin_pct)}
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(laneTotals.avg_r_per_l)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(laneTotals.avg_p_per_l)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(laneTotals.diff_15)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(laneTotals.diff_18)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(laneTotals.diff_20)}</td>
                  </tr>
                )}
                {laneSort.sorted.map((r, i) => (
                  <tr key={i} className="border-t border-[#F3F4F6] hover:bg-[#FAF5FF]">
                    <td className="px-3 py-1.5">
                      <ClickName value={r.customer} onClick={onCustomerClick} />
                    </td>
                    <td className="px-3 py-1.5">{r.origin}</td>
                    <td className="px-3 py-1.5">
                      <ClickName
                        value={`${r.origin} - ${r.destination}`}
                        display={r.destination}
                        onClick={onLaneClick}
                      />
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(r.conc_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(r.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                    <td className={`px-3 py-1.5 text-right ${r.profit < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtUsd(r.profit)}
                    </td>
                    <td className={`px-3 py-1.5 text-right ${r.margin_pct < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtPct(r.margin_pct)}
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.avg_r_per_l)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.avg_p_per_l)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_15)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_18)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.diff_20)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

function ClickName({
  value,
  display,
  onClick,
}: {
  value: string
  display?: string
  onClick?: (v: string) => void
}) {
  const text = display ?? value
  if (!onClick) return <>{text}</>
  return (
    <button
      type="button"
      onClick={() => onClick(value)}
      className="text-left hover:text-[#1B3A5C] hover:underline"
      title="Filter by this value"
    >
      {text}
    </button>
  )
}

function Spin() {
  return (
    <div className="flex h-40 items-center justify-center">
      <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
    </div>
  )
}

function ChartCard({
  title,
  subtitle,
  children,
  loading,
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
  loading?: boolean
}) {
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <div className="mb-2">
        <div className="text-sm font-semibold text-[#111827]">{title}</div>
        {subtitle && <div className="text-[10px] text-[#6B7280]">{subtitle}</div>}
      </div>
      {loading ? <Spin /> : children}
    </div>
  )
}
