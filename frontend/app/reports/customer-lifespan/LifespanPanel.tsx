"use client"

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
  useLifespan,
  type Division,
  type LifespanData,
  type Window,
} from "@/lib/customer-lifespan-api"
import { Card, ErrorBox, Loading } from "./ui"

function Distribution({ buckets }: { buckets: LifespanData["buckets"] }) {
  return (
    <div className="h-72">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={buckets} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} width={36} allowDecimals={false} />
          <Tooltip
            formatter={(v, name) => [fmtInt(Number(v)), String(name)]}
            labelFormatter={(l, payload) => {
              const rev = payload?.[0]?.payload?.revenue
              return `${l} · lifetime revenue ${fmtUsdCompact(typeof rev === "number" ? rev : null)}`
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

function Survival({ survival }: { survival: LifespanData["survival"] }) {
  const pick = (m: number) => survival.points.find((p) => p.month === m)?.survival
  const marks = [6, 12, 24, 60].map((m) => ({ m, s: pick(m) }))
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
            <XAxis dataKey="month" tick={{ fontSize: 11 }} tickFormatter={(m: number) => (m % 12 === 0 ? `${m / 12}y` : `${m}m`)} interval={11} />
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

export function LifespanPanel({ division, window }: { division: Division; window: Window }) {
  const { data, error, isLoading } = useLifespan(division, window)
  if (error) return <ErrorBox error={error} />
  if (isLoading || !data) return <Loading />
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card
        title="How long customers last"
        hint="Customers by lifespan (months between the first and the last month with a load), split by today's status. Short bars in red are customers who tried us and left."
      >
        <Distribution buckets={data.data.buckets} />
      </Card>
      <Card
        title="Survival curve"
        hint={`Share of customers still shipping N months after their first load (Kaplan–Meier). A customer quiet for more than ${window} days counts as gone; customers still in the base count up to their last load and not as gone, so new customers do not drag the curve down.`}
      >
        <Survival survival={data.data.survival} />
      </Card>
    </div>
  )
}
