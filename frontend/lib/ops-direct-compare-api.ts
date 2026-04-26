"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: {
    total?: number
    page?: number
    limit?: number
    cached?: boolean
    top?: number
    total_profit?: number
    total_revenue?: number
    window?: { start: string; end: string }
  }
}

async function apiFetch<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Per-panel filter contract
// ---------------------------------------------------------------------------

export type DCRange = "mtd" | "last_month" | "ytd" | "custom"
export type DCDivision = "All" | "CORP" | "DFW"

export interface DCPanelFilters {
  range: DCRange
  startDate?: string
  endDate?: string
  division: DCDivision
  teams?: string[]      // empty/omitted → all in division
  subTeams?: string[]   // only meaningful when division === "DFW"
}

function panelQs(prefix: "" | "p1_" | "p2_", f: DCPanelFilters): string[] {
  const parts: string[] = []
  parts.push(`${prefix}range=${encodeURIComponent(f.range)}`)
  if (f.range === "custom" && f.startDate)
    parts.push(`${prefix}start_date=${encodeURIComponent(f.startDate)}`)
  if (f.range === "custom" && f.endDate)
    parts.push(`${prefix}end_date=${encodeURIComponent(f.endDate)}`)
  if (f.division && f.division !== "All")
    parts.push(`${prefix}division=${encodeURIComponent(f.division)}`)
  if (f.teams && f.teams.length)
    parts.push(`${prefix}teams=${encodeURIComponent(f.teams.join(","))}`)
  if (f.subTeams && f.subTeams.length)
    parts.push(`${prefix}sub_teams=${encodeURIComponent(f.subTeams.join(","))}`)
  return parts
}

function singleQs(f: DCPanelFilters, extra?: Record<string, string>) {
  const parts = panelQs("", f)
  if (extra) for (const [k, v] of Object.entries(extra)) parts.push(`${k}=${encodeURIComponent(v)}`)
  return parts.length ? `?${parts.join("&")}` : ""
}

function diffQs(p1: DCPanelFilters, p2: DCPanelFilters, extra?: Record<string, string>) {
  const parts = [...panelQs("p1_", p1), ...panelQs("p2_", p2)]
  if (extra) for (const [k, v] of Object.entries(extra)) parts.push(`${k}=${encodeURIComponent(v)}`)
  return parts.length ? `?${parts.join("&")}` : ""
}

