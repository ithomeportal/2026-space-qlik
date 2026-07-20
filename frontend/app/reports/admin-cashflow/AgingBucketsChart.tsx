"use client"

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { Loader2 } from "lucide-react"
import { useAgingBuckets, type AdminCashflowFilters } from "@/lib/admin-cashflow-api"
import { fmtCount } from "./format"

interface Props {
  filters: AdminCashflowFilters
}

// Bruno PDF 2026-07-20: buckets recut to the ≤2 target — 0-2 green (on target),
// then amber → orange → red as the delivery-to-bill gap widens.
const BUCKET_COLORS: Record<string, string> = {
  "<0": "#9CA3AF",
  "0-2": "#10B981",
  "3-5": "#F59E0B",
  "6-10": "#F97316",
  "11-15": "#EF4444",
  ">15": "#B91C1C",
}

export function AgingBucketsChart({ filters }: Props) {
  const { data, isLoading } = useAgingBuckets(filters)
  const buckets = data?.data?.buckets ?? []
  const total = data?.data?.total ?? 0

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-baseline justify-between">
        <div>
          <div className="text-sm font-semibold text-[#1B3A5C]">
            Delivery → Bill aging distribution
          </div>
          <div className="text-[11px] text-[#6B7280]">
            Days between dest_actual_departure and bill_date · target
            ≤2
          </div>
        </div>
        <div className="text-xs text-[#6B7280]">
          {fmtCount(total)} loads
        </div>
      </div>
      <div className="h-52">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-[#6B7280]">
            <Loader2 className="h-4 w-4 animate-spin" />
          </div>
        ) : buckets.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-[#9CA3AF]">
            No data for current filters
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={buckets} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: "#6B7280" }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#6B7280" }}
                axisLine={false}
                tickLine={false}
                width={40}
              />
              <Tooltip
                cursor={{ fill: "#F3F4F6" }}
                contentStyle={{
                  fontSize: 12,
                  borderRadius: 6,
                  border: "1px solid #E5E7EB",
                  padding: "6px 10px",
                }}
                formatter={(v) => [fmtCount(v as number), "Loads"]}
                labelFormatter={(l) => `${l} days`}
              />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {buckets.map((b) => (
                  <Cell
                    key={b.label}
                    fill={BUCKET_COLORS[b.label] ?? "#1B3A5C"}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
