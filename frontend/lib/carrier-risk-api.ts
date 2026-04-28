"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total?: number; page?: number; limit?: number }
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
// Filter contract — shared across all carrier-risk endpoints
// ---------------------------------------------------------------------------

export type CarrierRiskRange = "mtd" | "last_month" | "last_3m" | "ytd" | "custom"

export interface CarrierRiskFilters {
  range: CarrierRiskRange
  startDate?: string
  endDate?: string
  teams?: string[]    // empty / omitted => all teams
  customer?: string
  lane?: string
  carrier?: string
}

function buildQs(
  f: CarrierRiskFilters,
  extra?: Record<string, string | number>,
) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  if (f.teams && f.teams.length) q.set("teams", f.teams.join(","))
  if (f.customer) q.set("customer", f.customer)
  if (f.lane) q.set("lane", f.lane)
  if (f.carrier) q.set("carrier", f.carrier)
  if (extra) {
    for (const [k, v] of Object.entries(extra)) q.set(k, String(v))
  }
  const s = q.toString()
  return s ? `?${s}` : ""
}

function keyFromFilters(f: CarrierRiskFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    (f.teams ?? []).slice().sort().join(","),
    f.customer ?? "",
    f.lane ?? "",
    f.carrier ?? "",
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CarrierRiskFacets {
  teams: string[]
  customers: string[]
  year_floor: string
  today: string
}

export interface CarrierRiskKpis {
  movements: number
  distinct_carriers: number
  distinct_lanes: number
  avg_carrier_cost: number
  revenue: number
  profit: number
  margin_pct: number | null
  single_carrier_lane_pct: number | null
  single_carrier_volume_pct: number | null
  window: { start: string; end: string }
  teams_applied: string[]
}

export type RiskBand = "red" | "amber" | "green"

export interface CarrierRiskLaneRow {
  lane: string | null
  n_mov: number
  n_carrier: number
  avg_cost: number
  top1_share: number | null
  hhi: number | null
  cv_cost: number | null
  margin_pct: number | null
  revenue: number
  profit: number
  risk_band: RiskBand
}

export interface CarrierLaneRow {
  carrier_name: string | null
  lane: string | null
  mov: number
  avg_cost: number
}

export interface CarrierDetailRow {
  id: string | null
  actual_departure: string | null
  customer: string | null
  carrier_name: string | null
  lane: string | null
  revenue: number | null
  profit: number | null
  margin_pct: number | null
}

export interface CarrierLaneTrendPoint {
  week_start: string
  mov: number
  n_carrier: number
  avg_cost: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useCarrierRiskFacets() {
  return useQuery({
    queryKey: ["carrier-risk", "facets"],
    queryFn: () => apiFetch<CarrierRiskFacets>("custom/carrier-risk/facets"),
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    ...RETRY,
  })
}

export function useCarrierRiskKpis(f: CarrierRiskFilters) {
  return useQuery({
    queryKey: ["carrier-risk", "kpis", ...keyFromFilters(f)],
    queryFn: () =>
      apiFetch<CarrierRiskKpis>(`custom/carrier-risk/kpis${buildQs(f)}`),
    staleTime: 5 * 60 * 1000,
    ...RETRY,
  })
}

export function useCarrierRiskByLane(
  f: CarrierRiskFilters,
  sort: string,
  page: number,
  limit: number,
) {
  return useQuery({
    queryKey: ["carrier-risk", "by-lane", ...keyFromFilters(f), sort, page, limit],
    queryFn: () =>
      apiFetch<CarrierRiskLaneRow[]>(
        `custom/carrier-risk/by-lane${buildQs(f, { sort, page, limit })}`,
      ),
    staleTime: 5 * 60 * 1000,
    placeholderData: (prev) => prev,
    ...RETRY,
  })
}

export function useCarrierRiskByCarrierLane(
  f: CarrierRiskFilters,
  sort: string,
  page: number,
  limit: number,
) {
  return useQuery({
    queryKey: [
      "carrier-risk",
      "by-carrier-lane",
      ...keyFromFilters(f),
      sort,
      page,
      limit,
    ],
    queryFn: () =>
      apiFetch<CarrierLaneRow[]>(
        `custom/carrier-risk/by-carrier-lane${buildQs(f, { sort, page, limit })}`,
      ),
    staleTime: 5 * 60 * 1000,
    placeholderData: (prev) => prev,
    ...RETRY,
  })
}

export function useCarrierRiskDetails(
  f: CarrierRiskFilters,
  sort: string,
  page: number,
  limit: number,
) {
  return useQuery({
    queryKey: ["carrier-risk", "details", ...keyFromFilters(f), sort, page, limit],
    queryFn: () =>
      apiFetch<CarrierDetailRow[]>(
        `custom/carrier-risk/details${buildQs(f, { sort, page, limit })}`,
      ),
    staleTime: 5 * 60 * 1000,
    placeholderData: (prev) => prev,
    ...RETRY,
  })
}

export function useCarrierRiskLaneTrend(
  lane: string | undefined,
  teams: string[],
  customer?: string,
) {
  return useQuery({
    enabled: !!lane,
    queryKey: ["carrier-risk", "lane-trend", lane ?? "", teams.slice().sort().join(","), customer ?? ""],
    queryFn: () => {
      const q = new URLSearchParams()
      if (lane) q.set("lane", lane)
      if (teams && teams.length) q.set("teams", teams.join(","))
      if (customer) q.set("customer", customer)
      return apiFetch<CarrierLaneTrendPoint[]>(
        `custom/carrier-risk/lane-trend?${q.toString()}`,
      )
    },
    staleTime: 10 * 60 * 1000,
    ...RETRY,
  })
}
