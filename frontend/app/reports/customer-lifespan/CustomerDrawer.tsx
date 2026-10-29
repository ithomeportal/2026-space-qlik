"use client"

import { X } from "lucide-react"
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
  COLORS,
  fmtDate,
  fmtInt,
  fmtMonth,
  fmtMonths,
  fmtPct,
  fmtUsd,
  fmtUsdCompact,
  useCustomer,
  type Division,
  type Window,
} from "@/lib/customer-lifespan-api"
import { ErrorBox, Loading, StatusChip } from "./ui"

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">{label}</div>
      <div className="text-sm font-semibold tabular-nums text-[#111827]">{value}</div>
    </div>
  )
}

/** Side panel: one customer's months since the first load (the workbook's per-customer sheet). */
export function CustomerDrawer({ division, window, customerId, onClose }: {
  division: Division
  window: Window
  customerId: string
  onClose: () => void
}) {
  const { data, error, isLoading } = useCustomer(division, window, customerId)
  const c = data?.data
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={onClose}>
      <aside
        className="h-full w-full max-w-3xl overflow-y-auto bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-[#1B3A5C]">{c?.name ?? customerId}</h2>
            <div className="mt-1 flex items-center gap-2 text-xs text-[#6B7280]">
              {customerId} {c && <StatusChip status={c.status} />} {c?.divisions.join(" · ")}
            </div>
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-[#6B7280] hover:bg-[#F3F4F6]">
            <X className="h-4 w-4" />
          </button>
        </div>
        {error ? <ErrorBox error={error} /> : null}
        {(isLoading || !c) && !error && <Loading />}
        {c && (
          <>
            <div className="grid grid-cols-3 gap-3 rounded-lg bg-[#F9FAFB] p-3 sm:grid-cols-6">
              <Fact label="First load" value={fmtDate(c.first_ship)} />
              <Fact label="Last load" value={fmtDate(c.last_ship)} />
              <Fact label="Lifespan" value={fmtMonths(c.lifespan_months)} />
              <Fact label="Months shipping" value={fmtInt(c.active_months)} />
              <Fact label="Came back" value={`${c.reactivations}×`} />
              <Fact label="Days quiet" value={fmtInt(c.days_since_last)} />
              <Fact label="Loads" value={fmtInt(c.loads)} />
              <Fact label="Revenue" value={fmtUsdCompact(c.revenue)} />
              <Fact label="Margin" value={fmtUsdCompact(c.margin)} />
              <Fact label="Margin %" value={fmtPct(c.margin_pct)} />
              <Fact label="Margin / month" value={fmtUsd(c.avg_monthly_margin)} />
              <Fact label="First-load year" value={String(c.cohort_year)} />
            </div>
            <div className="mt-4 h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={c.series.map((p) => ({ ...p, label: fmtMonth(p.month) }))} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
                  <XAxis dataKey="label" tick={{ fontSize: 10 }} minTickGap={16} />
                  <YAxis yAxisId="usd" tickFormatter={(v: number) => fmtUsdCompact(v)} tick={{ fontSize: 11 }} width={56} />
                  <YAxis yAxisId="pct" orientation="right" tickFormatter={(v: number) => `${v}%`} tick={{ fontSize: 11 }} width={40} />
                  <Tooltip
                    formatter={(v, name) => [name === "Margin %" ? fmtPct(Number(v)) : fmtUsd(Number(v)), String(name)]}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar yAxisId="usd" dataKey="revenue" name="Revenue" fill={COLORS.revenue} />
                  <Bar yAxisId="usd" dataKey="margin" name="Margin" fill={COLORS.margin} />
                  <Line yAxisId="pct" dataKey="margin_pct" name="Margin %" stroke={COLORS.navy} dot={false} connectNulls={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <table className="mt-4 w-full text-xs">
              <thead className="bg-[#F9FAFB] text-[#6B7280]">
                <tr>
                  <th className="px-2 py-1 text-left font-medium">Month</th>
                  <th className="px-2 py-1 text-right font-medium">Loads</th>
                  <th className="px-2 py-1 text-right font-medium">Revenue</th>
                  <th className="px-2 py-1 text-right font-medium">Margin</th>
                  <th className="px-2 py-1 text-right font-medium">Margin %</th>
                </tr>
              </thead>
              <tbody>
                {[...c.series].reverse().filter((p) => p.loads > 0).map((p) => (
                  <tr key={p.month} className="border-t border-[#F3F4F6] tabular-nums">
                    <td className="px-2 py-1">{fmtMonth(p.month)}</td>
                    <td className="px-2 py-1 text-right">{fmtInt(p.loads)}</td>
                    <td className="px-2 py-1 text-right">{fmtUsd(p.revenue)}</td>
                    <td className={`px-2 py-1 text-right ${p.margin < 0 ? "text-[#DC2626]" : ""}`}>{fmtUsd(p.margin)}</td>
                    <td className="px-2 py-1 text-right">{fmtPct(p.margin_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </aside>
    </div>
  )
}
