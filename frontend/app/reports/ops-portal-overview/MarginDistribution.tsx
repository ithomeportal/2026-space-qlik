"use client"

import { Loader2 } from "lucide-react"
import {
  useOppMarginDistribution,
  fmtUsd,
  fmtCount,
  type OppFilters,
  type OppMarginBucket,
} from "@/lib/ops-portal-overview-api"

type BucketKey = "lt_0" | "0_5" | "5_10" | "10_15" | "15_20" | "gte_20"

const BUCKET_ORDER: BucketKey[] = [
  "lt_0",
  "0_5",
  "5_10",
  "10_15",
  "15_20",
  "gte_20",
]

const BUCKET_LABEL: Record<BucketKey, string> = {
  lt_0: "< 0%",
  "0_5": "0–5%",
  "5_10": "5–10%",
  "10_15": "10–15%",
  "15_20": "15–20%",
  gte_20: "≥ 20%",
}

const BUCKET_COLOR: Record<BucketKey, string> = {
  lt_0: "bg-[#DC2626]",
  "0_5": "bg-[#F97316]",
  "5_10": "bg-[#F59E0B]",
  "10_15": "bg-[#EAB308]",
  "15_20": "bg-[#16A34A]",
  gte_20: "bg-[#15803D]",
}

export function MarginDistribution({ filters }: { filters: OppFilters }) {
  const { data, isLoading, isError } = useOppMarginDistribution(filters)

  // R18: per-bucket count + header summary read ORDERS, not customers.
  const byBucket = new Map<string, OppMarginBucket>(
    (data?.data ?? []).map((r) => [r.bucket, r]),
  )
  const rows = BUCKET_ORDER.map((bucket) => ({
    bucket,
    orders: byBucket.get(bucket)?.orders ?? 0,
    revenue: byBucket.get(bucket)?.revenue ?? 0,
  }))

  // Pinned Totals come from the server-side full-universe aggregate (meta),
  // never a client reduce over the bucket list.
  const meta = data?.meta ?? {}
  const totalOrders = Number(meta.total_orders ?? 0)
  const totalRevenue = Number(meta.total_revenue ?? 0)
  const hasData = rows.some((r) => r.orders > 0)

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      {isError && (
        <div className="mb-2 rounded border border-[#DC2626] bg-[#FEF2F2] px-2 py-1 text-[11px] text-[#DC2626]">
          Margin distribution failed to load.
        </div>
      )}
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#1B3A5C]">
          Margin distribution
        </h3>
        <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">
          {fmtCount(totalOrders)} orders · {fmtUsd(totalRevenue)} revenue
        </div>
      </div>
      {isLoading ? (
        <div className="flex h-16 items-center justify-center">
          <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />
        </div>
      ) : !hasData ? (
        <div className="text-xs text-[#6B7280]">No data in window.</div>
      ) : (
        <>
          <div className="flex h-3 w-full overflow-hidden rounded-full bg-[#F3F4F6]">
            {rows.map((r) => {
              const pct = totalOrders ? (r.orders / totalOrders) * 100 : 0
              return (
                <div
                  key={r.bucket}
                  className={BUCKET_COLOR[r.bucket]}
                  style={{ width: `${pct}%` }}
                  title={`${BUCKET_LABEL[r.bucket]}: ${r.orders} orders (${pct.toFixed(1)}%)`}
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
                  {fmtCount(r.orders)}
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
