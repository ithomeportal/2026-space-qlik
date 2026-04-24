"use client"

import { Loader2 } from "lucide-react"
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { fmtDay, fmtMonth, fmtUsd, useCeoTrends } from "@/lib/ceo-api"
import { CeoErrorBanner } from "../ErrorBanner"

export function Trends() {
  const { data, isLoading, error } = useCeoTrends()
  const d = data?.data

  const monthly = (d?.monthly ?? []).map((r) => ({
    ...r,
    label: fmtMonth(r.bucket),
  }))
  const daily = (d?.daily ?? []).map((r) => ({
    ...r,
    label: fmtDay(r.bucket),
  }))

  return (
    <div className="space-y-6">
      <CeoErrorBanner label="Trends" errors={[error]} />

      <div className="rounded-md border border-[#E5E7EB] bg-white p-3 text-xs text-[#6B7280]">
        All Trends panels are <strong>date-immutable</strong> — they ignore the Range / Team /
        Customer filters and always show the fixed windows below.
      </div>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Panel title="Customer Count & Margin % — Last 15 Months" loading={isLoading}>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={monthly}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
              <YAxis
                yAxisId="right"
                orientation="right"
                tickFormatter={(v) => `${v.toFixed(0)}%`}
                tick={{ fontSize: 11 }}
                domain={[0, 50]}
              />
              <Tooltip formatter={(v, name) =>
                name === "% Margin" ? `${Number(v).toFixed(2)}%` : String(v)
              } />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar yAxisId="left" dataKey="customers" fill="#10B981" name="# Customer" barSize={28} />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="margin_pct"
                stroke="#2563EB"
                name="% Margin"
                dot={{ r: 3 }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Profit / Loads by Month — Last 15 Months" loading={isLoading}>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={monthly}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} />
              <YAxis yAxisId="left" tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v, name) =>
                name === "Profit" ? fmtUsd(Number(v)) : String(v)
              } />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar yAxisId="left" dataKey="profit" fill="#D97706" name="Profit" barSize={28} />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="loads"
                stroke="#DC2626"
                name="Loads"
                dot={{ r: 3 }}
              />
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>
      </section>

      <section className="grid grid-cols-1 gap-4">
        <Panel title="Profit / Loads by Day — Last 80 Days" loading={isLoading}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={daily}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={Math.max(0, Math.floor(daily.length / 20))} />
              <YAxis yAxisId="left" tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} tick={{ fontSize: 11 }} />
              <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11 }} />
              <Tooltip formatter={(v, name) =>
                name === "Profit" ? fmtUsd(Number(v)) : String(v)
              } />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line yAxisId="left" type="monotone" dataKey="profit" stroke="#D97706" name="Profit" dot={false} />
              <Line yAxisId="right" type="monotone" dataKey="loads" stroke="#DC2626" name="Loads" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Customer Count & Margin % by Day — Last 80 Days" loading={isLoading}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={daily}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval={Math.max(0, Math.floor(daily.length / 20))} />
              <YAxis yAxisId="left" tick={{ fontSize: 11 }} />
              <YAxis
                yAxisId="right"
                orientation="right"
                tickFormatter={(v) => `${v.toFixed(0)}%`}
                tick={{ fontSize: 11 }}
              />
              <Tooltip formatter={(v, name) =>
                name === "% Margin" ? `${Number(v).toFixed(2)}%` : String(v)
              } />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line yAxisId="left" type="monotone" dataKey="customers" stroke="#10B981" name="# Customer" dot={false} />
              <Line yAxisId="right" type="monotone" dataKey="margin_pct" stroke="#2563EB" name="% Margin" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Panel>
      </section>
    </div>
  )
}

function Panel({
  title,
  loading,
  children,
}: {
  title: string
  loading?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="bg-[#F9FAFB] px-3 py-2 text-sm font-semibold text-[#111827]">{title}</div>
      <div className="p-3">
        {loading ? (
          <div className="flex h-64 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  )
}
