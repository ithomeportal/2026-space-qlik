"use client"

import { useQuery, keepPreviousData } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total: number; limit: number }
}

async function apiFetch<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const DFW_LOSSES_RETRY = {
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

export type DfwLossesRange = "mtd" | "wtd" | "last_month" | "ytd" | "custom"

export interface DfwLossesFilters {
  range: DfwLossesRange
  startDate?: string
  endDate?: string
  contractTypes?: string[]
  customerNames?: string[]
}

function dfwQs(f: DfwLossesFilters, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  // Repeated keys — proxy forwards via .append() so multi-select survives.
  for (const c of f.contractTypes ?? []) q.append("contract_type", c)
  for (const c of f.customerNames ?? []) q.append("customer_name", c)
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

function dfwKey(f: DfwLossesFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    (f.contractTypes ?? []).slice().sort().join(","),
    (f.customerNames ?? []).slice().sort().join(","),
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DfwLossesFilterOptions {
  contract_types: string[]
  customers: string[]
  year_start: string
  year_end: string
  window: { start: string; end: string }
}

export interface DfwLossesDailyRow {
  date: string
  day: number
  month: string
  loads: number
  amount_lost: number
  loss_per_load: number | null
  by_customer: Record<string, number>
}

export interface DfwLossesDaily {
  customers: string[]
  customers_truncated: boolean
  rows: DfwLossesDailyRow[]
  summary: {
    loads_avg: number
    amount_lost_avg: number
    loss_per_load_avg: number | null
  }
  /** Server-side full-universe Totals row (§44). `loss_per_load` here is a
   *  ratio of sums, so it will not equal `summary.loss_per_load_avg` (a mean of
   *  per-day ratios) — both are correct. */
  totals: {
    loads: number
    amount_lost: number
    loss_per_load: number | null
    by_customer: Record<string, number>
  }
  window: { start: string; end: string }
}

export interface DfwLossesOrderRow {
  order_id: string
  customer: string | null
  origin_actual_departure: string | null
  revenue: number
  profit: number
  margin_pct: number | null
}

export interface DfwLossesOrders {
  day: string
  rows: DfwLossesOrderRow[]
  totals: {
    loads: number
    revenue: number
    profit: number
    margin_pct: number | null
  }
}

export type DfwLossesOrdersSort =
  | "departure_desc" | "departure_asc"
  | "order_id_desc" | "order_id_asc"
  | "customer_desc" | "customer_asc"
  | "revenue_desc" | "revenue_asc"
  | "profit_desc" | "profit_asc"
  | "margin_desc" | "margin_asc"

export interface DfwLossesLaneRow {
  customer: string | null
  origin: string | null
  destination: string | null
  loads: number
  loss: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useDfwLossesFilters(filters: DfwLossesFilters) {
  return useQuery({
    queryKey: ["dfw-losses", "filters", ...dfwKey(filters)],
    queryFn: () =>
      apiFetch<DfwLossesFilterOptions>(
        `custom/dfw-losses/filters${dfwQs({ ...filters, contractTypes: [], customerNames: [] })}`,
      ),
    staleTime: 10 * 60 * 1000,
    placeholderData: keepPreviousData,
    ...DFW_LOSSES_RETRY,
  })
}

export function useDfwLossesDaily(filters: DfwLossesFilters) {
  return useQuery({
    queryKey: ["dfw-losses", "daily", ...dfwKey(filters)],
    queryFn: () =>
      apiFetch<DfwLossesDaily>(`custom/dfw-losses/daily${dfwQs(filters)}`),
    placeholderData: keepPreviousData,
    ...DFW_LOSSES_RETRY,
  })
}

/**
 * Deep link to the day drill-down, opened in a new tab from the Daily table's
 * `Loads` cell (Bruno 2026-08-03 R1). Only the filters that change *which*
 * orders belong to the day travel — the range selector does not, since the day
 * itself is already pinned.
 */
export function dfwLossesOrdersHref(
  day: string,
  filters: Pick<DfwLossesFilters, "contractTypes" | "customerNames">,
): string {
  const q = new URLSearchParams()
  q.set("day", day)
  // Repeated keys, never a comma-join: customer names legitimately contain
  // commas ("CONAGRA FOODS PACKAGED FOODS, LLC"), and joining them here would
  // make the value unparseable at the other end (§45).
  for (const c of filters.contractTypes ?? []) q.append("contract", c)
  for (const c of filters.customerNames ?? []) q.append("customer", c)
  return `/reports/dfw-losses/orders?${q.toString()}`
}

export function useDfwLossesOrders(
  day: string,
  filters: Pick<DfwLossesFilters, "contractTypes" | "customerNames">,
  sort: DfwLossesOrdersSort,
  page: number,
  limit = 200,
) {
  const q = new URLSearchParams()
  q.set("day", day)
  for (const c of filters.contractTypes ?? []) q.append("contract_type", c)
  for (const c of filters.customerNames ?? []) q.append("customer_name", c)
  q.set("sort", sort)
  q.set("page", String(page))
  q.set("limit", String(limit))
  return useQuery({
    // §50 — the key covers every field the query string serialises.
    queryKey: [
      "dfw-losses",
      "orders",
      day,
      (filters.contractTypes ?? []).slice().sort().join(","),
      (filters.customerNames ?? []).slice().sort().join(","),
      sort,
      page,
      limit,
    ],
    queryFn: () => apiFetch<DfwLossesOrders>(`custom/dfw-losses/orders?${q.toString()}`),
    enabled: Boolean(day),
    placeholderData: keepPreviousData,
    ...DFW_LOSSES_RETRY,
  })
}

export function useDfwLossesLanes(filters: DfwLossesFilters, limit = 50) {
  return useQuery({
    queryKey: ["dfw-losses", "lanes", ...dfwKey(filters), limit],
    queryFn: () =>
      apiFetch<DfwLossesLaneRow[]>(
        `custom/dfw-losses/lanes${dfwQs(filters, { limit: String(limit) })}`,
      ),
    placeholderData: keepPreviousData,
    ...DFW_LOSSES_RETRY,
  })
}
