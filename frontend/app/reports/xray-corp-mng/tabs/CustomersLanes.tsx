"use client"

import { Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useXrayAttrition,
  useXrayByCustomer,
  useXrayByLane,
  type XrayFilters,
} from "@/lib/xray-api"
import { XrayErrorBanner } from "../ErrorBanner"

interface Props {
  filters: XrayFilters
}

export function CustomersLanes({ filters }: Props) {
  const { data: custRes, isLoading: loadingCust, error: custErr } = useXrayByCustomer(filters)
  const { data: laneRes, isLoading: loadingLane, error: laneErr } = useXrayByLane(filters)
  const trioFilter = { team: filters.team, customer: filters.customer }
  const { data: attrRes, isLoading: loadingAttr, error: attrErr } = useXrayAttrition(trioFilter)
  const customers = custRes?.data ?? []
  const lanes = laneRes?.data ?? []
  const attrition = attrRes?.data ?? []

  const custTotal = customers.reduce(
    (acc, r) => ({
      loads: acc.loads + Number(r.loads || 0),
      revenue: acc.revenue + Number(r.revenue || 0),
      profit: acc.profit + Number(r.profit || 0),
    }),
    { loads: 0, revenue: 0, profit: 0 },
  )
  const custMarginPct = custTotal.revenue ? (custTotal.profit / custTotal.revenue) * 100 : 0

  const laneTotal = lanes.reduce(
    (acc, r) => ({
      loads: acc.loads + Number(r.loads || 0),
      revenue: acc.revenue + Number(r.revenue || 0),
      profit: acc.profit + Number(r.profit || 0),
    }),
    { loads: 0, revenue: 0, profit: 0 },
  )
  const laneMarginPct = laneTotal.revenue ? (laneTotal.profit / laneTotal.revenue) * 100 : 0

  return (
    <div className="space-y-6">
      <XrayErrorBanner label="Customers & Lanes" errors={[custErr, laneErr, attrErr]} />
      {/* Profit by Customer */}
      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#E5E7EB] bg-[#F3F4F6] px-3 py-2 text-sm font-semibold text-[#111827]">
          Profit by Customer
          <span className="ml-2 text-xs text-[#6B7280]">({customers.length} customers)</span>
        </div>
        {loadingCust ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : (
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#F9FAFB] text-[#6B7280]">
                <tr>
                  <Th className="text-left">Customer</Th>
                  <Th className="text-right"># Loads</Th>
                  <Th className="text-right">$ Revenue</Th>
                  <Th className="text-right">$ Profit</Th>
                  <Th className="text-right">Margin %</Th>
                  <Th className="text-right">OTP %</Th>
                  <Th className="text-right">OTD %</Th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-[#E5E7EB] bg-[#F9FAFB] font-semibold">
                  <td className="px-3 py-1.5">Totals</td>
                  <td className="px-3 py-1.5 text-right">{fmtCount(custTotal.loads)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtUsd(custTotal.revenue)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtUsd(custTotal.profit)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtPct(custMarginPct)}</td>
                  <td className="px-3 py-1.5 text-right">—</td>
                  <td className="px-3 py-1.5 text-right">—</td>
                </tr>
                {customers.map((r) => (
                  <tr key={r.customer_name} className="border-t border-[#F3F4F6] hover:bg-[#F9FAFB]">
                    <td className="px-3 py-1.5">{r.customer_name}</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(r.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                    <td className={`px-3 py-1.5 text-right ${r.profit < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtUsd(r.profit)}
                    </td>
                    <td className={`px-3 py-1.5 text-right ${marginClass(r.margin_pct)}`}>
                      {fmtPct(r.margin_pct)}
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(r.otp_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(r.otd_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Profit by Lane */}
      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#E5E7EB] bg-[#F3F4F6] px-3 py-2 text-sm font-semibold text-[#111827]">
          Profit by Lane
          <span className="ml-2 text-xs text-[#6B7280]">({lanes.length} lanes)</span>
        </div>
        {loadingLane ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : (
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#F9FAFB] text-[#6B7280]">
                <tr>
                  <Th className="text-left">Lane</Th>
                  <Th className="text-right"># Loads</Th>
                  <Th className="text-right">$ Revenue</Th>
                  <Th className="text-right">$ Profit</Th>
                  <Th className="text-right">Margin %</Th>
                  <Th className="text-right">OTP %</Th>
                  <Th className="text-right">OTD %</Th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-[#E5E7EB] bg-[#F9FAFB] font-semibold">
                  <td className="px-3 py-1.5">Totals</td>
                  <td className="px-3 py-1.5 text-right">{fmtCount(laneTotal.loads)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtUsd(laneTotal.revenue)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtUsd(laneTotal.profit)}</td>
                  <td className="px-3 py-1.5 text-right">{fmtPct(laneMarginPct)}</td>
                  <td className="px-3 py-1.5 text-right">—</td>
                  <td className="px-3 py-1.5 text-right">—</td>
                </tr>
                {lanes.map((r) => (
                  <tr key={r.lane} className="border-t border-[#F3F4F6] hover:bg-[#F9FAFB]">
                    <td className="px-3 py-1.5">{r.lane}</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(r.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                    <td className={`px-3 py-1.5 text-right ${r.profit < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtUsd(r.profit)}
                    </td>
                    <td className={`px-3 py-1.5 text-right ${marginClass(r.margin_pct)}`}>
                      {fmtPct(r.margin_pct)}
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(r.otp_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(r.otd_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Attrition — sorted by days since last load */}
      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#E5E7EB] bg-[#F3F4F6] px-3 py-2 text-sm font-semibold text-[#111827]">
          Attrition — Details by Lanes
          <span className="ml-2 text-xs text-[#6B7280]">sorted by days since last load</span>
        </div>
        {loadingAttr ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : (
          <div className="max-h-[500px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#F9FAFB] text-[#6B7280]">
                <tr>
                  <Th className="text-left">Customer</Th>
                  <Th className="text-left">Lane</Th>
                  <Th className="text-right"># Loads</Th>
                  <Th className="text-right">$ Revenue</Th>
                  <Th className="text-right">$ Profit</Th>
                  <Th className="text-right">% Margin</Th>
                  <Th className="text-right">OTP %</Th>
                  <Th className="text-right">OTD %</Th>
                  <Th className="text-right">Last Load</Th>
                  <Th className="text-right">Days</Th>
                </tr>
              </thead>
              <tbody>
                {attrition.map((r, i) => (
                  <tr key={i} className="border-t border-[#F3F4F6] hover:bg-[#F9FAFB]">
                    <td className="px-3 py-1.5">{r.customer_name}</td>
                    <td className="px-3 py-1.5">{r.lane}</td>
                    <td className="px-3 py-1.5 text-right">{fmtCount(r.loads)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtUsd(r.revenue)}</td>
                    <td className={`px-3 py-1.5 text-right ${r.profit < 0 ? "text-[#DC2626]" : ""}`}>
                      {fmtUsd(r.profit)}
                    </td>
                    <td className={`px-3 py-1.5 text-right ${marginClass(r.margin_pct)}`}>
                      {fmtPct(r.margin_pct)}
                    </td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(r.otp_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{fmtPct(r.otd_pct)}</td>
                    <td className="px-3 py-1.5 text-right">{r.last_load_date ?? "—"}</td>
                    <td className={`px-3 py-1.5 text-right font-semibold ${daysClass(r.days_since)}`}>
                      {fmtCount(r.days_since)}
                    </td>
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

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <th className={`px-3 py-1.5 font-semibold ${className}`}>{children}</th>
}

function marginClass(pct: number) {
  if (pct < 0) return "bg-[#FEE2E2] text-[#DC2626]"
  if (pct < 10) return "bg-[#FEF3C7] text-[#D97706]"
  return "text-[#16A34A]"
}

function daysClass(days: number) {
  if (days === 0) return "text-[#16A34A]"
  if (days <= 3) return "text-[#D97706]"
  return "text-[#DC2626]"
}
