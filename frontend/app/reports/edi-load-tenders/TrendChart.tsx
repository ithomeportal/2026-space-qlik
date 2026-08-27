"use client"

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
import type { EdiChartPoint, EdiGrain } from "@/lib/edi-load-tenders-api"

const GRAINS: { k: EdiGrain; label: string }[] = [
  { k: "day", label: "Day" },
  { k: "week", label: "Week" },
  { k: "month", label: "Month" },
]

interface Props {
  data: EdiChartPoint[]
  grain: EdiGrain
  onGrainChange: (g: EdiGrain) => void
  loading: boolean
}

export function TrendChart({ data, grain, onGrainChange, loading }: Props) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <header className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-900">Tender volume</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Bucketed on each shipment&apos;s first tender, so an amendment never
            counts as new demand.
          </p>
        </div>
        <div className="flex gap-1 rounded-md border border-slate-200 p-0.5">
          {GRAINS.map((g) => (
            <button
              key={g.k}
              onClick={() => onGrainChange(g.k)}
              className={`rounded px-2 py-1 text-xs ${
                grain === g.k
                  ? "bg-slate-900 text-white"
                  : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              {g.label}
            </button>
          ))}
        </div>
      </header>
      <div className="h-72 p-3">
        {loading && data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-400">
            Loading…
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="bucket" tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <YAxis yAxisId="l" tick={{ fontSize: 11 }} stroke="#94a3b8" />
              <YAxis
                yAxisId="r"
                orientation="right"
                domain={[0, 100]}
                unit="%"
                tick={{ fontSize: 11 }}
                stroke="#94a3b8"
              />
              <Tooltip
                formatter={(value, name) =>
                  name === "Create rate"
                    ? [`${Number(value).toFixed(1)}%`, name]
                    : [Number(value).toLocaleString("en-US"), name]
                }
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar
                yAxisId="l"
                dataKey="created"
                name="Order created"
                stackId="a"
                fill="#0f766e"
              />
              <Bar
                yAxisId="l"
                dataKey="cust_cancelled"
                name="Cancelled by customer"
                stackId="a"
                fill="#dc2626"
              />
              <Line
                yAxisId="r"
                type="monotone"
                dataKey="create_rate"
                name="Create rate"
                stroke="#1d4ed8"
                strokeWidth={2}
                dot={false}
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </section>
  )
}
