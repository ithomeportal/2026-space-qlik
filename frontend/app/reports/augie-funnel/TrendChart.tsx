"use client"

import { useMemo } from "react"
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
import { parseLocalDate } from "@/lib/local-date"
import type { AugieFunnelGrain, AugieTrendPoint } from "@/lib/augie-funnel-api"
import { EmptyBlock, ErrorBlock, LoadingBlock, Panel, Toggle } from "./Ui"

const GRAINS: { k: AugieFunnelGrain; label: string }[] = [
  { k: "day", label: "Day" },
  { k: "week", label: "Week" },
]

const PCT_SERIES = new Set(["Tracked %", "Captured %"])

interface Props {
  data: AugieTrendPoint[] | undefined
  grain: AugieFunnelGrain
  onGrainChange: (g: AugieFunnelGrain) => void
  loading: boolean
  error: unknown
  singleDay: boolean
}

function label(bucket: string, grain: AugieFunnelGrain) {
  const d = parseLocalDate(bucket)
  const md = d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
  return grain === "week" ? `Wk ${md}` : md
}

export function TrendChart({ data, grain, onGrainChange, loading, error, singleDay }: Props) {
  const rows = useMemo(
    () =>
      (data ?? []).map((p) => ({
        label: label(p.bucket, grain),
        captured: p.captured,
        trackedNoInfo: Math.max(p.tracked - p.captured, 0),
        notTracked: Math.max(p.pickups - p.tracked, 0),
        trackedPct: p.tracked_pct,
        capturedPct: p.captured_pct,
      })),
    [data, grain],
  )

  let body
  if (singleDay) {
    body = <EmptyBlock h={200} msg="Pick a longer range to see the trend." />
  } else if (error) {
    body = <ErrorBlock what="the trend" error={error} />
  } else if (loading && rows.length === 0) {
    body = <LoadingBlock h={280} />
  } else if (rows.length === 0) {
    body = <EmptyBlock h={200} msg="No pickups in this window." />
  } else {
    body = (
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" vertical={false} />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="#9CA3AF" minTickGap={12} />
            <YAxis yAxisId="l" tick={{ fontSize: 11 }} stroke="#9CA3AF" allowDecimals={false} />
            <YAxis
              yAxisId="r"
              orientation="right"
              domain={[0, 100]}
              unit="%"
              tick={{ fontSize: 11 }}
              stroke="#9CA3AF"
            />
            <Tooltip
              formatter={(value, name) => {
                const n = String(name)
                if (value === null || value === undefined) return ["—", n]
                return PCT_SERIES.has(n)
                  ? [`${Number(value).toFixed(1)}%`, n]
                  : [Number(value).toLocaleString("en-US"), n]
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar yAxisId="l" dataKey="captured" name="Info captured" stackId="a" fill="#047857" />
            <Bar
              yAxisId="l"
              dataKey="trackedNoInfo"
              name="Tracked, no info"
              stackId="a"
              fill="#93C5FD"
            />
            <Bar yAxisId="l" dataKey="notTracked" name="Not in Augie" stackId="a" fill="#FCA5A5" />
            <Line
              yAxisId="r"
              type="monotone"
              dataKey="trackedPct"
              name="Tracked %"
              stroke="#1D4ED8"
              strokeWidth={2}
              dot={false}
              connectNulls={false}
            />
            <Line
              yAxisId="r"
              type="monotone"
              dataKey="capturedPct"
              name="Captured %"
              stroke="#065F46"
              strokeWidth={2}
              strokeDasharray="4 3"
              dot={false}
              connectNulls={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    )
  }

  return (
    <Panel
      title="Trend"
      subtitle="Pickups per bucket split by funnel stage; Tracked % is of pickups, Captured % of tracked."
      right={<Toggle options={GRAINS} value={grain} onChange={onGrainChange} />}
    >
      {body}
    </Panel>
  )
}
