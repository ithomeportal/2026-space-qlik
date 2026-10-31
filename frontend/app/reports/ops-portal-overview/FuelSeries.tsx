"use client"

// "Fuel" measure of the KPI MANAGEMENT chart (2026-10-31).
//
// The business bars stay on the LEFT axis — in the measure that was selected
// before Fuel was clicked (default Prof.), labels unchanged — and EIA weekly
// retail diesel ($/gal) for the 9 regions rides on a RIGHT axis, U.S. National
// thicker. Month grain adds dashed forecast lines for the coming months.
//
// Mirrors the quoting portal's US National Fuel page (pricing.unilinkportal.com
// /admin/us-national-fuel): same regions, colors, All / None chips and default
// (every region on). Fuel is market data — the caption says it is NOT filtered
// by team / customer / lane, and the request does not send those filters.
//
// Data is merged into the /combo rows by bucket key (fuelChartData.ts), so the
// Chart's brush — and its `dataEpoch` remount (§97) — keep working unchanged.

import { useEffect, useMemo, useState } from "react"
import { Bar, Brush, CartesianGrid, ComposedChart, LabelList, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts"
import { useOppFuel, type OppGrain } from "@/lib/ops-portal-overview-api"
import { FuelTooltip, RegionChips } from "./FuelTooltip"
import {
  FORECAST_SUFFIX,
  NATIONAL_CODE,
  fmtFuelDate,
  fuelBrush,
  fuelKey,
  mergeFuelRows,
  regionColor,
  type FuelRow,
} from "./fuelChartData"

interface Props {
  rows: FuelRow[]
  grain: OppGrain
  /** The business measure drawn as bars (never "fuel"). */
  barKey: string
  barLabel: string
  showBars: boolean
  fmt: (v: number) => string
  labelFmt: (v: number) => string
  brush: { start: number; end: number }
  onBrush: (start: number, end: number) => void
  dataEpoch: number
}

function useRegionToggles(codes: string[]) {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set())
  const toggle = (code: string) =>
    setHidden((prev) => {
      const next = new Set(prev)
      if (next.has(code)) next.delete(code)
      else next.add(code)
      return next
    })
  return {
    hidden,
    toggle,
    all: () => setHidden(new Set()),
    none: () => setHidden(new Set(codes)),
  }
}

export function FuelSeries(props: Props) {
  const { rows, grain, barKey, barLabel, showBars, fmt, labelFmt, brush, onBrush, dataEpoch } = props
  const { data: res, isLoading, error } = useOppFuel(grain, true)
  const fuel = res?.data
  const regions = useMemo(() => fuel?.regions ?? [], [fuel])
  const toggles = useRegionToggles(regions.map((r) => r.code))
  const data = useMemo(() => mergeFuelRows(rows, fuel, grain), [rows, fuel, grain])
  const win = fuelBrush(brush, rows.length, data.length)
  // Same reason as Chart.tsx's `dataEpoch`: Recharts keeps the brush window in
  // its store and a data swap resets it, so remount <Brush> one commit later.
  const [epoch, setEpoch] = useState(0)
  useEffect(() => setEpoch((e) => e + 1), [data])
  const isMonth = grain === "month"
  const visible = regions.filter((r) => !toggles.hidden.has(r.code))

  return (
    <div>
      <RegionChips regions={regions} hidden={toggles.hidden} onToggle={toggles.toggle} onAll={toggles.all} onNone={toggles.none} />
      <ResponsiveContainer width="100%" height={380}>
        <ComposedChart data={data} margin={{ top: 16, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#F3F4F6" />
          <XAxis dataKey="label" tick={{ fontSize: 10 }} />
          <YAxis yAxisId="left" tick={{ fontSize: 10 }} tickFormatter={(v) => fmt(Number(v))} />
          <YAxis
            yAxisId="fuel"
            orientation="right"
            domain={["auto", "auto"]}
            tick={{ fontSize: 10 }}
            tickFormatter={(v) => `$${Number(v).toFixed(2)}`}
          />
          <Tooltip
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null
              const row = payload[0].payload as FuelRow
              const v = row[barKey]
              return (
                <FuelTooltip
                  row={row}
                  regions={regions}
                  hidden={toggles.hidden}
                  isMonth={isMonth}
                  barLabel={showBars && typeof v === "number" ? barLabel : null}
                  barValue={typeof v === "number" ? fmt(v) : ""}
                />
              )
            }}
          />
          {showBars && (
            <Bar yAxisId="left" dataKey={barKey} name={barLabel} fill="#7DD3FC">
              <LabelList dataKey={barKey} position="top" fontSize={9} fill="#475569" formatter={(v) => labelFmt(Number(v))} />
            </Bar>
          )}
          {visible.map((r) => (
            <Line
              key={r.code}
              yAxisId="fuel"
              type="monotone"
              dataKey={fuelKey(r.code)}
              name={r.name}
              stroke={regionColor(r.code)}
              strokeWidth={r.code === NATIONAL_CODE ? 2.5 : 1.5}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
          {isMonth &&
            visible.map((r) => (
              <Line
                key={`${r.code}${FORECAST_SUFFIX}`}
                yAxisId="fuel"
                type="monotone"
                dataKey={fuelKey(r.code) + FORECAST_SUFFIX}
                name={`${r.name} (forecast)`}
                stroke={regionColor(r.code)}
                strokeWidth={r.code === NATIONAL_CODE ? 2.5 : 1.5}
                strokeDasharray="5 4"
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            ))}
          <Brush
            /* ⚠ Load-bearing — see Chart.tsx's `dataEpoch` note. */
            key={`${grain}-${dataEpoch}-${epoch}`}
            dataKey="label"
            height={20}
            stroke="#94A3B8"
            travellerWidth={8}
            startIndex={win.start}
            endIndex={win.end}
            onChange={(r) => {
              if (r && typeof r.startIndex === "number" && typeof r.endIndex === "number") {
                onBrush(r.startIndex, r.endIndex)
              }
            }}
          />
        </ComposedChart>
      </ResponsiveContainer>
      <FuelCaption
        loading={isLoading}
        failed={Boolean(error)}
        unavailable={fuel?.unavailable ?? null}
        latest={fuel?.freshness.latest_period ?? null}
      />
    </div>
  )
}

function FuelCaption({
  loading,
  failed,
  unavailable,
  latest,
}: {
  loading: boolean
  failed: boolean
  unavailable: string | null
  latest: string | null
}) {
  const status = loading
    ? "Loading fuel prices…"
    : failed
      ? "Fuel prices failed to load."
      : unavailable ?? (latest ? `Latest week ${fmtFuelDate(latest)}` : "No EIA weeks in this window.")
  return (
    <p className="mt-1 text-[11px] text-[#6B7280]">
      EIA weekly retail diesel ($/gal) — market data, not filtered by team/customer/lane. {status}
    </p>
  )
}
