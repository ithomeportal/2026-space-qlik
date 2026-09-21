"use client"

import { useMemo } from "react"
import {
  Bar,
  Brush,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  fmtDate,
  useSpotsTrend,
  type SpotsFilters,
  type SpotsGrain,
} from "@/lib/production-spots-trends-api"
import { EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Panel } from "./Ui"

/** Outcome mix (stacked bars) with quote rate and win rate over it.
 *
 *  Two things make this chart honest rather than merely pretty:
 *
 *  1. The series is DENSE — the backend zero-fills every bucket, so a dead day
 *     renders as a gap in the bars rather than being closed over silently.
 *  2. The unsettled tail is SHADED. Outcomes take 10 days (Home Depot) to 30
 *     (lane feed) to resolve, so the newest buckets structurally under-report
 *     wins. Without the shading the win-rate line dives at the right edge every
 *     time anyone opens the page, and it is believed once.
 */

const SERIES = [
  { key: "won", name: "Won", colour: "#047857" },
  { key: "lost", name: "Lost", colour: "#B91C1C" },
  { key: "rejected", name: "Rejected", colour: "#DC2626" },
  { key: "no_reply", name: "No reply", colour: "#D97706" },
  { key: "in_play", name: "In play", colour: "#2563EB" },
  { key: "cancelled", name: "Cancelled", colour: "#9CA3AF" },
  { key: "skipped", name: "Skipped", colour: "#D1D5DB" },
] as const

/** How much of the series the brush shows by default. The data stays WHOLE and
 *  the viewport moves (§70) — slicing the array here would delete the history
 *  the scrollbar exists to reach. */
const DEFAULT_WINDOW: Record<SpotsGrain, number> = { day: 45, week: 16, month: 12 }

function label(bucket: string, grain: SpotsGrain) {
  if (grain === "month") return bucket.slice(0, 7)
  return fmtDate(bucket)
}

export function TrendChart({
  filters,
  grain,
}: {
  filters: SpotsFilters
  grain: SpotsGrain
}) {
  const { data, isLoading, error } = useSpotsTrend(filters, grain)

  const rows = useMemo(() => {
    return (data?.data ?? []).map((p) => ({
      label: label(p.bucket, grain),
      bucket: p.bucket,
      provisional: p.provisional,
      won: p.won,
      lost: p.lost,
      rejected: p.rejected,
      no_reply: p.no_reply,
      in_play: p.in_play,
      cancelled: p.cancelled,
      skipped: p.skipped,
      presented: p.presented,
      // Rates travel as fractions; scale to display units BEFORE render so the
      // axis, the tooltip and the line all agree.
      quote_rate: p.quote_rate === null ? null : p.quote_rate * 100,
      win_rate: p.win_rate === null ? null : p.win_rate * 100,
    }))
  }, [data, grain])

  // Auto-scale the % axis. A fixed 0–100 squashes a 5% win rate onto the x-axis
  // and makes every movement in it invisible.
  const pctMax = useMemo(() => {
    const max = Math.max(
      0,
      ...rows.map((r) => Math.max(Number(r.quote_rate) || 0, Number(r.win_rate) || 0))
    )
    return Math.min(100, Math.ceil(max / 10) * 10 + 5)
  }, [rows])

  const firstProvisional = rows.find((r) => r.provisional)
  const lastRow = rows[rows.length - 1]

  const startIndex = Math.max(0, rows.length - DEFAULT_WINDOW[grain])

  if (error) return <ErrorBlock what="the trend" error={error} />

  return (
    <Panel
      title="Outcome mix & rates"
      subtitle={`by ${grain} · ${rows.length} buckets · drag the handles to move the window`}
    >
      {isLoading && rows.length === 0 ? (
        <LoadingBlock h={320} />
      ) : rows.length === 0 ? (
        <EmptyBlock h={320} />
      ) : (
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart
            data={rows}
            margin={{ top: 12, right: 8, bottom: 0, left: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
            <YAxis yAxisId="left" tick={{ fontSize: 10 }} allowDecimals={false} />
            <YAxis
              yAxisId="right"
              orientation="right"
              domain={[0, pctMax]}
              tick={{ fontSize: 10 }}
              tickFormatter={(v) => `${v}%`}
            />
            {/* The unsettled tail. Rendered only when both edges exist in the
                data, so it can never be silently discarded for overflowing the
                axis the way a ReferenceLine outside an explicit domain is. */}
            {firstProvisional && lastRow ? (
              <ReferenceArea
                yAxisId="left"
                x1={firstProvisional.label}
                x2={lastRow.label}
                fill="#111827"
                fillOpacity={0.05}
                label={{
                  value: "still settling",
                  position: "insideTop",
                  fontSize: 9,
                  fill: "#6B7280",
                }}
              />
            ) : null}
            <Tooltip
              formatter={(value, name) => {
                if (value === null || value === undefined) return ["—", name]
                if (name === "Quote rate" || name === "Win rate")
                  return [`${Number(value).toFixed(1)}%`, name]
                return [Number(value).toLocaleString("en-US"), name]
              }}
              labelFormatter={(v) => {
                const row = rows.find((r) => r.label === v)
                return row?.provisional ? `${v} — still settling` : String(v)
              }}
            />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            {SERIES.map((s, i) => (
              <Bar
                key={s.key}
                yAxisId="left"
                dataKey={s.key}
                name={s.name}
                stackId="outcome"
                fill={s.colour}
                radius={i === SERIES.length - 1 ? [3, 3, 0, 0] : undefined}
              />
            ))}
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="quote_rate"
              name="Quote rate"
              stroke="#1B3A5C"
              strokeWidth={2}
              dot={false}
              connectNulls
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="win_rate"
              name="Win rate"
              stroke="#047857"
              strokeWidth={2}
              dot={{ r: 2 }}
              connectNulls
            />
            {/* Remounted on grain/length change rather than steered by an
                effect: `startIndex` is advisory, and Recharts keeps the visible
                window in its own store (§97). */}
            <Brush
              key={`${grain}-${rows.length}`}
              dataKey="label"
              height={20}
              travellerWidth={8}
              stroke="#CBD5E1"
              startIndex={startIndex}
              endIndex={Math.max(startIndex, rows.length - 1)}
            />
          </ComposedChart>
        </ResponsiveContainer>
      )}

      <Footnote>
        Bars are the outcome mix of everything <em>presented</em> in the bucket
        (Skipped included, so the stack height is Presented). The shaded tail is
        not yet settled: Home Depot outcomes land 7–10 days after the quote and
        lane-feed quotes age off at 30 days, so wins there are structurally
        under-reported and the win-rate line will rise as they resolve. Use the
        settled-period tables above for any week-on-week judgement about win rate.
        {rows.some((r) => r.presented === 0) ? (
          <>
            {" "}
            Empty buckets are real: Home Depot posts no offers at weekends.
          </>
        ) : null}
      </Footnote>
    </Panel>
  )
}
