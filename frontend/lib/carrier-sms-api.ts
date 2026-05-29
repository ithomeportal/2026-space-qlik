"use client"

import { keepPreviousData, useQuery } from "@tanstack/react-query"

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
// Filter contract — shared across the carrier-sms endpoints
// ---------------------------------------------------------------------------

export interface CarrierSmsFilters {
  search?: string
  includeInactive?: boolean
  flagged?: boolean
  sort?: string
  page?: number
  limit?: number
}

function buildQs(f: CarrierSmsFilters, withPaging: boolean): string {
  const q = new URLSearchParams()
  if (f.search) q.set("search", f.search)
  if (f.includeInactive) q.set("include_inactive", "true")
  if (f.flagged) q.set("flagged", "true")
  if (f.sort) q.set("sort", f.sort)
  if (withPaging) {
    q.set("page", String(f.page ?? 1))
    q.set("limit", String(f.limit ?? 50))
  }
  const s = q.toString()
  return s ? `?${s}` : ""
}

/** Direct (proxied) URL for the server-streamed CSV of the full filtered set. */
export function carrierSmsCsvHref(f: CarrierSmsFilters): string {
  return `/api/proxy/custom/carrier-sms/carriers.csv${buildQs(f, false)}`
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CarrierSmsRow {
  id: string
  name: string
  city: string | null
  state: string | null
  dot_number: string | null
  mc_number: string | null
  is_active: boolean
  vehicle_oos_pct: number | null
  driver_oos_pct: number | null
  vehicle_insp_total: number | null
  driver_insp_total: number | null
  basic_unsafe: number | null
  basic_hos: number | null
  basic_fitness: number | null
  basic_drugalc: number | null
  basic_vehmaint: number | null
  unsafe_ac: string | null
  hos_ac: string | null
  fitness_ac: string | null
  drugalc_sv: string | null
  vehmaint_ac: string | null
  mcp_risk_overall: string | null
  mcp_risk_points: number | null
  mcp_is_blocked: boolean | null
  mcp_last_checked: string | null
  data_file_date: string | null
  nat_avg_vehicle: number
  nat_avg_driver: number
}

export interface CarrierSmsSummary {
  total: number
  above_vehicle_nat_avg: number
  above_driver_nat_avg: number
  concerning_basics: number
  mcp_not_acceptable: number
  missing_sms: number
  sms_data_newest: string | null
  sms_data_oldest: string | null
  mcp_checked_newest: string | null
  mcp_checked_oldest: string | null
  nat_avg_vehicle: number
  nat_avg_driver: number
  basic_concern: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useCarrierSmsList(f: CarrierSmsFilters) {
  return useQuery({
    queryKey: [
      "carrier-sms-list",
      f.search ?? "",
      !!f.includeInactive,
      !!f.flagged,
      f.sort ?? "",
      f.page ?? 1,
      f.limit ?? 50,
    ],
    queryFn: () =>
      apiFetch<CarrierSmsRow[]>(`custom/carrier-sms/carriers${buildQs(f, true)}`),
    placeholderData: keepPreviousData,
    ...RETRY,
  })
}

export function useCarrierSmsSummary(f: CarrierSmsFilters) {
  return useQuery({
    queryKey: [
      "carrier-sms-summary",
      f.search ?? "",
      !!f.includeInactive,
      !!f.flagged,
    ],
    queryFn: () =>
      apiFetch<CarrierSmsSummary>(`custom/carrier-sms/summary${buildQs(f, false)}`),
    ...RETRY,
  })
}
