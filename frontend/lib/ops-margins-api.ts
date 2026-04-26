"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total?: number; page?: number; limit?: number; bucket?: string; weeks?: number }
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
// Filter contract
// ---------------------------------------------------------------------------

export type OpsRange = "mtd" | "last_month" | "ytd" | "custom"
export type OpsDivision = "All" | "CORP" | "DFW"

export interface OpsFilters {
  range: OpsRange
  startDate?: string
  endDate?: string
  division: OpsDivision
  teams?: string[]       // empty/omitted = all in division
  companies?: string[]   // empty/omitted = TMS+TMS3
  subTeams?: string[]    // only meaningful when division === "DFW"
  customer?: string
  origin?: string
  destination?: string
}

function qs(f: OpsFilters, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  if (f.division && f.division !== "All") q.set("division", f.division)
  if (f.teams && f.teams.length) q.set("teams", f.teams.join(","))
  if (f.companies && f.companies.length) q.set("companies", f.companies.join(","))
  if (f.subTeams && f.subTeams.length) q.set("sub_teams", f.subTeams.join(","))
  if (f.customer) q.set("customer", f.customer)
  if (f.origin) q.set("origin", f.origin)
  if (f.destination) q.set("destination", f.destination)
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

function key(f: OpsFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    f.division,
    (f.teams ?? []).slice().sort().join(","),
    (f.companies ?? []).slice().sort().join(","),
    (f.subTeams ?? []).slice().sort().join(","),
    f.customer ?? "",
    f.origin ?? "",
    f.destination ?? "",
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OpsFilterOptions {
  divisions: string[]
  teams: string[]
  corp_teams: string[]
  dfw_team: string
  dfw_sub_teams: string[]
  companies: string[]
  customers: string[]
  origins: string[]
  destinations: string[]
  year_start: string
  year_end: string
}

export interface OpsSummary {
  loads: number
  loss_loads: number
  revenue: number
  profit: number
  loss_revenue: number
  loss_profit: number
  margin_pct: number | null
  loss_margin_pct: number | null
  window: { start: string; end: string }
  teams_applied: string[]
  companies_applied: string[]
  sub_teams_applied: string[] | null
}

export interface OpsTrendPoint {
  bucket: string | null
  loads: number
  loss_loads: number
  revenue: number
  profit: number
  margin_pct: number | null
}

export interface OpsCustomerMarginRow {
  customer: string | null
  lane_count: number
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
}

export interface OpsLaneMarginRow {
  customer: string | null
  origin: string | null
  destination: string | null
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
}

export interface OpsByLaneRow {
  customer: string | null
  origin: string | null
  destination: string | null
  loads: number
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

export interface OpsNegativeOrderRow {
  actual_day: string | null
  id: string | null
  customer: string | null
  carrier: string | null
  origin: string | null
  destination: string | null
  revenue: number
  profit: number
  margin_pct: number | null
  concentration: number | null
}

export interface OpsLossCustomerRow {
  customer: string | null
  loads: number
  revenue: number
  profit: number
  concentration: number | null
}

export interface OpsLossesByBucket {
  bucket: string | null
  loads: number
  profit: number
}

export interface OpsDistributionRow {
  bucket:
    | "lt_0"
    | "0_5"
    | "5_10"
    | "10_15"
    | "15_20"
    | "gte_20"
    | "no_revenue"
  customers: number
  revenue: number
  profit: number
}

export interface OpsCustomerSparkPoint {
  bucket: string | null
  margin_pct: number | null
  revenue: number
  profit: number
}

export interface OpsFreshness {
  last_updated: string | null
  last_created: string | null
  rows_in_scope: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useOpsFilters(f: Partial<OpsFilters>) {
  const params = new URLSearchParams()
  if (f.division && f.division !== "All") params.set("division", f.division)
  if (f.teams && f.teams.length) params.set("teams", f.teams.join(","))
  if (f.companies && f.companies.length)
    params.set("companies", f.companies.join(","))
  if (f.subTeams && f.subTeams.length)
    params.set("sub_teams", f.subTeams.join(","))
  if (f.customer) params.set("customer", f.customer)
  if (f.origin) params.set("origin", f.origin)
  const queryString = params.toString()
  return useQuery({
    queryKey: [
      "ops-margins",
      "filters",
      f.division ?? "All",
      (f.teams ?? []).slice().sort().join(","),
      (f.companies ?? []).slice().sort().join(","),
      (f.subTeams ?? []).slice().sort().join(","),
      f.customer ?? "",
      f.origin ?? "",
    ],
    queryFn: () =>
      apiFetch<OpsFilterOptions>(
        `custom/ops-margins/filters${queryString ? "?" + queryString : ""}`,
      ),
    staleTime: 5 * 60_000,
    ...RETRY,
  })
}

export function useOpsSummary(f: OpsFilters) {
  return useQuery({
    queryKey: ["ops-margins", "summary", ...key(f)],
    queryFn: () => apiFetch<OpsSummary>(`custom/ops-margins/summary${qs(f)}`),
    ...RETRY,
  })
}

export function useOpsTrend(f: OpsFilters, bucket: "day" | "week" | "month") {
  return useQuery({
    queryKey: ["ops-margins", "trend", bucket, ...key(f)],
    queryFn: () =>
      apiFetch<OpsTrendPoint[]>(
        `custom/ops-margins/trend${qs(f, { bucket })}`,
      ),
    ...RETRY,
  })
}

export function useOpsCustomersMargin(
  f: OpsFilters,
  sort: string,
  page: number,
  limit: number,
) {
  return useQuery({
    queryKey: ["ops-margins", "customers-margin", sort, page, limit, ...key(f)],
    queryFn: () =>
      apiFetch<OpsCustomerMarginRow[]>(
        `custom/ops-margins/customers-margin${qs(f, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    ...RETRY,
  })
}

export function useOpsLanesMargin(
  f: OpsFilters,
  sort: string,
  page: number,
  limit: number,
) {
  return useQuery({
    queryKey: ["ops-margins", "lanes-margin", sort, page, limit, ...key(f)],
    queryFn: () =>
      apiFetch<OpsLaneMarginRow[]>(
        `custom/ops-margins/lanes-margin${qs(f, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    ...RETRY,
  })
}

export function useOpsByLane(
  f: OpsFilters,
  sort: string,
  page: number,
  limit: number,
  thresholds: [number, number, number],
) {
  return useQuery({
    queryKey: [
      "ops-margins",
      "by-lane",
      sort,
      page,
      limit,
      thresholds.join(","),
      ...key(f),
    ],
    queryFn: () =>
      apiFetch<OpsByLaneRow[]>(
        `custom/ops-margins/by-lane${qs(f, {
          sort,
          page: String(page),
          limit: String(limit),
          threshold_1: String(thresholds[0]),
          threshold_2: String(thresholds[1]),
          threshold_3: String(thresholds[2]),
        })}`,
      ),
    ...RETRY,
  })
}

export function useOpsNegativeOrders(
  f: OpsFilters,
  sort: string,
  page: number,
  limit: number,
) {
  return useQuery({
    queryKey: ["ops-margins", "negative-orders", sort, page, limit, ...key(f)],
    queryFn: () =>
      apiFetch<OpsNegativeOrderRow[]>(
        `custom/ops-margins/negative-orders${qs(f, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    ...RETRY,
  })
}

export function useOpsLossCustomers(
  f: OpsFilters,
  sort: string,
  page: number,
  limit: number,
) {
  return useQuery({
    queryKey: ["ops-margins", "loss-customers", sort, page, limit, ...key(f)],
    queryFn: () =>
      apiFetch<OpsLossCustomerRow[]>(
        `custom/ops-margins/loss-customers${qs(f, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    ...RETRY,
  })
}

export function useOpsLossesByMonth(f: OpsFilters, months = 8) {
  return useQuery({
    queryKey: ["ops-margins", "losses-by-month", months, ...key(f)],
    queryFn: () =>
      apiFetch<OpsLossesByBucket[]>(
        `custom/ops-margins/losses-by-month${qs(f, { months: String(months) })}`,
      ),
    ...RETRY,
  })
}

export function useOpsLossesByWeek(f: OpsFilters, weeks = 8) {
  return useQuery({
    queryKey: ["ops-margins", "losses-by-week", weeks, ...key(f)],
    queryFn: () =>
      apiFetch<OpsLossesByBucket[]>(
        `custom/ops-margins/losses-by-week${qs(f, { weeks: String(weeks) })}`,
      ),
    ...RETRY,
  })
}

export function useOpsDistribution(f: OpsFilters) {
  return useQuery({
    queryKey: ["ops-margins", "distribution", ...key(f)],
    queryFn: () =>
      apiFetch<OpsDistributionRow[]>(`custom/ops-margins/distribution${qs(f)}`),
    ...RETRY,
  })
}

export function useOpsCustomerSpark(
  f: OpsFilters,
  customers: string[],
  weeks = 8,
) {
  const enabled = customers.length > 0
  return useQuery({
    enabled,
    queryKey: [
      "ops-margins",
      "customer-spark",
      weeks,
      customers.slice().sort().join(","),
      f.division,
      (f.teams ?? []).slice().sort().join(","),
      (f.companies ?? []).slice().sort().join(","),
      (f.subTeams ?? []).slice().sort().join(","),
      f.origin ?? "",
      f.destination ?? "",
    ],
    queryFn: () => {
      const params = new URLSearchParams()
      params.set("customers", customers.join(","))
      params.set("weeks", String(weeks))
      if (f.division && f.division !== "All") params.set("division", f.division)
      if (f.teams && f.teams.length) params.set("teams", f.teams.join(","))
      if (f.companies && f.companies.length)
        params.set("companies", f.companies.join(","))
      if (f.subTeams && f.subTeams.length)
        params.set("sub_teams", f.subTeams.join(","))
      if (f.origin) params.set("origin", f.origin)
      if (f.destination) params.set("destination", f.destination)
      return apiFetch<Record<string, OpsCustomerSparkPoint[]>>(
        `custom/ops-margins/customer-spark?${params.toString()}`,
      )
    },
    ...RETRY,
  })
}

export function useOpsFreshness() {
  return useQuery({
    queryKey: ["ops-margins", "freshness"],
    queryFn: () => apiFetch<OpsFreshness>("custom/ops-margins/freshness"),
    staleTime: 60_000,
    ...RETRY,
  })
}
