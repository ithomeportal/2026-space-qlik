"use client"

import { Loader2 } from "lucide-react"
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
  useBookerWeekly,
  type BookerScopeFilters,
} from "@/lib/booker-scorecard-api"

interface Props {
  scope: BookerScopeFilters
}

/**
 * Bars = # Orders, lines = OTP / OTD, by week, last 10 weeks (Bruno Request 6).
 *
 * Deliberately date-filter-independent: it takes only the Customer / Contract
 * Type / Posted By scope, and the endpoint declares no date params at all. The
 * caption says so on screen — an unlabelled chart that ignores the filter bar
 * above it reads as a bug.
 */
export function WeeklyChart({ scope }: Props) {
  const { data, isLoading, error } = useBookerWeekly(scope)
  const weeks = data?.data?.weeks ?? []

  // Percentages travel as fractions; Recharts needs the display value so the
  // axis, the tooltip and the line all agree.
  const rows = weeks.map((w) => ({
    label: w.label,
    orders: w.orders,
    otp: w.otp_pct === null ? null : w.otp_pct * 100,
    otd: w.otd_pct === null ? null : w.otd_pct * 100,
  }))

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-sm font-semibold text-[#1B3A5C]">
          Orders &amp; service — last 10 weeks
        </div>
        <div className="text-[10px] text-[#9CA3AF]">
          Weeks start Monday · not affected by the Date filter · Customer /
          Contract / Posted By do apply
        </div>
      </div>

      {error ? (
        <div className="py-8 text-center text-xs text-[#991B1B]">
          Could not load the trend:{" "}
          {error instanceof Error ? error.message : "unknown error"}
        </div>
      ) : isLoading && rows.length === 0 ? (
        <div className="flex h-[260px] items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart
            data={rows}
            margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} />
            <YAxis
              yAxisId="left"
              tick={{ fontSize: 10 }}
              allowDecimals={false}
            />
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={[0, 100]}
              tick={{ fontSize: 10 }}
              tickFormatter={(v) => `${v}%`}
            />
            <Tooltip
              formatter={(value, name) => {
                if (value === null || value === undefined) return ["—", name]
                if (name === "# Orders")
                  return [Number(value).toLocaleString("en-US"), name]
                return [`${Number(value).toFixed(1)}%`, name]
              }}
              labelFormatter={(v) => `Week of ${v}`}
            />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            <Bar
              yAxisId="left"
              dataKey="orders"
              name="# Orders"
              fill="#93C5FD"
              radius={[3, 3, 0, 0]}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="otp"
              name="OTP"
              stroke="#059669"
              strokeWidth={2}
              dot={{ r: 3 }}
              connectNulls
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="otd"
              name="OTD"
              stroke="#D97706"
              strokeWidth={2}
              dot={{ r: 3 }}
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
