"use client"

import { useMemo, useState } from "react"
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  COLORS,
  STATUS_META,
  fmtInt,
  fmtMonths,
  fmtUsdCompact,
  useCustomers,
  useLifespan,
  type CustomerRow,
  type Division,
  type LifespanData,
  type ReportFilters,
  type Status,
  type Window,
} from "@/lib/customer-lifespan-api"
import { ListDrawer, type ListSection } from "./ListDrawer"
import { AssignedCell, Card, ErrorBox, Loading } from "./ui"

const STATUS_ORDER: Status[] = ["active", "at_risk", "lost"]
const MIN_CURVE_MONTHS = 3

function Distribution({ buckets, onPick }: { buckets: LifespanData["buckets"]; onPick: (bucket: string) => void }) {
  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={buckets}
          margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
          className="cursor-pointer outline-none [&_*]:outline-none"
          onClick={(state) => {
            // null = a click on the legend or margin; Number(null) would open the first bucket.
            if (state?.activeTooltipIndex == null) return
            const row = buckets[Number(state.activeTooltipIndex)]
            if (row) onPick(row.bucket)
          }}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} width={36} allowDecimals={false} />
          <Tooltip
            formatter={(v, name) => [fmtInt(Number(v)), String(name)]}
            labelFormatter={(l, payload) => {
              const rev = payload?.[0]?.payload?.revenue
              return `${l} · revenue ${fmtUsdCompact(typeof rev === "number" ? rev : null)}`
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="active" name={STATUS_META.active.label} stackId="s" fill={STATUS_META.active.color} />
          <Bar dataKey="at_risk" name={STATUS_META.at_risk.label} stackId="s" fill={STATUS_META.at_risk.color} />
          <Bar dataKey="lost" name={STATUS_META.lost.label} stackId="s" fill={STATUS_META.lost.color} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

/** Round months: 12m, 24m, 36m… (a range under two years steps by 3). */
function survivalTicks(horizon: number): number[] {
  const step = horizon >= 24 ? 12 : 3
  return Array.from({ length: Math.floor(horizon / step) }, (_, i) => (i + 1) * step)
}

function Survival({ survival }: { survival: LifespanData["survival"] }) {
  const pick = (m: number) => survival.points.find((p) => p.month === m)?.survival
  const marks = [6, 12, 24, 60].map((m) => ({ m, s: pick(m) }))
  const horizon = survival.points.length
  if (horizon < MIN_CURVE_MONTHS) {
    return <p className="py-10 text-center text-xs text-[#6B7280]">These dates are too short for a retention curve. Choose a wider range.</p>
  }
  return (
    <>
      <div className="mb-2 flex flex-wrap gap-2 text-[11px]">
        <span className="rounded-full bg-[#EEF2FF] px-2 py-0.5 text-[#1B3A5C]">
          median customer lifetime: {survival.median_months ? fmtMonths(survival.median_months) : "over the whole history"}
        </span>
        {marks.map(({ m, s }) =>
          s === undefined ? null : (
            <span key={m} className="rounded-full bg-[#F3F4F6] px-2 py-0.5 text-[#374151]">
              still shipping after {fmtMonths(m)}: {s.toFixed(0)}%
            </span>
          ),
        )}
      </div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={survival.points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
            <XAxis
              dataKey="month"
              type="number"
              domain={[1, Math.max(horizon, 1)]}
              ticks={survivalTicks(horizon)}
              interval={0}
              tick={{ fontSize: 11 }}
              tickFormatter={(m: number) => `${m}m`}
            />
            <YAxis domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} tick={{ fontSize: 11 }} width={40} />
            <ReferenceLine y={50} stroke="#9CA3AF" strokeDasharray="4 3" />
            <Tooltip
              formatter={(v) => [`${Number(v).toFixed(1)}%`, "Still shipping"]}
              labelFormatter={(m) => `After ${fmtMonths(Number(m))}`}
            />
            <Area type="stepAfter" dataKey="survival" stroke={COLORS.navy} fill={COLORS.navy} fillOpacity={0.12} strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </>
  )
}

function bucketSections(rows: CustomerRow[], bucket: string): ListSection[] {
  const inside = rows.filter((r) => r.lifespan_bucket === bucket)
  return STATUS_ORDER.map((status) => ({
    key: status,
    label: STATUS_META[status].label,
    color: STATUS_META[status].color,
    rows: inside
      .filter((r) => r.status === status)
      .sort((a, b) => b.revenue - a.revenue)
      .map((r) => ({
        id: r.customer_id,
        name: r.name,
        detail: `${fmtInt(r.days_since_last)} ${r.days_since_last === 1 ? "day" : "days"} since last load · ${fmtUsdCompact(r.revenue)} revenue`,
        right: <AssignedCell row={r} />,
      })),
  }))
}

function BucketDrawer({ division, window, filters, bucket, onClose, onOpen }: {
  division: Division
  window: Window
  filters: ReportFilters
  bucket: string
  onClose: () => void
  onOpen: (id: string) => void
}) {
  const { data, error, isLoading } = useCustomers(division, window, filters)
  const sections = useMemo(() => bucketSections(data?.data ?? [], bucket), [data, bucket])
  return (
    <ListDrawer
      title={bucket}
      subtitle="Customers with this lifespan, by current status"
      sections={sections}
      loading={isLoading || !data}
      error={error}
      onClose={onClose}
      onOpen={onOpen}
    />
  )
}

export function LifespanPanel({ division, window, filters, onOpen }: {
  division: Division
  window: Window
  filters: ReportFilters
  onOpen: (id: string) => void
}) {
  const [picked, setPicked] = useState<string | null>(null)
  const { data, error, isLoading } = useLifespan(division, window, filters)
  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) return <Loading />
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card
        title="Customer lifespan"
        description="Shows how long customers have shipped with us, grouped by lifespan and current status."
        howToLabel="How to read this report"
        howTo={<>Each bar shows the number of customers in a lifespan range, measured from their first to last month with a load. Colors show their <b>current status</b>: active (green), at risk (orange), or lost (red). Click a bar to see its customers.</>}
      >
        <Distribution buckets={data.data.buckets} onPick={setPicked} />
      </Card>
      <Card
        title="Customer retention over time"
        description={`Estimated share of customers still shipping over time. Customers with no loads for more than ${window} days are considered lost.`}
        howTo="Read left to right to see the estimated percentage of customers still shipping at each month after their first load. A steeper drop means customers are leaving sooner; the 50% line marks the median customer lifetime."
      >
        <Survival survival={data.data.survival} />
      </Card>
      {picked && (
        <BucketDrawer
          division={division}
          window={window}
          filters={filters}
          bucket={picked}
          onClose={() => setPicked(null)}
          onOpen={onOpen}
        />
      )}
    </div>
  )
}
