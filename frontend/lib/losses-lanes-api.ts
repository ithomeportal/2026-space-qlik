"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total: number; page: number; limit: number }
}

async function apiFetch<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const LOSSES_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Shared filter contract
// ---------------------------------------------------------------------------

export type LossesRange = "mtd" | "last_month" | "ytd" | "custom"

export interface LossesFilters {
  range: LossesRange
  startDate?: string
  endDate?: string
  teams?: string[]   // empty or omitted => all teams
  customer?: string
}

function lossesQs(f: LossesFilters, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  if (f.teams && f.teams.length) q.set("teams", f.teams.join(","))
  if (f.customer) q.set("customer", f.customer)
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

function queryKeyFilters(f: LossesFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    (f.teams ?? []).slice().sort().join(","),
    f.customer ?? "",
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface LossesFilterOptions {
  teams: string[]
  customers: string[]
  year_start: string
  year_end: string
}

export interface LossesSummary {
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
  window: { start: string; end: string }
  teams_applied: string[]
}

export interface LossesLaneRow {
  customer: string | null
  lane: string | null
  revenue: number
  profit: number
  margin_pct: number | null
  profit_1: number
  diff_1: number
  profit_2: number
  diff_2: number
  profit_3: number
  diff_3: number
}

export interface LossesFreshness {
  last_updated: string | null
  last_created: string | null
  rows_in_scope: number
}

export interface LossesLaneTrendPoint {
  bucket: string
  total_loads: number
  loss_loads: number
  total_revenue: number
  total_profit: number
  loss_revenue: number
  loss_profit: number
}

export interface LossesWeeklyMoverRow {
  customer: string | null
  lane: string | null
  this_rank: number | null
  last_rank: number | null
  this_profit: number | null
  last_profit: number | null
  this_revenue: number | null
}

export interface LossesWeeklyMovers {
  new_entries: LossesWeeklyMoverRow[]
  dropped: LossesWeeklyMoverRow[]
  moved: LossesWeeklyMoverRow[]
  window: {
    this_week: { start: string; end: string }
    last_week: { start: string; end: string }
    top_n: number
  }
}

export interface LossesCustomerRow {
  customer: string | null
  loads: number
  revenue: number
  profit: number
}

export interface LossesLaneComboRow {
  lane: string | null
  loads: number
  revenue: number
  profit: number
}

export interface LossesTrendPoint {
  bucket: string
  loads: number
  revenue: number
  profit: number
}

export interface LossesOrderRow {
  actual_day: string | null
  id: string | null
  customer_id: string | null
  customer_name: string | null
  origin: string | null
  destination: string | null
  revenue: number
  profit: number
  margin_pct: number | null
  contract_type: string | null
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useLossesFilters() {
  return useQuery({
    queryKey: ["losses", "filters"],
    queryFn: () => apiFetch<LossesFilterOptions>("custom/losses-lanes/filters"),
    staleTime: 10 * 60 * 1000,
    ...LOSSES_RETRY,
  })
}

export function useLossesSummary(filters: LossesFilters) {
  return useQuery({
    queryKey: ["losses", "summary", ...queryKeyFilters(filters)],
    queryFn: () =>
      apiFetch<LossesSummary>(`custom/losses-lanes/summary${lossesQs(filters)}`),
    ...LOSSES_RETRY,
  })
}

export function useLossesByLane(
  filters: LossesFilters,
  sort: string,
  page: number,
  limit = 100,
  thresholds?: [number, number, number],
) {
  const t = thresholds ?? [0.15, 0.18, 0.20]
  return useQuery({
    queryKey: [
      "losses",
      "by-lane",
      ...queryKeyFilters(filters),
      sort,
      page,
      limit,
      t[0],
      t[1],
      t[2],
    ],
    queryFn: () =>
      apiFetch<LossesLaneRow[]>(
        `custom/losses-lanes/by-lane${lossesQs(filters, {
          sort,
          page: String(page),
          limit: String(limit),
          threshold_1: String(t[0]),
          threshold_2: String(t[1]),
          threshold_3: String(t[2]),
        })}`,
      ),
    ...LOSSES_RETRY,
  })
}

export function useLossesByCustomer(
  filters: LossesFilters,
  sort: string,
  page: number,
  limit = 100,
) {
  return useQuery({
    queryKey: ["losses", "by-customer", ...queryKeyFilters(filters), sort, page, limit],
    queryFn: () =>
      apiFetch<LossesCustomerRow[]>(
        `custom/losses-lanes/by-customer${lossesQs(filters, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    ...LOSSES_RETRY,
  })
}

export function useLossesTopLanesCombo(filters: LossesFilters, limit = 10) {
  return useQuery({
    queryKey: ["losses", "top-combo", ...queryKeyFilters(filters), limit],
    queryFn: () =>
      apiFetch<LossesLaneComboRow[]>(
        `custom/losses-lanes/top-lanes-combo${lossesQs(filters, { limit: String(limit) })}`,
      ),
    ...LOSSES_RETRY,
  })
}

export function useLossesByDay(filters: LossesFilters) {
  return useQuery({
    queryKey: ["losses", "by-day", ...queryKeyFilters(filters)],
    queryFn: () =>
      apiFetch<LossesTrendPoint[]>(`custom/losses-lanes/by-day${lossesQs(filters)}`),
    ...LOSSES_RETRY,
  })
}

export function useLossesByWeek(teams: string[] | undefined, customer: string | undefined) {
  const qs = new URLSearchParams()
  if (teams && teams.length) qs.set("teams", teams.join(","))
  if (customer) qs.set("customer", customer)
  const s = qs.toString()
  return useQuery({
    queryKey: ["losses", "by-week", (teams ?? []).slice().sort().join(","), customer ?? ""],
    queryFn: () =>
      apiFetch<LossesTrendPoint[]>(
        `custom/losses-lanes/by-week${s ? `?${s}` : ""}`,
      ),
    ...LOSSES_RETRY,
  })
}

export function useLossesByMonth(teams: string[] | undefined, customer: string | undefined) {
  const qs = new URLSearchParams()
  if (teams && teams.length) qs.set("teams", teams.join(","))
  if (customer) qs.set("customer", customer)
  const s = qs.toString()
  return useQuery({
    queryKey: ["losses", "by-month", (teams ?? []).slice().sort().join(","), customer ?? ""],
    queryFn: () =>
      apiFetch<LossesTrendPoint[]>(
        `custom/losses-lanes/by-month${s ? `?${s}` : ""}`,
      ),
    ...LOSSES_RETRY,
  })
}

export function useLossesFreshness() {
  return useQuery({
    queryKey: ["losses", "freshness"],
    queryFn: () => apiFetch<LossesFreshness>("custom/losses-lanes/freshness"),
    staleTime: 5 * 60 * 1000,
    refetchInterval: 10 * 60 * 1000,
    ...LOSSES_RETRY,
  })
}

export function useLossesLaneTrend(
  lane: string | undefined,
  teams: string[] | undefined,
  customer: string | undefined,
  days = 60,
) {
  const qs = new URLSearchParams()
  if (lane) qs.set("lane", lane)
  if (teams && teams.length) qs.set("teams", teams.join(","))
  if (customer) qs.set("customer", customer)
  qs.set("days", String(days))
  return useQuery({
    queryKey: [
      "losses",
      "lane-trend",
      lane ?? "",
      (teams ?? []).slice().sort().join(","),
      customer ?? "",
      days,
    ],
    queryFn: () =>
      apiFetch<LossesLaneTrendPoint[]>(
        `custom/losses-lanes/lane-trend?${qs.toString()}`,
      ),
    enabled: Boolean(lane),
    ...LOSSES_RETRY,
  })
}

export function useLossesWeeklyMovers(
  teams: string[] | undefined,
  customer: string | undefined,
  topN = 10,
) {
  const qs = new URLSearchParams()
  if (teams && teams.length) qs.set("teams", teams.join(","))
  if (customer) qs.set("customer", customer)
  qs.set("top_n", String(topN))
  return useQuery({
    queryKey: [
      "losses",
      "weekly-movers",
      (teams ?? []).slice().sort().join(","),
      customer ?? "",
      topN,
    ],
    queryFn: () =>
      apiFetch<LossesWeeklyMovers>(
        `custom/losses-lanes/weekly-movers?${qs.toString()}`,
      ),
    ...LOSSES_RETRY,
  })
}

export function useLossesOrders(
  filters: LossesFilters,
  sort: string,
  page: number,
  limit = 100,
  lane?: string,
) {
  return useQuery({
    queryKey: [
      "losses",
      "orders",
      ...queryKeyFilters(filters),
      sort,
      page,
      limit,
      lane ?? "",
    ],
    queryFn: () => {
      const extra: Record<string, string> = {
        sort,
        page: String(page),
        limit: String(limit),
      }
      if (lane) extra.lane = lane
      return apiFetch<LossesOrderRow[]>(
        `custom/losses-lanes/orders${lossesQs(filters, extra)}`,
      )
    },
    ...LOSSES_RETRY,
  })
}
