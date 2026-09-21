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
import {
  fmtCount,
  fmtDate,
  fmtPct,
  fmtUsd,
  fmtUsdShort,
  useSpotsActuals,
  type SpotsFilters,
  type SpotsGrain,
} from "@/lib/production-spots-trends-api"
import { Card, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Note, Panel } from "./Ui"

/** What actually MOVED — McLeod spot loads that departed.
 *
 *  ⚠ This is the OTHER population and it does not reconcile with the funnel,
 *  by design. The funnel is quoting activity dated by when we priced; this is
 *  freight dated by when it left. A lost bid never becomes a McLeod load, so a
 *  "conversion" measured here would be a flawless, wrong 100%.
 *
 *  Fails soft: if the datalake is unreachable the panel says so rather than
 *  rendering zeros, because a zero here is indistinguishable from a quiet month.
 */
export function ActualsPanel({
  filters,
  grain,
}: {
  filters: SpotsFilters
  grain: SpotsGrain
}) {
  const { data, isLoading, error } = useSpotsActuals(filters, grain)
  const d = data?.data

  const rows = useMemo(
    () =>
      (d?.series ?? []).map((p) => ({
        label: grain === "month" ? p.bucket.slice(0, 7) : fmtDate(p.bucket),
        loads: p.loads,
        revenue: p.revenue,
        profit: p.profit,
        margin: p.margin === null ? null : p.margin * 100,
      })),
    [d, grain]
  )

  if (error) return <ErrorBlock what="the actuals" error={error} />
  if (isLoading && !d) return <LoadingBlock h={320} />

  if (d && !d.available) {
    return (
      <Panel title="Moved (Actuals)" subtitle="McLeod spot loads that departed">
        <Note>
          The McLeod datalake is unavailable right now, so this tab is blank. The
          funnel tabs are unaffected — they read a different database.
        </Note>
      </Panel>
    )
  }

  const t = d?.totals

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Card
          label="Loads moved"
          value={fmtCount(t?.loads)}
          sub="delivered or in transit"
          title="Distinct McLeod order ids with contract_type_descr = SPOT, status D or P, a real departure date and non-zero revenue."
        />
        <Card label="Revenue" value={fmtUsd(t?.revenue)} />
        <Card label="Profit" value={fmtUsd(t?.profit)} />
        <Card
          label="Margin"
          value={fmtPct(t?.margin)}
          title="Total profit ÷ total revenue over the whole window — never the average of the per-period margins."
        />
      </div>

      <Panel
        title="Moved (Actuals)"
        subtitle={`by ${grain} · dated by actual departure, not by quote date`}
      >
        {rows.length === 0 ? (
          <EmptyBlock h={300} msg="No spot loads departed in this window." />
        ) : (
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={rows} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} interval="preserveStartEnd" />
              <YAxis
                yAxisId="left"
                tick={{ fontSize: 10 }}
                tickFormatter={(v) => fmtUsdShort(Number(v))}
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fontSize: 10 }}
                tickFormatter={(v) => `${v}%`}
              />
              <Tooltip
                formatter={(value, name) => {
                  if (value === null || value === undefined) return ["—", name]
                  if (name === "Margin") return [`${Number(value).toFixed(1)}%`, name]
                  if (name === "Loads")
                    return [Number(value).toLocaleString("en-US"), name]
                  return [fmtUsd(Number(value)), name]
                }}
              />
              <Legend wrapperStyle={{ fontSize: 10 }} />
              <Bar
                yAxisId="left"
                dataKey="revenue"
                name="Revenue"
                fill="#93C5FD"
                radius={[3, 3, 0, 0]}
              />
              <Bar
                yAxisId="left"
                dataKey="profit"
                name="Profit"
                fill="#1B3A5C"
                radius={[3, 3, 0, 0]}
              />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="margin"
                name="Margin"
                stroke="#047857"
                strokeWidth={2}
                dot={{ r: 2 }}
                connectNulls
              />
            </ComposedChart>
          </ResponsiveContainer>
        )}

        <Footnote>
          Source: <code>mcleod_gld_budget_report_v4</code> where{" "}
          <code>contract_type_descr = &apos;SPOT&apos;</code>, bucketed on actual
          departure, with the standard hygiene filter (non-zero revenue, status D or P,
          a real departure date). ⚠ <strong>This does not reconcile with the funnel
          and is not meant to.</strong> The funnel counts quotes on the day we priced
          them; this counts freight on the day it left, months can differ, and a lost
          bid never appears here at all — so conversion cannot be measured from this
          panel.
        </Footnote>
      </Panel>
    </div>
  )
}
