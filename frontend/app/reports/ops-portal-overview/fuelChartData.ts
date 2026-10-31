// Pure shaping for the KPI chart's "Fuel" measure (2026-10-31).
//
// Ported from the quoting portal's src/lib/fuel/chart-data.ts (buildFuelChartData,
// FUEL_REGION_COLORS) — the backend already buckets the EIA series onto the
// chart's own day / week / month buckets, so this only MERGES them into the
// business rows by `bucket_start` (the brush indices therefore stay those of
// /combo) and appends month-grain forecast buckets AFTER the last one.
//
// dataKeys: `fuel_<code>` actual, `fuel_<code>__f` forecast (dashed, bridged
// back to the last actual bucket so the two segments connect), and
// `fuel_<code>__chg` the WoW / MoM change used by the tooltip.

import { parseLocalDate } from "@/lib/local-date"
import { fmtBucket, type OppFuel, type OppGrain } from "@/lib/ops-portal-overview-api"

export const FUEL_KEY_PREFIX = "fuel_"
export const FORECAST_SUFFIX = "__f"
export const CHANGE_SUFFIX = "__chg"
export const NATIONAL_CODE = "NUS"

/** Stable per-region colors — the same as the quoting portal's page. */
export const FUEL_REGION_COLORS: Record<string, string> = {
  NUS: "#0284c7",
  R1X: "#dc2626",
  R1Y: "#ea580c",
  R1Z: "#ca8a04",
  R20: "#16a34a",
  R30: "#0891b2",
  R40: "#7c3aed",
  R50: "#db2777",
  SCA: "#4f46e5",
}
const FALLBACK_COLOR = "#64748b"

export function regionColor(code: string): string {
  return FUEL_REGION_COLORS[code] ?? FALLBACK_COLOR
}

export const fuelKey = (code: string) => `${FUEL_KEY_PREFIX}${code}`

export type FuelRow = Record<string, unknown> & { bucket_start: string; label: string }

function fuelFields(values: Record<string, number>, suffix = ""): Record<string, number> {
  return Object.fromEntries(Object.entries(values).map(([c, v]) => [fuelKey(c) + suffix, v]))
}

/** Null every numeric business field so a future bucket draws no bar. */
function blankOf(template: FuelRow): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(template).map(([k, v]) => [k, typeof v === "number" ? null : v]),
  )
}

function lastActualIndex(rows: FuelRow[], codes: string[]): number {
  for (let i = rows.length - 1; i >= 0; i--) {
    if (codes.some((c) => typeof rows[i][fuelKey(c)] === "number")) return i
  }
  return -1
}

/** Bridge: each region's forecast line starts at its last actual value. */
function withBridge(rows: FuelRow[], codes: string[]): FuelRow[] {
  const idx = lastActualIndex(rows, codes)
  if (idx < 0) return rows
  const bridge = Object.fromEntries(
    codes
      .filter((c) => typeof rows[idx][fuelKey(c)] === "number")
      .map((c) => [fuelKey(c) + FORECAST_SUFFIX, rows[idx][fuelKey(c)]]),
  )
  return rows.map((r, i) => (i === idx ? { ...r, ...bridge } : r))
}

/**
 * Business rows + fuel, merged by bucket key. Returns NEW objects; the input
 * rows are never mutated. Forecast buckets (month grain) are appended only
 * past the last business bucket, never inserted, so every existing index holds.
 */
export function mergeFuelRows(base: FuelRow[], fuel: OppFuel | undefined, grain: OppGrain): FuelRow[] {
  if (!fuel || !base.length) return base
  const byBucket = new Map(fuel.points.map((p) => [p.bucket_start, p]))
  const merged: FuelRow[] = base.map((row) => {
    const p = byBucket.get(row.bucket_start)
    if (!p) return row
    return { ...row, fuel_period: p.period, ...fuelFields(p.values), ...fuelFields(p.wow, CHANGE_SUFFIX) }
  })
  const lastBase = base[base.length - 1].bucket_start
  const future = (grain === "month" ? fuel.forecast : []).filter((f) => f.bucket_start > lastBase)
  if (!future.length) return merged
  const codes = fuel.regions.map((r) => r.code)
  const blank = blankOf(base[base.length - 1])
  const appended: FuelRow[] = future.map((f) => ({
    ...blank,
    projection: null,
    bucket_start: f.bucket_start,
    label: fmtBucket(f.bucket_start, grain),
    fuel_forecast: true,
    ...fuelFields(f.values, FORECAST_SUFFIX),
  }))
  return [...withBridge(merged, codes), ...appended]
}

/**
 * The Chart's brush is in /combo indices. A window that reaches the last
 * business bucket is extended over the appended forecast buckets, so the
 * default "most recent N" view shows where prices are heading.
 */
export function fuelBrush(
  brush: { start: number; end: number },
  baseLen: number,
  rowsLen: number,
): { start: number; end: number } {
  const maxIdx = Math.max(0, rowsLen - 1)
  const end = brush.end >= baseLen - 1 ? maxIdx : Math.min(brush.end, maxIdx)
  return { start: Math.min(brush.start, end), end }
}

/** "Oct 19, 2026" from a date-only ISO string — parsed by parts (§116). */
export function fmtFuelDate(iso: string): string {
  return parseLocalDate(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

export function fmtGallon(v: number): string {
  return `$${v.toFixed(3)}`
}

export function fmtSignedGallon(v: number): string {
  return `${v > 0 ? "+" : ""}${v.toFixed(3)}`
}

/** Fuel convention: up = costlier = red, down = cheaper = green. */
export function changeColor(v: number): string {
  if (v > 0) return "#DC2626"
  if (v < 0) return "#16A34A"
  return "#6B7280"
}
