"use client"

// Projected as CANDLESTICKS — Bruno PDF 2026-10-16 R1.
//
// Each bucket's candle is the OHLC of the stored projection while that bucket
// was running (ops_projection_history; /combo `projection`): month = the
// month-end projection, week = avg/day × 7, day = avg/day (one snapshot ⇒ a
// flat candle). Margin % is never scaled. Recharts has no candlestick, so this
// is a custom <Bar shape> over a RANGE dataKey `proj_range = [low, high]` —
// a range value is what makes the y-axis domain include the whole wick.

import type { OppBucket, OppCandle, OppCandleMeasure } from "@/lib/ops-portal-overview-api"

export const CANDLE_UP = "#16A34A"
export const CANDLE_DOWN = "#DC2626"

const CANDLE_MEASURES = new Set<string>(["volume", "revenue", "profit", "margin_pct"])

export function isCandleMeasure(m: string): m is OppCandleMeasure {
  return CANDLE_MEASURES.has(m)
}

/** Fields the chart rows gain for the active measure. */
export interface CandleFields {
  proj_range: [number, number] | null
  proj_ohlc: OppCandle | null
  returning_customers: number | null
}

/**
 * Decorate rows with the active measure's candle + the Customers split.
 * Pure: returns new objects, never mutates the input rows.
 */
export function withKpiExtras<T extends Partial<OppBucket>>(rows: T[], measure: string): (T & CandleFields)[] {
  return rows.map((r) => {
    const c = isCandleMeasure(measure) ? r.projection?.[measure] ?? null : null
    const total = typeof r.customers === "number" ? r.customers : null
    const fresh = typeof r.new_customers === "number" ? r.new_customers : 0
    return {
      ...r,
      proj_range: c ? [c.low, c.high] : null,
      proj_ohlc: c,
      returning_customers: total === null ? null : Math.max(0, total - fresh),
    }
  })
}

interface ShapeProps {
  x?: number
  y?: number
  width?: number
  height?: number
  payload?: { proj_ohlc?: OppCandle | null }
}

/** Custom Bar shape: wick high–low + body open–close. */
export function ProjectedCandle({ x = 0, y = 0, width = 0, height = 0, payload }: ShapeProps) {
  const c = payload?.proj_ohlc
  if (!c || !Number.isFinite(c.high) || !Number.isFinite(c.low)) return null
  const top = Math.min(y, y + height)
  const h = Math.abs(height)
  const span = c.high - c.low
  const px = (v: number) => (span > 0 ? top + ((c.high - v) / span) * h : top)
  const color = c.close >= c.open ? CANDLE_UP : CANDLE_DOWN
  const cx = x + width / 2
  const bodyW = Math.max(2, Math.min(width * 0.6, 18))
  const bodyTop = Math.min(px(c.open), px(c.close))
  const bodyH = Math.max(1.5, Math.abs(px(c.open) - px(c.close)))
  return (
    <g>
      <line x1={cx} x2={cx} y1={px(c.high)} y2={px(c.low)} stroke={color} strokeWidth={1} />
      <rect x={cx - bodyW / 2} y={bodyTop} width={bodyW} height={bodyH} fill={color} stroke={color} />
    </g>
  )
}

/** Recharts calls `shape` with untyped props — narrow them here, once. */
export function renderCandle(props: unknown) {
  return <ProjectedCandle {...(props as ShapeProps)} />
}
