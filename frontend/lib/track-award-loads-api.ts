"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total: number; page?: number; limit?: number }
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

export interface TalFilters {
  statuses: string[]
  divisions: string[]
  customerIds: string[]
  awardNames: string[]
}

function qs(f: TalFilters, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  if (f.statuses.length) q.set("status", f.statuses.join(","))
  if (f.divisions.length) q.set("division", f.divisions.join(","))
  if (f.customerIds.length) q.set("customer_id", f.customerIds.join(","))
  if (f.awardNames.length) q.set("award_name", f.awardNames.join(","))
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

function keyFilters(f: TalFilters) {
  return [
    f.statuses.slice().sort().join(","),
    f.divisions.slice().sort().join(","),
    f.customerIds.slice().sort().join(","),
    f.awardNames.slice().sort().join(","),
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface TalFilterOptions {
  statuses: string[]
  divisions: string[]
  customer_ids: string[]
  award_names: string[]
  as_of: string | null
}

export interface TalKpis {
  lanes: {
    unique_lanes_awarded: number
    unique_actual_lanes: number
    lane_variance: number
    ratio: number | null
  }
  volume: {
    awarded_volume: number
    total_actual_volume: number
    load_variance: number
    ratio: number | null
  }
  profit: {
    projected_profit: number
    actual_profit: number
    profit_variance: number
    ratio: number | null
  }
  carrier_cost: {
    projected_carrier_cost: number
    actual_carrier_cost: number
    variance: number
    ratio: number | null
  }
}

export interface TalAggRow {
  unique_lanes_awarded: number
  awarded_volume: number
  total_actual_volume: number
  load_variance: number
  projected_profit: number
  actual_profit: number
  profit_variance: number
  projected_carrier_cost: number
  actual_carrier_cost: number
  carrier_cost_variance: number
}

export interface TalByDivisionRow extends TalAggRow {
  division: string
}
export interface TalByCustomerRow extends TalAggRow {
  customer_id: string
}
export interface TalByCustomerAwardRow extends TalAggRow {
  customer_name: string
  award_name: string
  division: string
  status: string
}
export interface TalByAwardLaneRow extends TalAggRow {
  audit_id: number | null
  award_id_name: string | null
  award_name: string
  customer_name: string
  lane: string
  equip: string | null
  effective_date: string | null
  expiration_date: string | null
  days_to_expiration: number | null
  load_ratio: number | null
  profit_ratio: number | null
  carrier_cost_ratio: number | null
  prev_total_loads: number | null
  prev_snapshot: string | null
  wow_delta_loads: number | null
  rpm: number | null
  min_charge: number | null
  all_in_rates: number | null
}

export type TalAwardLaneSort =
  | "days_asc"
  | "days_desc"
  | "loads_desc"
  | "loads_asc"
  | "load_variance_desc"
  | "load_variance_asc"
  | "profit_desc"
  | "profit_asc"
  | "profit_variance_desc"
  | "profit_variance_asc"
  | "carrier_desc"
  | "carrier_asc"
  | "award_asc"

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useTalFilters() {
  return useQuery({
    queryKey: ["tal", "filters"],
    queryFn: () =>
      apiFetch<TalFilterOptions>("custom/track-award-loads/filters"),
    staleTime: 10 * 60 * 1000,
    ...RETRY,
  })
}

export function useTalKpis(f: TalFilters) {
  return useQuery({
    queryKey: ["tal", "kpis", ...keyFilters(f)],
    queryFn: () =>
      apiFetch<TalKpis>(`custom/track-award-loads/kpis${qs(f)}`),
    ...RETRY,
  })
}

export function useTalByDivision(f: TalFilters) {
  return useQuery({
    queryKey: ["tal", "by-division", ...keyFilters(f)],
    queryFn: () =>
      apiFetch<{ rows: TalByDivisionRow[] }>(
        `custom/track-award-loads/by-division${qs(f)}`,
      ),
    ...RETRY,
  })
}

export function useTalByCustomer(f: TalFilters) {
  return useQuery({
    queryKey: ["tal", "by-customer", ...keyFilters(f)],
    queryFn: () =>
      apiFetch<{ rows: TalByCustomerRow[] }>(
        `custom/track-award-loads/by-customer${qs(f)}`,
      ),
    ...RETRY,
  })
}

export function useTalByCustomerAward(f: TalFilters) {
  return useQuery({
    queryKey: ["tal", "by-customer-award", ...keyFilters(f)],
    queryFn: () =>
      apiFetch<{ rows: TalByCustomerAwardRow[] }>(
        `custom/track-award-loads/by-customer-award${qs(f)}`,
      ),
    ...RETRY,
  })
}

export function useTalByAwardLane(f: TalFilters, sort: TalAwardLaneSort) {
  return useQuery({
    queryKey: ["tal", "by-award-lane", sort, ...keyFilters(f)],
    queryFn: () =>
      apiFetch<{ rows: TalByAwardLaneRow[] }>(
        `custom/track-award-loads/by-award-lane${qs(f, { sort })}`,
      ),
    ...RETRY,
  })
}
