"use client"

import { useQuery, keepPreviousData } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total: number }
}

async function apiFetch<T>(path: string, signal?: AbortSignal): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
    signal,
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const HD_RETRY = {
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

export type HdSpotRange = "today" | "yesterday" | "mtd" | "last_month" | "custom"

/** McLeod order status, relabelled per the request: V=Cancelled, A=Pending to
 *  Cover, D|P=Covered. */
export type HdSpotStatus = "cancelled" | "covered" | "pending"

export interface HdSpotFilters {
  range: HdSpotRange
  startDate?: string
  endDate?: string
  equipment?: string[]
  status?: HdSpotStatus[]
}

function hdQs(f: HdSpotFilters) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  // Repeated keys — the proxy forwards with .append() so multi-select survives
  // (§45). Never comma-join.
  for (const v of f.equipment ?? []) q.append("equipment", v)
  for (const v of f.status ?? []) q.append("status", v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

/** The query key must cover EVERY field hdQs serialises, or a filter change
 *  silently serves a cached response for the previous scope (§50). */
function hdKey(f: HdSpotFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    (f.equipment ?? []).slice().sort().join("|"),
    (f.status ?? []).slice().sort().join("|"),
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HdSpotFilterOptions {
  equipment: string[]
  status: { value: HdSpotStatus; label: string; codes: string[] }[]
  data_floor: string
  year_end: string
}

export interface HdSpotSummary {
  offered: number
  quoted: number
  participation: number | null
  awarded: number
  conversion: number | null
  revenue_covered: number | null
  profit_covered: number | null
  margin_covered: number | null
  money_ok: boolean
  match_rate: number | null
  won_orders: number
  won_orders_matched: number
  start_date: string
  end_date: string
}

export interface HdSpotChartPoint {
  date: string
  awarded: number
  conversion: number | null
}

export interface HdSpotRow {
  equipment: string
  date: string
  offered: number
  quoted: number
  participation: number | null
  awarded: number
  conversion: number | null
  loads: number
  loads_cancelled: number
  loads_covered: number
  loads_pending: number
  revenue: number
  revenue_cancelled: number
  revenue_covered: number
  revenue_pending: number
  carrier_cost: number
  carrier_cost_cancelled: number
  carrier_cost_covered: number
  carrier_cost_pending: number
  profit: number
  profit_cancelled: number
  profit_covered: number
  profit_pending: number
  margin: number | null
  margin_covered: number | null
  margin_pending: number | null
}

export interface HdSpotTable {
  rows: HdSpotRow[]
  totals: HdSpotRow & {
    won_orders: number
    won_orders_matched: number
    match_rate: number | null
  }
  money_ok: boolean
}

export interface HdSpotFreshness {
  spot: string | null
  gold: string | null
  spot_stale_minutes: number | null
  is_stale: boolean
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useHdSpotFilterOptions() {
  return useQuery({
    queryKey: ["hd-spot", "filters"],
    queryFn: ({ signal }) =>
      apiFetch<HdSpotFilterOptions>("custom/hd-spot/filters", signal),
    staleTime: 10 * 60 * 1000,
    ...HD_RETRY,
  })
}

export function useHdSpotSummary(f: HdSpotFilters) {
  return useQuery({
    queryKey: ["hd-spot", "summary", ...hdKey(f)],
    queryFn: ({ signal }) =>
      apiFetch<HdSpotSummary>(`custom/hd-spot/summary${hdQs(f)}`, signal),
    placeholderData: keepPreviousData,
    ...HD_RETRY,
  })
}

export function useHdSpotChart(f: HdSpotFilters) {
  return useQuery({
    queryKey: ["hd-spot", "chart", ...hdKey(f)],
    queryFn: ({ signal }) =>
      apiFetch<HdSpotChartPoint[]>(`custom/hd-spot/chart${hdQs(f)}`, signal),
    placeholderData: keepPreviousData,
    ...HD_RETRY,
  })
}

export function useHdSpotTable(f: HdSpotFilters) {
  return useQuery({
    queryKey: ["hd-spot", "table", ...hdKey(f)],
    queryFn: ({ signal }) =>
      apiFetch<HdSpotTable>(`custom/hd-spot/table${hdQs(f)}`, signal),
    placeholderData: keepPreviousData,
    ...HD_RETRY,
  })
}

export function useHdSpotFreshness() {
  return useQuery({
    queryKey: ["hd-spot", "freshness"],
    queryFn: ({ signal }) =>
      apiFetch<HdSpotFreshness>("custom/hd-spot/freshness", signal),
    staleTime: 5 * 60 * 1000,
    ...HD_RETRY,
  })
}

// ---------------------------------------------------------------------------
// Formatters — every one returns an em-dash for null/NaN, never "0", so a
// missing figure can never be read as a real zero.
// ---------------------------------------------------------------------------

const DASH = "—"

export function fmtCount(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  return Number(n).toLocaleString("en-US")
}

export function fmtVol(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  // Volumes are NUMERIC(12,2) but whole in practice; drop a trailing .00.
  const v = Number(n)
  return Number.isInteger(v) ? v.toLocaleString("en-US") : v.toFixed(2)
}

/** Sign outside the symbol: -$484, never $-484. `Math.round(-0.4)` is `-0` and
 *  `-0 < 0` is false, so a negative that rounds away prints $0, not -$0. */
export function fmtUsd(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  const v = Math.round(Number(n))
  return (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US")
}

/** Percentages travel the wire as FRACTIONS. */
export function fmtPct(n: number | null | undefined, dp = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return DASH
  return `${(Number(n) * 100).toFixed(dp)}%`
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return DASH
  const [y, m, d] = iso.slice(0, 10).split("-")
  return `${m}/${d}/${y.slice(2)}`
}
