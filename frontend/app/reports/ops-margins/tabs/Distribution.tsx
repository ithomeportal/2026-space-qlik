"use client"

import { Loader2 } from "lucide-react"
import { useOpsDistribution, type OpsFilters, type OpsDistributionRow } from "@/lib/ops-margins-api"
import { OpsErrorBanner } from "../ErrorBanner"
import { fmtUsd, fmtCount } from "../format"

const BUCKET_LABEL: Record<OpsDistributionRow["bucket"], string> = {
  lt_0: "< 0%",
  "0_5": "0–5%",
  "5_10": "5–10%",
  "10_15": "10–15%",
  "15_20": "15–20%",
  gte_20: "≥ 20%",
  no_revenue: "no revenue",
}

const BUCKET_COLOR: Record<OpsDistributionRow["bucket"], string> = {
  lt_0: "bg-[#DC2626]",
  "0_5": "bg-[#F97316]",
  "5_10": "bg-[#F59E0B]",
  "10_15": "bg-[#EAB308]",
  "15_20": "bg-[#16A34A]",
  gte_20: "bg-[#15803D]",
  no_revenue: "bg-[#9CA3AF]",
}

export function Distribution({ filters }: { filters: OpsFilters }) {
  const { data, isLoading, error } = useOpsDistribution(filters)
  const rows = (data?.data ?? []).filter((r) => r.bucket !== "no_revenue")
  const totalCustomers = rows.reduce((s, r) => s + r.customers, 0)
  const totalRevenue = rows.reduce((s, r) => s + r.revenue, 0)

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <OpsErrorBanner errors={[error]} label="Margin distribution" />
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#1B3A5C]">
          Margin distribution
        </h3>
        <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">
          {fmtCount(totalCustomers)} customers · {fmtUsd(totalRevenue)} revenue
        </div>
      </div>
      {isLoading ? (
        <div className="flex h-16 items-center justify-center">
          <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />
        </div>
      ) : rows.length === 0 ? (
        <div className="text-xs text-[#6B7280]">No data in window.</div>
      ) : (
        <>
          <div className="flex h-3 w-full overflow-hidden rounded-full bg-[#F3F4F6]">
            {rows.map((r) => {
              const pct = totalCustomers ? (r.customers / totalCustomers) * 100 : 0
              return (
                <div
                  key={r.bucket}
                  className={BUCKET_COLOR[r.bucket]}
                  style={{ width: `${pct}%` }}
                  title={`${BUCKET_LABEL[r.bucket]}: ${r.customers} customers (${pct.toFixed(1)}%)`}
                />
              )
            })}
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-xs md:grid-cols-6">
            {rows.map((r) => (
              <div
                key={r.bucket}
                className="rounded border border-[#E5E7EB] px-2 py-1"
              >
                <div className="flex items-center gap-1">
                  <span className={`inline-block h-2 w-2 rounded-full ${BUCKET_COLOR[r.bucket]}`} />
                  <span className="text-[10px] uppercase tracking-wider text-[#6B7280]">
                    {BUCKET_LABEL[r.bucket]}
                  </span>
                </div>
                <div className="mt-0.5 text-sm font-semibold text-[#111827]">
                  {fmtCount(r.customers)}
                </div>
                <div className="text-[10px] text-[#6B7280]">{fmtUsd(r.revenue)}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
