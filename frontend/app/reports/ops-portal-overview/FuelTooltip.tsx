"use client"

// Tooltip + region chips for the KPI chart's "Fuel" measure (FuelSeries.tsx).

import type { OppFuelRegion } from "@/lib/ops-portal-overview-api"
import {
  CHANGE_SUFFIX,
  FORECAST_SUFFIX,
  NATIONAL_CODE,
  changeColor,
  fmtFuelDate,
  fmtGallon,
  fmtSignedGallon,
  fuelKey,
  regionColor,
  type FuelRow,
} from "./fuelChartData"

function heading(row: FuelRow, isMonth: boolean): string {
  const period = typeof row.fuel_period === "string" ? row.fuel_period : null
  if (row.fuel_forecast) return `${row.label} · forecast`
  if (!isMonth && period) return `Week of ${fmtFuelDate(period)}`
  return isMonth ? `${row.label} · monthly avg.` : String(row.label)
}

function priceOf(row: FuelRow, code: string): number | null {
  const actual = row[fuelKey(code)]
  if (typeof actual === "number") return actual
  const fc = row[fuelKey(code) + FORECAST_SUFFIX]
  return row.fuel_forecast && typeof fc === "number" ? fc : null
}

export function FuelTooltip({
  row,
  regions,
  hidden,
  isMonth,
  barLabel,
  barValue,
}: {
  row: FuelRow
  regions: OppFuelRegion[]
  hidden: ReadonlySet<string>
  isMonth: boolean
  barLabel: string | null
  barValue: string
}) {
  const changeLabel = isMonth ? "MoM" : "WoW"
  const items = regions
    .filter((r) => !hidden.has(r.code))
    .map((r) => ({ r, price: priceOf(row, r.code), chg: row[fuelKey(r.code) + CHANGE_SUFFIX] }))
    .filter((i) => i.price != null)
  return (
    <div className="rounded-md border border-[#E5E7EB] bg-white px-3 py-2 text-xs shadow-md">
      <div className="mb-1 font-semibold text-[#111827]">{heading(row, isMonth)}</div>
      {barLabel && (
        <div className="mb-1 flex items-center justify-between gap-4 border-b border-[#F3F4F6] pb-1">
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full bg-[#0EA5E9]" />
            {barLabel}
          </span>
          <span className="font-medium tabular-nums text-[#111827]">{barValue}</span>
        </div>
      )}
      {!items.length && <div className="text-[#9CA3AF]">No EIA price for this period</div>}
      {items.map(({ r, price, chg }) => (
        <div key={r.code} className="flex items-center justify-between gap-4">
          <span className={`flex items-center gap-1.5 ${r.code === NATIONAL_CODE ? "font-semibold" : ""}`}>
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: regionColor(r.code) }} />
            {r.name}
          </span>
          <span className="tabular-nums">
            <span className="font-medium text-[#111827]">{fmtGallon(price as number)}</span>
            {typeof chg === "number" && !row.fuel_forecast && (
              <span className="ml-2" style={{ color: changeColor(chg) }}>
                {fmtSignedGallon(chg)} {changeLabel}
              </span>
            )}
          </span>
        </div>
      ))}
    </div>
  )
}

export function RegionChips({
  regions,
  hidden,
  onToggle,
  onAll,
  onNone,
}: {
  regions: OppFuelRegion[]
  hidden: ReadonlySet<string>
  onToggle: (code: string) => void
  onAll: () => void
  onNone: () => void
}) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[11px]">
      {regions.map((r) => {
        const off = hidden.has(r.code)
        return (
          <button
            key={r.code}
            type="button"
            onClick={() => onToggle(r.code)}
            aria-pressed={!off}
            className={`flex items-center gap-1 rounded-full border px-2 py-0.5 ${
              off
                ? "border-[#E5E7EB] bg-[#F3F4F6] text-[#9CA3AF] line-through"
                : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F9FAFB]"
            } ${r.code === NATIONAL_CODE ? "font-semibold" : ""}`}
          >
            <span
              className="inline-block h-2 w-2 rounded-full"
              style={{ background: regionColor(r.code), opacity: off ? 0.4 : 1 }}
            />
            {r.name}
          </button>
        )
      })}
      <button type="button" onClick={onAll} className="rounded-md px-2 py-0.5 text-[#6B7280] hover:bg-[#F3F4F6]">
        All
      </button>
      <button type="button" onClick={onNone} className="rounded-md px-2 py-0.5 text-[#6B7280] hover:bg-[#F3F4F6]">
        None
      </button>
    </div>
  )
}
