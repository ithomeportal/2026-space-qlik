"use client"

import {
  Bar,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  useOcsPuOverview,
  useOcsPuPinned,
  type OcsFilters,
  type OcsRollingPoint,
} from "@/lib/ops-customer-score-api"
import { OcsErrorBanner } from "../ErrorBanner"
import { fmtCount, fmtMonthBucket, fmtPct, onTimeColor } from "../format"

interface Props {
  filters: OcsFilters
}

function KpiCard({
  title,
  orders,
  fail,
  pct,
}: {
  title: string
  orders: number
  fail: number
  pct: number | null
}) {
  return (
    <div className="rounded-md border border-[#E5E7EB] bg-white p-2">
      <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">
        {title}
      </div>
      <div className="mt-1 grid grid-cols-3 gap-2">
        <div>
          <div className="text-[9px] text-[#6B7280]">Orders</div>
          <div className="text-sm font-semibold text-[#111827] tabular-nums">
            {fmtCount(orders)}
          </div>
        </div>
        <div>
          <div className="text-[9px] text-[#6B7280]">Service Fail</div>
          <div className="text-sm font-semibold text-[#DC2626] tabular-nums">
            {fmtCount(fail)}
          </div>
        </div>
        <div>
          <div className="text-[9px] text-[#6B7280]">% On Time</div>
          <div className={`text-sm font-semibold tabular-nums ${onTimeColor(pct)}`}>
            {fmtPct(pct)}
          </div>
        </div>
      </div>
    </div>
  )
}

function FilteredKpiCard({
  orders,
  fail,
  pct,
}: {
  orders: number
  fail: number
  pct: number | null
}) {
  return (
    <div className="rounded-md border border-[#E5E7EB] bg-white p-2 text-center">
      <div className="text-[10px] uppercase tracking-wide text-[#6B7280]">
        PU Service Fail (filtered)
      </div>
      <div className="mt-0.5 text-2xl font-bold text-[#DC2626] leading-tight tabular-nums">
        {fmtCount(fail)}
      </div>
      <div className="text-[10px] text-[#6B7280]">
        out of {fmtCount(orders)} orders ·{" "}
        <span className={onTimeColor(pct)}>
          {fmtPct(pct)} on time
        </span>
      </div>
    </div>
  )
}

interface ComboRow {
  label: string
  fail: number
  pct: number | null
}

