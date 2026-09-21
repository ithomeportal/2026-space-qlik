"use client"

import { useQuery, keepPreviousData } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total: number; grain?: string; maturity_days?: number }
}

async function apiFetch<T>(path: string, signal?: AbortSignal): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
    signal,
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const PST_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    // Never retry an auth failure, and never retry a client abort (§43).
    if (/\b401\b|\b403\b/.test(msg) || /abort/i.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Shared filter contract
// ---------------------------------------------------------------------------

export type SpotsRange =
  | "today"
  | "yesterday"
  | "wtd"
  | "last7"
  | "mtd"
  | "last_month"
  | "last30"
  | "last90"
  | "qtd"
  | "ytd"
  | "custom"

export type SpotsGrain = "day" | "week" | "month"
export type SpotsDim = "channel" | "customer" | "actor" | "equipment" | "division"

/** Must stay in lockstep with `_SORTS` in the router — a token on one side of
 *  the wire only renders a table ordered by something other than its header,
 *  and nothing fails. A Python guard asserts the two sets are equal. */
export type SpotsSort =
  | "label_asc"
  | "label_desc"
  | "presented_desc"
  | "presented_asc"
  | "quoted_desc"
  | "quoted_asc"
  | "skipped_desc"
  | "won_desc"
  | "won_asc"
  | "no_reply_desc"
  | "quote_rate_desc"
  | "quote_rate_asc"
  | "win_rate_desc"
  | "win_rate_asc"
  | "awarded_revenue_desc"
  | "awarded_revenue_asc"
  | "awarded_margin_desc"
  | "awarded_margin_asc"

export interface SpotsFilters {
  range: SpotsRange
  startDate?: string
  endDate?: string
  channel?: string[]
  customer?: string[]
  actor?: string[]
  equipment?: string[]
  division?: string[]
}

function qs(f: SpotsFilters, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  // Repeated keys — the proxy forwards them with .append() so a multi-select
  // survives (§45). NEVER comma-join: customer names contain commas, and
  // "CONAGRA FOODS PACKAGED FOODS, LLC" would become two filters matching
  // nothing, returning empty with no error.
  for (const v of f.channel ?? []) q.append("channel", v)
  for (const v of f.customer ?? []) q.append("customer", v)
  for (const v of f.actor ?? []) q.append("actor", v)
  for (const v of f.equipment ?? []) q.append("equipment", v)
  for (const v of f.division ?? []) q.append("division", v)
  for (const [k, v] of Object.entries(extra ?? {})) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

/** The query key must cover EVERY field `qs` serialises, or a filter change
 *  silently serves the previous scope's cached response — invisible in the
 *  network tab, because the second request never fires (§50). */
function key(f: SpotsFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    (f.channel ?? []).slice().sort().join("|"),
    (f.customer ?? []).slice().sort().join("|"),
    (f.actor ?? []).slice().sort().join("|"),
    (f.equipment ?? []).slice().sort().join("|"),
    (f.division ?? []).slice().sort().join("|"),
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Every measure the backend returns for a bucket, already derived. Rates are
 *  FRACTIONS — `fmtPct` multiplies. */
export interface SpotsBucket {
  presented: number
  volume: number
  quoted: number
  skipped: number
  open: number
  accept: number
  won: number
  lost: number
  no_reply: number
  rejected: number
  cancelled: number
  other_outcome: number
  potential_revenue: number
  awarded_revenue: number
  awarded_rev_known: number
  awarded_profit: number
  awarded_profit_n: number
  loads_won: number
  decided: number
  in_play: number
  quote_rate: number | null
  skip_rate: number | null
  win_rate: number | null
  no_reply_rate: number | null
  reject_rate: number | null
  hit_rate: number | null
  in_play_share: number | null
  awarded_margin: number | null
  avg_award_price: number | null
  avg_quote_price: number | null
}

export interface SpotsWindow {
  start: string
  end: string
  business_days: number
  settled: boolean
  covers_outage: boolean
}

export interface SpotsDelta {
  abs: number | null
  pct: number | null
}

export interface SpotsCompare {
  current: SpotsBucket
  previous: SpotsBucket
  window: SpotsWindow
  previous_window: SpotsWindow
  deltas: Record<string, SpotsDelta>
}

export interface SpotsProjectionLeg {
  mtd: number
  projected: number | null
  last_month: number
  vs_last_month: SpotsDelta
}

export interface SpotsSummary {
  range: SpotsBucket
  range_window: SpotsWindow
  week: SpotsCompare
  month: SpotsCompare
  settled_week: SpotsCompare
  settled_month: SpotsCompare
  projection: Record<string, SpotsProjectionLeg> & {
    business_days_elapsed: number
    business_days_total: number
    business_days_last_month: number
    pace: number | null
  }
  maturity_days: number
  hd_maturity_days: number
}

export interface SpotsTrendPoint extends SpotsBucket {
  bucket: string
  bucket_end: string
  provisional: boolean
  covers_outage: boolean
}

export interface SpotsBreakdownRow extends SpotsBucket {
  label: string
  prev_presented: number | null
  delta_presented: SpotsDelta
  delta_win_rate: SpotsDelta
}

export interface SpotsBreakdown {
  rows: SpotsBreakdownRow[]
  totals: SpotsBucket
  dim: SpotsDim
  sort: SpotsSort
  previous_window: SpotsWindow
  min_decided_for_rate: number
}

export interface SpotsFilterOptions {
  channels: string[]
  equipment: string[]
  divisions: string[]
  customers: string[]
  actors: string[]
  data_floor: string
  year_end: string
  maturity_days: number
  hd_maturity_days: number
  outage: { start: string; end: string }
  bot_outcomes_from: string
}

export interface SpotsActualsPoint {
  bucket: string
  loads: number
  revenue: number
  profit: number
  margin: number | null
}

export interface SpotsActuals {
  available: boolean
  series: SpotsActualsPoint[]
  totals: {
    loads: number
    revenue: number
    profit: number
    margin: number | null
  } | null
}

export interface SpotsFeed {
  source: string
  heartbeat: string | null
  last_event: string | null
  stale_minutes: number | null
  is_stale: boolean
}

export interface SpotsFreshness {
  feeds: SpotsFeed[]
  spot: string | null
  gold: string | null
  stale_minutes: number | null
  is_stale: boolean
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const ROOT = "custom/production-spots-trends"

export function useSpotsFilterOptions() {
  return useQuery({
    queryKey: ["production-spots-trends", "filters"],
    queryFn: ({ signal }) => apiFetch<SpotsFilterOptions>(`${ROOT}/filters`, signal),
    staleTime: 10 * 60 * 1000,
    ...PST_RETRY,
  })
}

export function useSpotsSummary(f: SpotsFilters) {
  return useQuery({
    queryKey: ["production-spots-trends", "summary", ...key(f)],
    queryFn: ({ signal }) => apiFetch<SpotsSummary>(`${ROOT}/summary${qs(f)}`, signal),
    placeholderData: keepPreviousData,
    ...PST_RETRY,
  })
}

export function useSpotsTrend(f: SpotsFilters, grain: SpotsGrain) {
  return useQuery({
    queryKey: ["production-spots-trends", "trend", grain, ...key(f)],
    queryFn: ({ signal }) =>
      apiFetch<SpotsTrendPoint[]>(`${ROOT}/trend${qs(f, { grain })}`, signal),
    placeholderData: keepPreviousData,
    ...PST_RETRY,
  })
}

export function useSpotsBreakdown(f: SpotsFilters, dim: SpotsDim, sort: SpotsSort) {
  return useQuery({
    queryKey: ["production-spots-trends", "breakdown", dim, sort, ...key(f)],
    queryFn: ({ signal }) =>
      apiFetch<SpotsBreakdown>(`${ROOT}/breakdown${qs(f, { dim, sort })}`, signal),
    placeholderData: keepPreviousData,
    ...PST_RETRY,
  })
}

export function useSpotsActuals(f: SpotsFilters, grain: SpotsGrain) {
  return useQuery({
    queryKey: ["production-spots-trends", "actuals", grain, ...key(f)],
    queryFn: ({ signal }) =>
      apiFetch<SpotsActuals>(`${ROOT}/actuals${qs(f, { grain })}`, signal),
    placeholderData: keepPreviousData,
    ...PST_RETRY,
  })
}

export function useSpotsFreshness() {
  return useQuery({
    queryKey: ["production-spots-trends", "freshness"],
    queryFn: ({ signal }) => apiFetch<SpotsFreshness>(`${ROOT}/freshness`, signal),
    staleTime: 5 * 60 * 1000,
    ...PST_RETRY,
  })
}

// ---------------------------------------------------------------------------
// Formatters — every one returns an em-dash for null/NaN, never "0", so a
// missing figure can never be read as a real zero.
// ---------------------------------------------------------------------------

export const DASH = "—"

export function fmtCount(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  return Math.round(Number(n)).toLocaleString("en-US")
}

/** Sign outside the symbol: -$484, never $-484. `Math.round(-0.4)` is `-0` and
 *  `-0 < 0` is false, so a negative that rounds away prints $0, not -$0. */
export function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  const v = Math.round(Number(n))
  return (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US")
}

export function fmtUsdShort(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  const v = Number(n)
  const a = Math.abs(v)
  const sign = v < 0 ? "-" : ""
  if (a >= 1_000_000) return `${sign}$${(a / 1_000_000).toFixed(1)}M`
  if (a >= 1_000) return `${sign}$${Math.round(a / 1_000)}k`
  return `${sign}$${Math.round(a)}`
}

/** Percentages travel the wire as FRACTIONS. */
export function fmtPct(n: number | null | undefined, dp = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  return `${(Number(n) * 100).toFixed(dp)}%`
}

/** A delta percentage, signed. */
export function fmtDeltaPct(n: number | null | undefined, dp = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  const v = Number(n) * 100
  return `${v >= 0 ? "+" : ""}${v.toFixed(dp)}%`
}

export function fmtDeltaCount(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  const v = Math.round(Number(n))
  return `${v >= 0 ? "+" : ""}${v.toLocaleString("en-US")}`
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return DASH
  const [y, mo, d] = iso.slice(0, 10).split("-")
  return `${mo}/${d}/${y.slice(2)}`
}

export function fmtRange(w: { start: string; end: string } | undefined): string {
  if (!w) return DASH
  return `${fmtDate(w.start)} → ${fmtDate(w.end)}`
}

/** Tone for a delta. `goodDown` inverts it: a rising skip rate or no-reply rate
 *  is bad news, and colouring it green is how a page congratulates a team for
 *  getting worse. */
export function deltaTone(
  n: number | null | undefined,
  goodDown = false
): "up" | "down" | "flat" {
  if (n === null || n === undefined || Number.isNaN(n) || Number(n) === 0) return "flat"
  const good = goodDown ? Number(n) < 0 : Number(n) > 0
  return good ? "up" : "down"
}

export const TONE_CLASS: Record<"up" | "down" | "flat", string> = {
  up: "text-[#047857]",
  down: "text-[#B91C1C]",
  flat: "text-[#9CA3AF]",
}
