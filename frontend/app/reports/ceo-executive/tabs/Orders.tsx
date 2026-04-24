"use client"

import { Loader2 } from "lucide-react"
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

interface Props {
  filters: CeoFilters
}

export function Orders({ filters }: Props) {
  const { data, isLoading, error } = useCeoOrders(filters)
  const d = data?.data

  return (
    <div className="space-y-6">
      <CeoErrorBanner label="Orders" errors={[error]} />
      <LanePanel rows={d?.lane_analysis ?? []} loading={isLoading} />
      <AllOrdersPanel rows={d?.all_orders ?? []} loading={isLoading} />
    </div>
  )
}

function LanePanel({ rows, loading }: { rows: CeoLaneAnalysis[]; loading?: boolean }) {
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
        Lane Production Analysis
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
                <th className="px-2 py-1 text-left">Customer</th>
                <th className="px-2 py-1 text-left">Origin</th>
                <th className="px-2 py-1 text-left">Destination</th>
                <th className="px-1 py-1 text-right">Conc %</th>
                <th className="px-1 py-1 text-right"># Loads</th>
                <th className="px-1 py-1 text-right">$ Revenue</th>
                <th className="px-1 py-1 text-right">$ Profit</th>
                <th className="px-1 py-1 text-right">Margin %</th>
                <th className="px-1 py-1 text-right">AVG R / L</th>
                <th className="px-1 py-1 text-right">AVG P / L</th>
                <th className="px-1 py-1 text-right">15% Diff+</th>
                <th className="px-1 py-1 text-right">18% Diff+</th>
                <th className="px-1 py-1 text-right">20% Diff+</th>
              </tr>
            </thead>
            <tbody>
              <tr className="sticky top-[26px] bg-[#DDD6FE] font-semibold">
                <td className="px-2 py-1" colSpan={3}>Totals</td>
                <td className="px-1 py-1 text-right">100.00%</td>
                <td className="px-1 py-1 text-right">{fmtCount(tot.loads)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.revenue)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.profit)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(totMargin)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(rpl)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(ppl)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_15)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_18)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_20)}</td>
              </tr>
              {rows.map((r, i) => {
                const margBg =
                  r.margin_pct >= 15 ? "text-[#065F46] font-semibold"
                  : r.margin_pct < 5 ? "text-[#991B1B] font-semibold"
                  : ""
                const avgRpl = r.loads > 0 ? r.revenue / r.loads : 0
                const avgPpl = r.loads > 0 ? r.profit / r.loads : 0
                return (
                  <tr key={i} className="border-t border-[#F3F4F6]">
                    <td className="px-2 py-1 truncate max-w-[200px]">{r.customer}</td>
                    <td className="px-2 py-1 truncate max-w-[140px]">{r.origin}</td>
                    <td className="px-2 py-1 truncate max-w-[140px]">{r.destination}</td>
                    <td className="px-1 py-1 text-right">{fmtPct(r.conc_pct)}</td>
                    <td className="px-1 py-1 text-right">{fmtCount(r.loads)}</td>
                    <td className="px-1 py-1 text-right">{fmtUsd(r.revenue)}</td>
                    <td className="px-1 py-1 text-right">{fmtUsd(r.profit)}</td>
                    <td className={`px-1 py-1 text-right ${margBg}`}>{fmtPct(r.margin_pct)}</td>
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

function AllOrdersPanel({ rows, loading }: { rows: CeoAllOrder[]; loading?: boolean }) {
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

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="bg-[#FEF3C7] px-3 py-2 text-sm font-semibold text-[#92400E]">
        All Orders <span className="text-xs font-normal opacity-75">· first 1,000 rows by departure desc</span>
      </div>
      {loading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <div className="max-h-[600px] overflow-auto">
          <table className="w-full min-w-[1600px] text-[11px] tabular-nums">
            <thead className="sticky top-0 bg-[#FEF3C7] text-[#92400E]">
              <tr>
                <th className="px-2 py-1 text-left">Team</th>
                <th className="px-2 py-1 text-left">Order</th>
                <th className="px-2 py-1 text-left">Customer</th>
                <th className="px-2 py-1 text-left">Carrier</th>
                <th className="px-2 py-1 text-left">Origin</th>
                <th className="px-2 py-1 text-left">Destination</th>
                <th className="px-2 py-1 text-left">Departure</th>
                <th className="px-1 py-1 text-right">$ Revenue</th>
                <th className="px-1 py-1 text-right">$ Profit</th>
                <th className="px-1 py-1 text-right">Margin %</th>
                <th className="px-1 py-1 text-right">15% Diff+</th>
                <th className="px-1 py-1 text-right">18% Diff+</th>
                <th className="px-1 py-1 text-right">20% Diff+</th>
              </tr>
            </thead>
            <tbody>
              <tr className="sticky top-[26px] bg-[#FDE68A] font-semibold">
                <td className="px-2 py-1" colSpan={7}>Totals ({rows.length})</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.revenue)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.profit)}</td>
                <td className="px-1 py-1 text-right">{fmtPct(totMargin)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_15)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_18)}</td>
                <td className="px-1 py-1 text-right">{fmtUsd(tot.diff_20)}</td>
              </tr>
              {rows.map((r) => {
                const margBg =
                  r.margin_pct < 0 ? "text-[#991B1B] font-semibold"
                  : r.margin_pct >= 15 ? "text-[#065F46] font-semibold"
                  : ""
                return (
                  <tr key={r.id} className="border-t border-[#F3F4F6]">
                    <td className="px-2 py-1">{r.team}</td>
                    <td className="px-2 py-1">{r.id}</td>
                    <td className="px-2 py-1 truncate max-w-[180px]">{r.customer}</td>
                    <td className="px-2 py-1 truncate max-w-[160px]">{r.carrier}</td>
                    <td className="px-2 py-1 truncate max-w-[130px]">{r.origin}</td>
                    <td className="px-2 py-1 truncate max-w-[130px]">{r.destination}</td>
                    <td className="px-2 py-1">{fmtDeparture(r.departure)}</td>
                    <td className="px-1 py-1 text-right">{fmtUsd(r.revenue)}</td>
                    <td className="px-1 py-1 text-right">{fmtUsd(r.profit)}</td>
                    <td className={`px-1 py-1 text-right ${margBg}`}>{fmtPct(r.margin_pct)}</td>
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
