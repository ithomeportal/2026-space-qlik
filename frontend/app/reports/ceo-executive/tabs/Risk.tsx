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

interface Props {
  filters: CeoFilters
}

export function Risk({ filters }: Props) {
  const { data, isLoading, error } = useCeoRisk(filters)
  const d = data?.data

  return (
    <div className="space-y-6">
      <CeoErrorBanner label="Risk" errors={[error]} />

      <WorstLanesTable rows={d?.worst_lanes ?? []} loading={isLoading} />
      <NegOrdersTable rows={d?.neg_orders ?? []} loading={isLoading} />
      <NegCustomersTable rows={d?.neg_customers ?? []} loading={isLoading} />
    </div>
  )
}

function WorstLanesTable({ rows, loading }: { rows: CeoWorstLane[]; loading?: boolean }) {
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
        Worst Margins by Lanes <span className="text-xs font-normal opacity-75">· margin_amt &lt; 0</span>
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full min-w-[1100px] text-[11px] tabular-nums">
            <thead className="sticky top-0 bg-[#FEE2E2] text-[#991B1B]">
              <tr>
                <th className="px-2 py-1 text-left">Customer</th>
                <th className="px-2 py-1 text-left">Origin</th>
                <th className="px-2 py-1 text-left">Destination</th>
                <th className="px-1 py-1 text-right"># Loads</th>
                <th className="px-1 py-1 text-right">$ Revenue</th>
                <th className="px-1 py-1 text-right">$ Profit</th>
                <th className="px-1 py-1 text-right">Margin %</th>
                <th className="px-1 py-1 text-right">15% Diff+</th>
                <th className="px-1 py-1 text-right">18% Diff+</th>
                <th className="px-1 py-1 text-right">20% Diff+</th>
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
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-[#F3F4F6]">
                  <td className="px-2 py-1 truncate max-w-[180px]">{r.customer}</td>
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

function NegOrdersTable({ rows, loading }: { rows: CeoNegOrder[]; loading?: boolean }) {
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
        Negative Loads Totals by Order <span className="text-xs font-normal opacity-75">· margin_amt &lt; 0</span>
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[480px] overflow-auto">
          <table className="w-full min-w-[1100px] text-[11px] tabular-nums">
            <thead className="sticky top-0 bg-[#FEE2E2] text-[#991B1B]">
              <tr>
                <th className="px-2 py-1 text-left">Order</th>
                <th className="px-2 py-1 text-left">Customer</th>
                <th className="px-2 py-1 text-left">Carrier</th>
                <th className="px-2 py-1 text-left">Origin</th>
                <th className="px-2 py-1 text-left">Destination</th>
                <th className="px-1 py-1 text-right">$ Revenue</th>
                <th className="px-1 py-1 text-right">$ Profit</th>
                <th className="px-1 py-1 text-right">Margin %</th>
                <th className="px-1 py-1 text-right">Conc %</th>
              </tr>
            </thead>
            <tbody>
              <tr className="sticky top-[26px] bg-[#FECACA] font-semibold">
                <td className="px-2 py-1" colSpan={5}>Totals ({rows.length})</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.revenue)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.profit)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(totMargin)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(tot.conc_pct)}</td>
              </tr>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-[#F3F4F6]">
                  <td className="px-2 py-1">{r.id}</td>
                  <td className="px-2 py-1 truncate max-w-[180px]">{r.customer}</td>
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

function NegCustomersTable({ rows, loading }: { rows: CeoNegCustomer[]; loading?: boolean }) {
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
        Negative Loads Total Amount by Customer <span className="text-xs font-normal opacity-75">· margin_amt &lt; 0</span>
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[440px] overflow-auto">
          <table className="w-full text-[11px] tabular-nums">
            <thead className="sticky top-0 bg-[#FEE2E2] text-[#991B1B]">
              <tr>
                <th className="px-2 py-1 text-left">Customer</th>
                <th className="px-1 py-1 text-right"># Loads</th>
                <th className="px-1 py-1 text-right">$ Revenue</th>
                <th className="px-1 py-1 text-right">$ Profit</th>
                <th className="px-1 py-1 text-right">Conc %</th>
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
              {rows.map((r) => (
                <tr key={r.customer} className="border-t border-[#F3F4F6]">
                  <td className="px-2 py-1 truncate max-w-[260px]">{r.customer}</td>
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