function panelKey(f: DCPanelFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    f.division,
    (f.teams ?? []).slice().sort().join(","),
    (f.subTeams ?? []).slice().sort().join(","),
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DCFilterOptions {
  divisions: string[]
  teams: string[]
  corp_teams: string[]
  dfw_team: string
  dfw_sub_teams: string[]
  companies: string[]
  year_start: string
  year_end: string
}

export interface DCPanelSummary {
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
  avg_r_per_l: number | null
  avg_p_per_l: number | null
  window: { start: string; end: string }
  teams_applied: string[]
  sub_teams_applied: string[] | null
}

export interface DCConcentrationSlice {
  customer: string
  revenue: number
  profit: number
  concentration_pct: number | null
  is_others: boolean
}

export interface DCCustomerRow {
  customer: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
  avg_p_per_l: number | null
  diff_profit?: number
  diff_revenue?: number
}

export interface DCLaneRow {
  lane: string
  origin: string | null
  destination: string | null
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
  avg_p_per_l: number | null
  diff_profit?: number
  diff_revenue?: number
}

export interface DCTrendPoint {
  bucket: string | null
  revenue: number
  profit: number
  margin_pct: number | null
}

export interface DCCustRevMargin {
  customer: string
  revenue: number
  profit: number
  margin_pct: number | null
}

export interface DCOrderRow {
  actual_day: string | null
  id: string
  cust_id: string | null
  customer: string | null
  team: string | null
  lane: string | null
  revenue: number
  profit: number
  margin_pct: number | null
  avg_r_per_l: number
  avg_p_per_l: number
}

export interface DCFreshness {
  last_updated: string | null
  last_created: string | null
  rows_in_scope: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useDCFilters() {
  return useQuery({
    queryKey: ["dc", "filters"],
    queryFn: () => apiFetch<DCFilterOptions>("custom/ops-direct-compare/filters"),
    staleTime: 60_000,
    ...RETRY,
  })
}

export function useDCFreshness() {
  return useQuery({
    queryKey: ["dc", "freshness"],
    queryFn: () => apiFetch<DCFreshness>("custom/ops-direct-compare/freshness"),
    staleTime: 60_000,
    ...RETRY,
  })
}

export function useDCPanelSummary(panel: "p1" | "p2", f: DCPanelFilters) {
  return useQuery({
    queryKey: ["dc", "panel-summary", panel, ...panelKey(f)],
    queryFn: () =>
      apiFetch<DCPanelSummary>(`custom/ops-direct-compare/panel-summary${singleQs(f)}`),
    staleTime: 30_000,
    ...RETRY,
  })
}

export function useDCConcentration(panel: "p1" | "p2", f: DCPanelFilters, top = 5) {
  return useQuery({
    queryKey: ["dc", "concentration", panel, top, ...panelKey(f)],
    queryFn: () =>
      apiFetch<DCConcentrationSlice[]>(
        `custom/ops-direct-compare/concentration${singleQs(f, { top: String(top) })}`,
      ),
    staleTime: 30_000,
    ...RETRY,
  })
}

export function useDCByCustomer(
  panel: "p1" | "p2",
  f: DCPanelFilters,
  opts: { sort?: string; page?: number; limit?: number } = {},
) {
  const sort = opts.sort ?? "profit_desc"
  const page = opts.page ?? 1
  const limit = opts.limit ?? 200
  return useQuery({
    queryKey: ["dc", "by-customer", panel, sort, page, limit, ...panelKey(f)],
    queryFn: () =>
      apiFetch<DCCustomerRow[]>(
        `custom/ops-direct-compare/by-customer${singleQs(f, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    staleTime: 30_000,
    ...RETRY,
  })
}

export function useDCByCustomerDiff(
  p1: DCPanelFilters,
  p2: DCPanelFilters,
  opts: { sort?: string; page?: number; limit?: number } = {},
) {
  const sort = opts.sort ?? "p2_profit_desc"
  const page = opts.page ?? 1
  const limit = opts.limit ?? 200
  return useQuery({
    queryKey: [
      "dc",
      "by-customer-diff",
      sort,
      page,
      limit,
      ...panelKey(p1),
      "|",
      ...panelKey(p2),
    ],
    queryFn: () =>
      apiFetch<DCCustomerRow[]>(
        `custom/ops-direct-compare/by-customer-diff${diffQs(p1, p2, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    staleTime: 30_000,
    ...RETRY,
  })
}

export function useDCByLane(
  panel: "p1" | "p2",
  f: DCPanelFilters,
  opts: { sort?: string; page?: number; limit?: number } = {},
) {
  const sort = opts.sort ?? "profit_desc"
  const page = opts.page ?? 1
  const limit = opts.limit ?? 200
  return useQuery({
    queryKey: ["dc", "by-lane", panel, sort, page, limit, ...panelKey(f)],
    queryFn: () =>
      apiFetch<DCLaneRow[]>(
        `custom/ops-direct-compare/by-lane${singleQs(f, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    staleTime: 30_000,
    ...RETRY,
  })
}

export function useDCByLaneDiff(
  p1: DCPanelFilters,
  p2: DCPanelFilters,
  opts: { sort?: string; page?: number; limit?: number } = {},
) {
  const sort = opts.sort ?? "p2_profit_desc"
  const page = opts.page ?? 1
  const limit = opts.limit ?? 200
  return useQuery({
    queryKey: [
      "dc",
      "by-lane-diff",
      sort,
      page,
      limit,
      ...panelKey(p1),
      "|",
      ...panelKey(p2),
    ],
    queryFn: () =>
      apiFetch<DCLaneRow[]>(
        `custom/ops-direct-compare/by-lane-diff${diffQs(p1, p2, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    staleTime: 30_000,
    ...RETRY,
  })
}

export function useDCTrend12m() {
  return useQuery({
    queryKey: ["dc", "trend-12m"],
    queryFn: () =>
      apiFetch<DCTrendPoint[]>("custom/ops-direct-compare/trend-12m"),
    staleTime: 5 * 60_000, // matches backend TTL roughly
    ...RETRY,
  })
}

export function useDCCustomerRevMargin(f: DCPanelFilters, top = 20) {
  return useQuery({
    queryKey: ["dc", "cust-rev-margin", top, ...panelKey(f)],
    queryFn: () =>
      apiFetch<DCCustRevMargin[]>(
        `custom/ops-direct-compare/customer-revenue-margin${singleQs(f, {
          top: String(top),
        })}`,
      ),
    staleTime: 30_000,
    ...RETRY,
  })
}

export function useDCOrdersWindow(
  f: DCPanelFilters,
  opts: { sort?: string; page?: number; limit?: number } = {},
) {
  const sort = opts.sort ?? "date_desc"
  const page = opts.page ?? 1
  const limit = opts.limit ?? 200
  // orders-window only consumes division/team/sub-teams (date is hard-coded
  // to last+this year on the server). Strip the date keys from the cache key
  // so changing the panel's date doesn't refetch this expensive query.
  const teamKey = [
    f.division,
    (f.teams ?? []).slice().sort().join(","),
    (f.subTeams ?? []).slice().sort().join(","),
  ]
  // Build a slim query — only team/division.
  const slim = new URLSearchParams()
  if (f.division && f.division !== "All") slim.set("division", f.division)
  if (f.teams && f.teams.length) slim.set("teams", f.teams.join(","))
  if (f.subTeams && f.subTeams.length) slim.set("sub_teams", f.subTeams.join(","))
  slim.set("sort", sort)
  slim.set("page", String(page))
  slim.set("limit", String(limit))
  return useQuery({
    queryKey: ["dc", "orders-window", sort, page, limit, ...teamKey],
    queryFn: () =>
      apiFetch<DCOrderRow[]>(
        `custom/ops-direct-compare/orders-window?${slim.toString()}`,
      ),
    staleTime: 60_000,
    ...RETRY,
  })
}

// ---------------------------------------------------------------------------
// Client-side delta computation (cheaper than another round trip)
// ---------------------------------------------------------------------------

export interface DCDelta {
  revenue: number       // p1 - p2
  profit: number
  margin_pct: number | null
  loads: number
  avg_r_per_l: number | null
  avg_p_per_l: number | null
}

export function computeDelta(
  p1: DCPanelSummary | undefined,
  p2: DCPanelSummary | undefined,
): DCDelta | null {
  if (!p1 || !p2) return null
  const sub = (a: number | null, b: number | null) =>
    a === null || b === null ? null : a - b
  return {
    revenue: p1.revenue - p2.revenue,
    profit: p1.profit - p2.profit,
    margin_pct: sub(p1.margin_pct, p2.margin_pct),
    loads: p1.loads - p2.loads,
    avg_r_per_l: sub(p1.avg_r_per_l, p2.avg_r_per_l),
    avg_p_per_l: sub(p1.avg_p_per_l, p2.avg_p_per_l),
  }
}
