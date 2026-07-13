"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
}

async function apiFetch<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const ATTRITION_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Shared filter contract — Attrition WoW has no date range (everything is
// anchored to the most recent completed Mon-Sun week).
// ---------------------------------------------------------------------------

export interface AttritionFilters {
  teams?: string[]
  customer?: string
  contract?: string
  lane?: string
  // Bruno 2026-05-25 (page 6): the "RUAN" pseudo-team. When set to "ruan" the
  // backend scopes to RUAN customers under TEAM-DFW and groups/labels by the
  // `client` sub-shipper instead of customer_name.
  view?: "ruan"
  // Bruno 2026-06-30: the CEO Executive Attrition tab passes a DFW sub-team
  // (TM1..TM4) to narrow TEAM-DFW rows to a single team. Only summary/pivot
  // honor it; the native Attrition-WoW report never sets it.
  sub_team?: string
}

function buildQs(f: AttritionFilters, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  if (f.teams && f.teams.length) q.set("teams", f.teams.join(","))
  if (f.customer) q.set("customer", f.customer)
  if (f.contract) q.set("contract", f.contract)
  if (f.lane) q.set("lane", f.lane)
  if (f.view) q.set("view", f.view)
  if (f.sub_team) q.set("sub_team", f.sub_team)
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

function keyOf(f: AttritionFilters) {
  return [
    (f.teams ?? []).slice().sort().join(","),
    f.customer ?? "",
    f.contract ?? "",
    f.lane ?? "",
    f.view ?? "",
    f.sub_team ?? "",
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AttritionFilterOptions {
  teams: string[]
  customers: string[]
  contract_types: string[]
}

export interface AttritionFreshness {
  last_load_date: string | null
  rows_in_scope: number
  last_completed_week: { start: string; end: string }
}

export interface DiffPair {
  diff: number | null
  pct: number | null
}

export interface MetricBlock {
  l8w_avg: number | null
  lw: number | null
  l2w_avg: number | null
  diff_lw_vs_l8w: DiffPair
  diff_l2w_vs_l8w: DiffPair
}

export interface CountBlock {
  l8w: number
  lw: number
  diff: number | null
  pct: number | null
}

export interface AttritionSummary {
  windows: {
    l8w: { start: string; end: string }
    lw: { start: string; end: string }
    l2w: { start: string; end: string }
  }
  active_lanes: CountBlock
  active_customers: CountBlock
  loads: MetricBlock
  revenue: MetricBlock
  profit: MetricBlock
  margin_pct: MetricBlock
  profit_per_load: MetricBlock
}

export interface WeekRow {
  week_start: string
  loads: number
  customers: number
  revenue: number
  profit: number
  margin_pct: number | null
}

export interface AttritionTrends {
  weeks: WeekRow[]
  reference: {
    l8w_avg_loads: number
    l8w_avg_customers: number
    l8w_avg_revenue: number
    l8w_avg_profit: number
    l8w_avg_margin: number | null
  }
}

// Bruno 2026-06-11 (Overview): weekly Customer Attrition ratio. For each
// completed week, ratio = distinct customers that week / distinct customers
// in the prior 8 weeks. ``week_no`` is the ISO week (his "Week 23" labels).
export interface CustomerAttritionPoint {
  week_start: string
  week_no: number
  numerator: number
  denominator: number
  ratio: number | null
}

export interface CustomerAttrition {
  weeks: CustomerAttritionPoint[]
}

export interface PivotRow {
  week_start: string
  dim_key: string
  // Bruno Attrition R (PDF 2026-07-13): Team value per row (global team_id for
  // the "by Customer" view, individual sub-team for "by Customer and Lane";
  // null for the "by Team" view). Rendered as a Team column after Status.
  team?: string | null
  value: number | null
  // Bruno round-5 (2026-05-19): backend includes raw rev/prof when metric is
  // "margin" so the Totals row can compute a weighted-avg margin.
  revenue?: number
  profit?: number
}

export interface AttritionPivot {
  data: PivotRow[]
  meta: {
    dim: "customer" | "team" | "customer_lane"
    metric: "loads" | "revenue" | "profit" | "margin"
    weeks: number
  }
}

export interface ReactiveRow {
  team: string | null
  customer: string | null
  avg_loads_l8w: number
  avg_rev_l8w: number
  avg_profit_l8w: number
  avg_margin_l8w: number | null
  avg_loads_l2_4w: number
  avg_rev_l2_4w: number
  avg_profit_l2_4w: number
  avg_margin_l2_4w: number | null
  avg_loads_l5_9w: number
  avg_rev_l5_9w: number
  avg_profit_l5_9w: number
  avg_margin_l5_9w: number | null
  lw_loads: number
  lw_revenue: number
  lw_profit: number
  lw_margin: number | null
  load_diff_lw_vs_l8w: number
  pct_var_loads_lw_vs_l8w: number | null
  pct_var_rev_lw_vs_l8w: number | null
  pct_var_profit_lw_vs_l8w: number | null
  pct_var_loads_l2_4_vs_l8w: number | null
  pct_var_rev_l2_4_vs_l8w: number | null
  pct_var_profit_l2_4_vs_l8w: number | null
  pct_var_loads_l5_9_vs_l8w: number | null
  pct_var_rev_l5_9_vs_l8w: number | null
  pct_var_profit_l5_9_vs_l8w: number | null
  last_load_date: string | null
  days_since_last_load: number | null
  gap_before_last: number | null
  bucket:
    | "lw"
    | "l2_4w"
    | "l5_9w"
    | "spot_recent"
    | "spot_stale"
    | "gt_1y"
    | "no_load"
  reactive_this_week: boolean
  // Bruno round-3 (2026-05-07): true when last load is within 7d AND the prior
  // load was 8-63 days before — i.e. customer hopped back from L2-4W or L5-9W.
  reactive_lw_returning: boolean
}

export interface AttritionReactive {
  data: ReactiveRow[]
  meta: {
    windows: {
      l8w: { start: string; end: string }
      lw: { start: string; end: string }
      l2_4w: { start: string; end: string }
      l5_9w: { start: string; end: string }
    }
  }
}

// Bruno R8 (2026-06-03): /lane-summary rows aggregate per (team_id, customer,
// contract_type) — the lane grain (and the lane field) is gone; the route path
// keeps its name for wire stability.
export interface LaneSummaryRow {
  team: string | null
  customer: string | null
  contract_type: string | null
  avg_loads_l8w: number
  avg_rev_l8w: number
  avg_profit_l8w: number
  avg_margin_l8w: number | null
  avg_loads_l2_4w: number
  avg_rev_l2_4w: number
  avg_profit_l2_4w: number
  lw_loads: number
  lw_revenue: number
  lw_profit: number
  lw_margin: number | null
  total_loads: number
  total_revenue: number
  total_profit: number
  total_margin: number | null
  load_diff_lw_vs_l8w: number
  pct_var_loads_lw_vs_l8w: number | null
  pct_var_rev_lw_vs_l8w: number | null
  pct_var_profit_lw_vs_l8w: number | null
  pct_var_loads_l2_4_vs_l8w: number | null
  pct_var_rev_l2_4_vs_l8w: number | null
  pct_var_profit_l2_4_vs_l8w: number | null
  last_load_date: string | null
  days_since_last_load: number | null
  bucket: ReactiveRow["bucket"]
}

export interface WowVarRow {
  team: string
  customer_id: string | null
  customer_name: string | null
  var: number
}

export interface WowVariation {
  total: number
  by_team: { team: string; var: number }[]
  by_customer: WowVarRow[]
  windows: {
    lw: { start: string; end: string }
    lw_prev: { start: string; end: string }
  }
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useAttritionFilters(view?: "ruan") {
  return useQuery({
    queryKey: ["attrition-wow", "filters", view ?? ""],
    queryFn: () =>
      apiFetch<AttritionFilterOptions>(
        `custom/attrition-wow/filters${view ? `?view=${view}` : ""}`,
      ),
    staleTime: 10 * 60_000,
    ...ATTRITION_RETRY,
  })
}

export function useAttritionFreshness() {
  return useQuery({
    queryKey: ["attrition-wow", "freshness"],
    queryFn: () => apiFetch<AttritionFreshness>("custom/attrition-wow/freshness"),
    staleTime: 60_000,
    ...ATTRITION_RETRY,
  })
}

export function useAttritionSummary(f: AttritionFilters) {
  return useQuery({
    queryKey: ["attrition-wow", "summary", ...keyOf(f)],
    queryFn: () =>
      apiFetch<AttritionSummary>(`custom/attrition-wow/summary${buildQs(f)}`),
    staleTime: 5 * 60_000,
    ...ATTRITION_RETRY,
  })
}

export function useAttritionTrends(f: AttritionFilters, weeks = 15) {
  return useQuery({
    queryKey: ["attrition-wow", "trends", weeks, ...keyOf(f)],
    queryFn: () =>
      apiFetch<AttritionTrends>(
        `custom/attrition-wow/weekly-trends${buildQs(f, { weeks: String(weeks) })}`,
      ),
    staleTime: 5 * 60_000,
    ...ATTRITION_RETRY,
  })
}

export function useAttritionCustomerAttrition(f: AttritionFilters, weeks = 15) {
  return useQuery({
    queryKey: ["attrition-wow", "customer-attrition", weeks, ...keyOf(f)],
    queryFn: () =>
      apiFetch<CustomerAttrition>(
        `custom/attrition-wow/customer-attrition${buildQs(f, { weeks: String(weeks) })}`,
      ),
    staleTime: 5 * 60_000,
    ...ATTRITION_RETRY,
  })
}

export function useAttritionPivot(
  f: AttritionFilters,
  dim: "customer" | "team" | "customer_lane",
  metric: "loads" | "revenue" | "profit" | "margin",
  weeks = 12,
) {
  return useQuery({
    queryKey: ["attrition-wow", "pivot", dim, metric, weeks, ...keyOf(f)],
    queryFn: async () => {
      const res = await apiFetch<PivotRow[]>(
        `custom/attrition-wow/pivot${buildQs(f, {
          dim,
          metric,
          weeks: String(weeks),
        })}`,
      )
      return res
    },
    staleTime: 5 * 60_000,
    ...ATTRITION_RETRY,
  })
}

export function useAttritionReactive(f: AttritionFilters) {
  return useQuery({
    queryKey: ["attrition-wow", "reactive", ...keyOf(f)],
    queryFn: async () => {
      const res = await fetch(
        `/api/proxy/custom/attrition-wow/reactive-summary${buildQs(f)}`,
        { headers: { "Content-Type": "application/json" } },
      )
      if (!res.ok) throw new Error(`API error: ${res.status}`)
      return res.json() as Promise<{
        success: boolean
        data: ReactiveRow[]
        meta: AttritionReactive["meta"]
        error?: string
      }>
    },
    staleTime: 5 * 60_000,
    ...ATTRITION_RETRY,
  })
}

export function useAttritionLaneSummary(f: AttritionFilters) {
  return useQuery({
    queryKey: ["attrition-wow", "lane-summary", ...keyOf(f)],
    queryFn: () =>
      apiFetch<LaneSummaryRow[]>(`custom/attrition-wow/lane-summary${buildQs(f)}`),
    staleTime: 5 * 60_000,
    ...ATTRITION_RETRY,
  })
}

export function useAttritionWowVariation(f: AttritionFilters) {
  return useQuery({
    queryKey: ["attrition-wow", "wow-var", ...keyOf(f)],
    queryFn: () =>
      apiFetch<WowVariation>(`custom/attrition-wow/wow-variation${buildQs(f)}`),
    staleTime: 5 * 60_000,
    ...ATTRITION_RETRY,
  })
}

// ---------------------------------------------------------------------------
// Losses tab (Bruno 2026-05-25 pages 1-2) — negative-margin loads only.
// ---------------------------------------------------------------------------

export interface LossPoint {
  bucket: string // ISO date (month-start or Monday week-start)
  neg_profit: number // Σ margin_amt where margin_amt < 0 (negative number)
  neg_loads: number // count of negative-margin loads
}

export interface WorstLaneRow {
  customer: string | null
  origin: string | null
  dest: string | null
  loads: number
  revenue: number
  profit: number
  margin: number | null
}

export interface NegCustomerRow {
  customer: string | null
  loads: number
  revenue: number
  profit: number
  margin: number | null
}

export interface LossTotals {
  loads: number
  revenue: number
  profit: number
  margin: number | null
}

// Bruno 2026-05-28: the Losses tab date range applies to the two tables only.
export type LossRange = "ytd" | "mtd" | "wtd" | "last_month" | "custom"

export interface LossDateRange {
  key: LossRange
  from: string // ISO (inclusive)
  to: string // ISO (inclusive)
}

export interface AttritionLosses {
  by_month: LossPoint[]
  by_week: LossPoint[]
  worst_lanes: WorstLaneRow[]
  by_customer: NegCustomerRow[]
  range: LossDateRange
  totals: { lanes: LossTotals; customers: LossTotals }
}

// `range`/`from`/`to` scope the tables only; the charts ignore them server-side.
export function useAttritionLosses(
  f: AttritionFilters,
  range: LossRange = "ytd",
  from?: string,
  to?: string,
) {
  const extra: Record<string, string> = { range }
  if (range === "custom" && from) extra.from = from
  if (range === "custom" && to) extra.to = to
  return useQuery({
    queryKey: ["attrition-wow", "losses", ...keyOf(f), range, from ?? "", to ?? ""],
    queryFn: () =>
      apiFetch<AttritionLosses>(`custom/attrition-wow/losses${buildQs(f, extra)}`),
    staleTime: 5 * 60_000,
    ...ATTRITION_RETRY,
  })
}
