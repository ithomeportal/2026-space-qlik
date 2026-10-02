"use client"

import { createContext, createElement, useContext, type ReactNode } from "react"
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
    sort?: string
    totals?: DCCompareRow | null
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
// API prefix context — default points at the cross-team
// `/custom/ops-direct-compare` router. Per-team pages
// (e.g. /reports/corp-t1-direct-compare) wrap their content in
// <DcApiProvider prefix="custom/ops-direct-compare-t1"> so every hook below
// transparently hits the team-locked endpoints. The prefix is also baked into
// every queryKey so the 4 team copies cache independently of each other and of
// the cross-team report.
// ---------------------------------------------------------------------------

const DEFAULT_PREFIX = "custom/ops-direct-compare"

const ApiPrefixContext = createContext<string>(DEFAULT_PREFIX)

export function DcApiProvider({
  prefix,
  children,
}: {
  prefix: string
  children: ReactNode
}) {
  return createElement(ApiPrefixContext.Provider, { value: prefix }, children)
}

function useApiPrefix() {
  return useContext(ApiPrefixContext)
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

export interface DCPanelBudget {
  applicable: boolean
  loads?: number
  revenue?: number
  profit?: number
}

export interface DCPanelSummary {
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
  avg_r_per_l: number | null
  avg_p_per_l: number | null
  budget?: DCPanelBudget
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

/** One panel's figures for a compare row. */
export interface DCSide {
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
  avg_p_per_l: number | null
}

/** Combined row: both panels + Panel 1 − Panel 2 (Bruno 2026-10-01). */
export interface DCCompareRow {
  customer?: string | null
  lane?: string | null
  p1: DCSide
  p2: DCSide
  diff: DCSide
}

export interface DCPivotRow extends DCCompareRow {
  customer: string
  lane_count: number
  lanes: DCCompareRow[]
}

export interface DCCompareMeta {
  total: number
  page: number
  limit: number
  sort: string
  totals: DCCompareRow | null
}

export interface DCYoYPoint {
  revenue: number
  profit: number
  margin_pct: number | null
}

export interface DCYoYMonth {
  month: number
  label: string
  prev: DCYoYPoint | null
  cur: DCYoYPoint | null
}

export interface DCYoY {
  prev_year: number
  cur_year: number
  months: DCYoYMonth[]
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
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "dc", "filters"],
    queryFn: () => apiFetch<DCFilterOptions>(`${prefix}/filters`),
    staleTime: 60_000,
    ...RETRY,
  })
}

export function useDCFreshness() {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "dc", "freshness"],
    queryFn: () => apiFetch<DCFreshness>(`${prefix}/freshness`),
    staleTime: 60_000,
    ...RETRY,
  })
}

export function useDCPanelSummary(panel: "p1" | "p2", f: DCPanelFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "dc", "panel-summary", panel, ...panelKey(f)],
    queryFn: () =>
      apiFetch<DCPanelSummary>(`${prefix}/panel-summary${singleQs(f)}`),
    staleTime: 30_000,
    ...RETRY,
  })
}

export function useDCConcentration(panel: "p1" | "p2", f: DCPanelFilters, top = 5) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "dc", "concentration", panel, top, ...panelKey(f)],
    queryFn: () =>
      apiFetch<DCConcentrationSlice[]>(
        `${prefix}/concentration${singleQs(f, { top: String(top) })}`,
      ),
    staleTime: 30_000,
    ...RETRY,
  })
}

export type DCCompareDim = "customer" | "lane"

const COMPARE_PATH: Record<DCCompareDim, string> = {
  customer: "by-customer-diff",
  lane: "by-lane-diff",
}

export const DC_DEFAULT_SORT = "p1_profit_desc"

/** Details by Customer / Details by Lane — both panels in one row. */
export function useDCCompare(
  dim: DCCompareDim,
  p1: DCPanelFilters,
  p2: DCPanelFilters,
  opts: { sort?: string; page?: number; limit?: number } = {},
) {
  const prefix = useApiPrefix()
  const sort = opts.sort ?? DC_DEFAULT_SORT
  const page = opts.page ?? 1
  const limit = opts.limit ?? 200
  return useQuery({
    queryKey: [
      prefix, "dc", COMPARE_PATH[dim], sort, page, limit,
      ...panelKey(p1), "|", ...panelKey(p2),
    ],
    queryFn: () =>
      apiFetch<DCCompareRow[]>(
        `${prefix}/${COMPARE_PATH[dim]}${diffQs(p1, p2, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    staleTime: 30_000,
    ...RETRY,
  })
}

/** Customer → Lane pivot: customers paged, each with ALL its lanes. */
export function useDCPivot(
  p1: DCPanelFilters,
  p2: DCPanelFilters,
  opts: { sort?: string; page?: number; limit?: number } = {},
) {
  const prefix = useApiPrefix()
  const sort = opts.sort ?? DC_DEFAULT_SORT
  const page = opts.page ?? 1
  const limit = opts.limit ?? 200
  return useQuery({
    queryKey: [
      prefix, "dc", "by-customer-lane-diff", sort, page, limit,
      ...panelKey(p1), "|", ...panelKey(p2),
    ],
    queryFn: () =>
      apiFetch<DCPivotRow[]>(
        `${prefix}/by-customer-lane-diff${diffQs(p1, p2, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    staleTime: 30_000,
    ...RETRY,
  })
}

/** Jan–Dec, previous year vs current year. Ignores both panels' filters. */
export function useDCTrendYoY() {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "dc", "trend-yoy"],
    queryFn: () => apiFetch<DCYoY>(`${prefix}/trend-yoy`),
    staleTime: 5 * 60_000, // backend caches 10 min
    ...RETRY,
  })
}

// ---------------------------------------------------------------------------
// Period label — "MTD" / "Last Month" / "YTD" / "09/01–09/15" (custom). Shared
// by the panel KPI cards and every period-suffixed column header, so the card
// and the column it feeds can never name the window differently.
// ---------------------------------------------------------------------------

const RANGE_LABEL: Record<Exclude<DCRange, "custom">, string> = {
  mtd: "MTD",
  last_month: "Last Month",
  ytd: "YTD",
}

function mmdd(iso: string | undefined) {
  if (!iso || iso.length < 10) return "?"
  return `${iso.slice(5, 7)}/${iso.slice(8, 10)}`
}

export function periodLabel(f: DCPanelFilters): string {
  if (f.range !== "custom") return RANGE_LABEL[f.range]
  return `${mmdd(f.startDate)}–${mmdd(f.endDate)}`
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
