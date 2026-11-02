/**
 * Formatting + types for the public booker-rank TV page.
 *
 * PURE — no React, no `"use client"`. The report's own formatters live in
 * `lib/booker-scorecard-api.ts`, which is a `"use client"` module: a server
 * component that CALLS a value out of one gets a client-reference proxy
 * ("X is not a function"), so the TV page uses these instead.
 */

export interface PublicRankWindow {
  start: string
  end: string
  label: string
}

export interface PublicRankRow {
  booker: string
  rank: number | null
  prev_rank: number | null
  rank_delta: number | null
  bookings: number
  prev_bookings: number
  compliance_threshold_pct: number | null
  compliant_threshold: number | null
  threshold_orders: number | null
  cost_saving: number | null
}

export interface PublicRankTable {
  total_bookers: number
  min_bookings: number
  week: PublicRankWindow
  prev_week: PublicRankWindow
  like_for_like: boolean
  rows: PublicRankRow[]
}

export interface PublicBookerRank {
  current: PublicRankTable
  last_week: PublicRankTable
}

const USD = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const COUNT = new Intl.NumberFormat("en-US")

export function fmtUsd(v: number | null): string {
  return v === null ? "—" : USD.format(v)
}

export function fmtCount(v: number | null): string {
  return v === null ? "—" : COUNT.format(v)
}

/** ⚠ The backend sends a FRACTION (0.85), exactly as the report's own
 *  `fmtPct` expects — never a 0–100 number. */
export function fmtPct(v: number | null): string {
  return v === null || Number.isNaN(v) ? "—" : `${(v * 100).toFixed(1)}%`
}

/** "Updated 9:05 AM" in Chicago — a TV's own clock/timezone is never trusted. */
export function fmtUpdatedAt(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    timeZone: "America/Chicago",
    hour: "numeric",
    minute: "2-digit",
  })
}