function RollingComboChart({
  title,
  rows,
  bucketLabel,
  barColor,
  lineColor,
}: {
  title: string
  rows: OcsRollingPoint[]
  bucketLabel: (r: OcsRollingPoint) => string
  barColor: string
  lineColor: string
}) {
  const chart: ComboRow[] = rows.map((r) => ({
    label: bucketLabel(r),
    fail: r.fail || 0,
    pct: r.pct_on_time,
  }))
  const hasData = chart.length > 0
  return (
    <div className="rounded-md border border-[#E5E7EB] bg-white p-3">
      <div className="mb-2 text-sm font-medium text-[#374151]">{title}</div>
      {!hasData ? (
        <div className="flex h-[220px] items-center justify-center text-xs text-[#9CA3AF]">
          No data
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={chart} margin={{ top: 16, right: 12, left: 0, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={0} />
            <YAxis yAxisId="left" tick={{ fontSize: 10 }} allowDecimals={false} />
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={[0, 100]}
              tick={{ fontSize: 10 }}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              formatter={(v, name) => {
                if (name === "% On Time") {
                  const num = Number(v)
                  return Number.isFinite(num) ? `${num.toFixed(2)}%` : "—"
                }
                return fmtCount(Number(v))
              }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Bar
              yAxisId="left"
              dataKey="fail"
              fill={barColor}
              name="Service Fail"
              barSize={20}
              radius={[2, 2, 0, 0]}
            >
              <LabelList
                dataKey="fail"
                position="top"
                style={{ fontSize: 9, fill: "#374151" }}
              />
            </Bar>
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="pct"
              stroke={lineColor}
              name="% On Time"
              dot={{ r: 2 }}
              strokeWidth={2}
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

export function PuOverview({ filters }: Props) {
  const pinned = useOcsPuPinned(filters)
  const overview = useOcsPuOverview(filters)
  const p = pinned.data?.data
  const o = overview.data?.data

  return (
    <div className="space-y-4">
      <OcsErrorBanner
        errors={[pinned.error, overview.error]}
        label="PU Overview"
      />

      {/* Top row: 3 pinned KPI cards + filtered KPI card, all compact */}
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          title="This Month"
          orders={p?.kpi_month.orders ?? 0}
          fail={p?.kpi_month.fail ?? 0}
          pct={p?.kpi_month.pct_on_time ?? null}
        />
        <KpiCard
          title="This Quarter"
          orders={p?.kpi_quarter.orders ?? 0}
          fail={p?.kpi_quarter.fail ?? 0}
          pct={p?.kpi_quarter.pct_on_time ?? null}
        />
        <KpiCard
          title="This Year"
          orders={p?.kpi_year.orders ?? 0}
          fail={p?.kpi_year.fail ?? 0}
          pct={p?.kpi_year.pct_on_time ?? null}
        />
        <FilteredKpiCard
          orders={o?.kpi.orders ?? 0}
          fail={o?.kpi.fail ?? 0}
          pct={o?.kpi.pct_on_time ?? null}
        />
      </div>

      {/* Service Incident By Team + By Customer — half and half */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="rounded-md border border-[#E5E7EB] bg-white">
          <div className="px-3 py-2 text-sm font-medium text-[#374151] border-b border-[#E5E7EB]">
            # Service Incident By Team (PU)
          </div>
          <div className="overflow-x-auto max-h-[380px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-[#F9FAFB] text-[#6B7280] sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left">Team</th>
                  <th className="px-3 py-2 text-right">PU Order</th>
                  <th className="px-3 py-2 text-right">PU Service Fail</th>
                  <th className="px-3 py-2 text-right">% On Time</th>
                </tr>
              </thead>
              <tbody>
                {(o?.by_team ?? []).map((r) => (
                  <tr key={r.team_id ?? "?"} className="border-t border-[#F3F4F6]">
                    <td className="px-3 py-2 text-[#111827] font-medium">
                      {r.team_id || "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {fmtCount(r.orders)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-[#DC2626]">
                      {fmtCount(r.fail)}
                    </td>
                    <td
                      className={`px-3 py-2 text-right tabular-nums ${onTimeColor(r.pct_on_time)}`}
                    >
                      {fmtPct(r.pct_on_time)}
                    </td>
                  </tr>
                ))}
                {!o?.by_team.length && (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-3 py-6 text-center text-[#9CA3AF]"
                    >
                      {overview.isLoading ? "Loading…" : "No data"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-md border border-[#E5E7EB] bg-white">
          <div className="px-3 py-2 text-sm font-medium text-[#374151] border-b border-[#E5E7EB]">
            # Service Incident By Customer (PU) — top 100 by fail count
          </div>
          <div className="overflow-x-auto max-h-[380px] overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-[#F9FAFB] text-[#6B7280] sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left">Customer</th>
                  <th className="px-3 py-2 text-right">PU Order</th>
                  <th className="px-3 py-2 text-right">PU Service Fail</th>
                  <th className="px-3 py-2 text-right">% On Time</th>
                </tr>
              </thead>
              <tbody>
                {(o?.by_customer ?? []).map((r) => (
                  <tr
                    key={r.customer_name ?? "?"}
                    className="border-t border-[#F3F4F6]"
                  >
                    <td className="px-3 py-2 text-[#111827]">
                      {r.customer_name || "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {fmtCount(r.orders)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-[#DC2626]">
                      {fmtCount(r.fail)}
                    </td>
                    <td
                      className={`px-3 py-2 text-right tabular-nums ${onTimeColor(r.pct_on_time)}`}
                    >
                      {fmtPct(r.pct_on_time)}
                    </td>
                  </tr>
                ))}
                {!o?.by_customer.length && (
                  <tr>
                    <td
                      colSpan={4}
                      className="px-3 py-6 text-center text-[#9CA3AF]"
                    >
                      {overview.isLoading ? "Loading…" : "No data"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Service Incident By Delay Code */}
      <div className="rounded-md border border-[#E5E7EB] bg-white p-3">
        <div className="mb-3 text-sm font-medium text-[#374151]">
          # Service Incident By Delay Code (PU)
        </div>
        <div className="space-y-1">
          {(o?.by_delay ?? []).map((r) => {
            const max = Math.max(1, ...(o?.by_delay ?? []).map((x) => x.fail))
            const w = Math.max(2, (r.fail / max) * 100)
            return (
              <div
                key={r.edi_standard_code ?? "?"}
                className="flex items-center gap-2"
              >
                <div className="w-12 text-xs font-mono text-[#374151]">
                  {r.edi_standard_code || "—"}
                </div>
                <div className="flex-1 bg-[#F3F4F6] rounded-sm h-5 relative">
                  <div
                    className="absolute inset-y-0 left-0 bg-[#3B82F6] rounded-sm"
                    style={{ width: `${w}%` }}
                  />
                </div>
                <div className="w-16 text-right text-xs tabular-nums text-[#111827]">
                  {fmtCount(r.fail)}
                </div>
              </div>
            )
          })}
          {!o?.by_delay.length && (
            <div className="py-4 text-center text-xs text-[#9CA3AF]">
              {overview.isLoading ? "Loading…" : "No data"}
            </div>
          )}
        </div>
      </div>

      {/* Rolling 12 months — combo chart, ignores date filter */}
      <RollingComboChart
        title="Incident — Rolling Last 12 Months (PU)"
        rows={p?.rolling_12m ?? []}
        bucketLabel={(r) => fmtMonthBucket(r.bucket)}
        barColor="#DC2626"
        lineColor="#1B3A5C"
      />

      {/* Rolling 10 weeks — combo chart, ignores date filter */}
      <RollingComboChart
        title="Incident — Rolling Last 10 Weeks (PU)"
        rows={p?.rolling_10w ?? []}
        bucketLabel={(r) => r.label ?? "—"}
        barColor="#DC2626"
        lineColor="#1B3A5C"
      />

      <div className="text-[11px] text-[#6B7280]">
        Pinned KPIs &amp; rolling charts ignore the date filter (snapshot view).
      </div>
    </div>
  )
}
