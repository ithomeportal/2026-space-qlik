"use client"

import {
  useOcsDelOverview,
  useOcsDelPinned,
  type OcsFilters,
} from "@/lib/ops-customer-score-api"
import { OcsErrorBanner } from "../ErrorBanner"
import {
  fmtCount,
  fmtMonthBucket,
  fmtPct,
  onTimeColor,
} from "../format"

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
    <div className="rounded-md border border-[#A7F3D0] bg-[#F0FDF4] p-3">
      <div className="text-xs uppercase tracking-wide text-[#065F46]">
        {title}
      </div>
      <div className="mt-2 grid grid-cols-3 gap-3">
        <div>
          <div className="text-[10px] text-[#065F46]">Orders</div>
          <div className="text-base font-semibold text-[#111827]">
            {fmtCount(orders)}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-[#065F46]">Service Fail</div>
          <div className="text-base font-semibold text-[#DC2626]">
            {fmtCount(fail)}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-[#065F46]">% On Time</div>
          <div className={`text-base font-semibold ${onTimeColor(pct)}`}>
            {fmtPct(pct)}
          </div>
        </div>
      </div>
    </div>
  )
}

function RollingChart({
  title,
  rows,
  bucketLabel,
}: {
  title: string
  rows: Array<{
    bucket: string | null
    label?: string
    fail: number
    pct_on_time: number | null
  }>
  bucketLabel: (r: { bucket: string | null; label?: string }) => string
}) {
  const maxFail = Math.max(1, ...rows.map((r) => r.fail))
  return (
    <div className="rounded-md border border-[#E5E7EB] bg-white p-3">
      <div className="mb-3 text-sm font-medium text-[#374151]">{title}</div>
      <div className="grid grid-cols-12 gap-1 items-end h-40">
        {rows.map((r, i) => {
          const h = Math.max(2, (r.fail / maxFail) * 100)
          return (
            <div key={i} className="flex flex-col items-center justify-end">
              <div
                className="w-full bg-[#10B981] rounded-sm"
                style={{ height: `${h}%` }}
                title={`${r.fail} fails · ${fmtPct(r.pct_on_time)} on time`}
              />
              <div className="mt-1 text-[10px] text-[#6B7280] text-center leading-tight">
                {bucketLabel(r)}
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-2 grid grid-cols-12 gap-1 text-[10px] text-[#6B7280]">
        {rows.map((r, i) => (
          <div key={i} className="text-center">
            {r.fail || 0}
          </div>
        ))}
      </div>
    </div>
  )
}

export function DelOverview({ filters }: Props) {
  const pinned = useOcsDelPinned(filters)
  const overview = useOcsDelOverview(filters)
  const p = pinned.data?.data
  const o = overview.data?.data

  return (
    <div className="space-y-4">
      <OcsErrorBanner
        errors={[pinned.error, overview.error]}
        label="DEL Overview"
      />

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
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
      </div>

      <div className="rounded-md border border-[#A7F3D0] bg-[#F0FDF4] p-4 text-center">
        <div className="text-xs uppercase tracking-wide text-[#065F46]">
          DEL Service Fail (filtered)
        </div>
        <div className="mt-1 text-4xl font-bold text-[#DC2626]">
          {fmtCount(o?.kpi.fail ?? 0)}
        </div>
        <div className="mt-1 text-xs text-[#065F46]">
          out of {fmtCount(o?.kpi.orders ?? 0)} orders ·{" "}
          <span className={onTimeColor(o?.kpi.pct_on_time ?? null)}>
            {fmtPct(o?.kpi.pct_on_time ?? null)} on time
          </span>
        </div>
      </div>

      <div className="rounded-md border border-[#E5E7EB] bg-white">
        <div className="px-3 py-2 text-sm font-medium text-[#374151] border-b border-[#E5E7EB]">
          # Service Incident By Team (DEL)
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-[#F9FAFB] text-[#6B7280]">
              <tr>
                <th className="px-3 py-2 text-left">Team</th>
                <th className="px-3 py-2 text-right">DEL Order</th>
                <th className="px-3 py-2 text-right">DEL Service Fail</th>
                <th className="px-3 py-2 text-right">DEL % On Time</th>
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
          # Service Incident By Customer (DEL) — top 100 by fail count
        </div>
        <div className="overflow-x-auto max-h-[480px] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="bg-[#F9FAFB] text-[#6B7280] sticky top-0">
              <tr>
                <th className="px-3 py-2 text-left">Customer</th>
                <th className="px-3 py-2 text-right">DEL Order</th>
                <th className="px-3 py-2 text-right">DEL Service Fail</th>
                <th className="px-3 py-2 text-right">DEL % On Time</th>
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

      <div className="rounded-md border border-[#E5E7EB] bg-white p-3">
        <div className="mb-3 text-sm font-medium text-[#374151]">
          # Service Incident By Delay Code (DEL)
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
                    className="absolute inset-y-0 left-0 bg-[#10B981] rounded-sm"
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

      <RollingChart
        title="Incident — Rolling Last 12 Months (DEL)"
        rows={p?.rolling_12m ?? []}
        bucketLabel={(r) => fmtMonthBucket(r.bucket)}
      />

      <RollingChart
        title="Incident — Rolling Last 10 Weeks (DEL)"
        rows={p?.rolling_10w ?? []}
        bucketLabel={(r) => r.label ?? "—"}
      />

      <div className="text-[11px] text-[#6B7280]">
        Pinned KPIs &amp; rolling charts ignore the date filter (snapshot view).
      </div>
    </div>
  )
}
