"use client"

import { Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useXrayDfwAttrition,
  useXrayDfwByCustomer,
  useXrayDfwByLane,
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

export function CustomersLanes({
  filters,
  entityLabel = "Customer",
  onCustomerClick,
  onLaneClick,
}: Props) {
  const { data: custRes, isLoading: loadingCust, error: custErr } = useXrayDfwByCustomer(filters)
  const { data: laneRes, isLoading: loadingLane, error: laneErr } = useXrayDfwByLane(filters)
  const trioFilter = {
    subTeams: filters.subTeams,
    customers: filters.customers,
    lanes: filters.lanes,
    view: filters.view,
  }
  const { data: attrRes, isLoading: loadingAttr, error: attrErr } = useXrayDfwAttrition(trioFilter)
  const customers = custRes?.data ?? []
  const lanes = laneRes?.data ?? []
  const attrition = attrRes?.data ?? []

  const custSort = useSortable(customers)
  const laneSort = useSortable(lanes)
  const attrSort = useSortable(attrition)

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
      <XrayDfwErrorBanner label="Customers & Lanes" errors={[custErr, laneErr, attrErr]} />
      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#E5E7EB] bg-[#F3F4F6] px-3 py-2 text-sm font-semibold text-[#111827]">
          Profit by {entityLabel}
          <span className="ml-2 text-xs text-[#6B7280]">({customers.length} {entityLabel.toLowerCase()}s)</span>
        </div>
        {loadingCust ? (
          <Spin />
        ) : (
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#F9FAFB] text-[#6B7280]">
                <tr>
                  <SortableTh label={entityLabel} columnKey="customer_name" state={custSort} />
                  <SortableTh label="# Loads" columnKey="loads" state={custSort} align="right" />
                  <SortableTh label="$ Revenue" columnKey="revenue" state={custSort} align="right" />
                  <SortableTh label="$ Profit" columnKey="profit" state={custSort} align="right" />
                  <SortableTh label="Margin %" columnKey="margin_pct" state={custSort} align="right" />
                  <SortableTh label="OTP %" columnKey="otp_pct" state={custSort} align="right" />
                  <SortableTh label="OTD %" columnKey="otd_pct" state={custSort} align="right" />
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
                {custSort.sorted.map((r) => (
                  <tr key={r.customer_name} className="border-t border-[#F3F4F6] hover:bg-[#F9FAFB]">
                    <td className="px-3 py-1.5">
                      <ClickName value={r.customer_name} onClick={onCustomerClick} />
                    </td>
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

      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#E5E7EB] bg-[#F3F4F6] px-3 py-2 text-sm font-semibold text-[#111827]">
          Profit by Lane
          <span className="ml-2 text-xs text-[#6B7280]">({lanes.length} lanes)</span>
        </div>
        {loadingLane ? (
          <Spin />
        ) : (
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#F9FAFB] text-[#6B7280]">
                <tr>
                  <SortableTh label="Lane" columnKey="lane" state={laneSort} />
                  <SortableTh label="# Loads" columnKey="loads" state={laneSort} align="right" />
                  <SortableTh label="$ Revenue" columnKey="revenue" state={laneSort} align="right" />
                  <SortableTh label="$ Profit" columnKey="profit" state={laneSort} align="right" />
                  <SortableTh label="Margin %" columnKey="margin_pct" state={laneSort} align="right" />
                  <SortableTh label="OTP %" columnKey="otp_pct" state={laneSort} align="right" />
                  <SortableTh label="OTD %" columnKey="otd_pct" state={laneSort} align="right" />
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
                {laneSort.sorted.map((r) => (
                  <tr key={r.lane} className="border-t border-[#F3F4F6] hover:bg-[#F9FAFB]">
                    <td className="px-3 py-1.5">
                      <ClickName value={r.lane} onClick={onLaneClick} />
                    </td>
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

      <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
        <div className="border-b border-[#E5E7EB] bg-[#F3F4F6] px-3 py-2 text-sm font-semibold text-[#111827]">
          Attrition — Details by Lanes
          <span className="ml-2 text-xs text-[#6B7280]">sorted by days since last load</span>
        </div>
        {loadingAttr ? (
          <Spin />
        ) : (
          <div className="max-h-[500px] overflow-auto">
            <table className="w-full text-xs tabular-nums">
              <thead className="sticky top-0 bg-[#F9FAFB] text-[#6B7280]">
                <tr>
                  <SortableTh label={entityLabel} columnKey="customer_name" state={attrSort} />
                  <SortableTh label="Lane" columnKey="lane" state={attrSort} />
                  <SortableTh label="# Loads" columnKey="loads" state={attrSort} align="right" />
                  <SortableTh label="$ Revenue" columnKey="revenue" state={attrSort} align="right" />
                  <SortableTh label="$ Profit" columnKey="profit" state={attrSort} align="right" />
                  <SortableTh label="% Margin" columnKey="margin_pct" state={attrSort} align="right" />
                  <SortableTh label="OTP %" columnKey="otp_pct" state={attrSort} align="right" />
                  <SortableTh label="OTD %" columnKey="otd_pct" state={attrSort} align="right" />
                  <SortableTh label="Last Load" columnKey="last_load_date" state={attrSort} align="right" />
                  <SortableTh label="Days" columnKey="days_since" state={attrSort} align="right" />
                </tr>
              </thead>
              <tbody>
                {attrSort.sorted.map((r, i) => (
                  <tr key={i} className="border-t border-[#F3F4F6] hover:bg-[#F9FAFB]">
                    <td className="px-3 py-1.5">
                      <ClickName value={r.customer_name} onClick={onCustomerClick} />
                    </td>
                    <td className="px-3 py-1.5">
                      <ClickName value={r.lane} onClick={onLaneClick} />
                    </td>
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

function ClickName({
  value,
  onClick,
}: {
  value: string
  onClick?: (v: string) => void
}) {
  if (!onClick) return <>{value}</>
  return (
    <button
      type="button"
      onClick={() => onClick(value)}
      className="text-left hover:text-[#1B3A5C] hover:underline"
      title="Filter by this value"
    >
      {value}
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
