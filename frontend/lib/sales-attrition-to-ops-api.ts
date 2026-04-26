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

export type SaopRange = "last_365" | "mtd" | "last_month" | "ytd" | "custom"

export type SaopBucket =
  | ""
  | "1_30"
  | "31_90"
  | "91_180"
  | "181_365"
  | "365_plus"

export interface SaopFilters {
  range: SaopRange
  startDate?: string
  endDate?: string
  teams?: string[]
  customer?: string
  bucket?: SaopBucket
}

function qs(f: SaopFilters, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  if (f.teams && f.teams.length) q.set("teams", f.teams.join(","))
  if (f.customer) q.set("customer", f.customer)
  if (f.bucket) q.set("bucket", f.bucket)
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

function keyFilters(f: SaopFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    (f.teams ?? []).slice().sort().join(","),
    f.customer ?? "",
    f.bucket ?? "",
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SaopFilterOptions {
  teams: string[]
  customers: string[]
  buckets: string[]
}

export interface SaopDetailsRow {
  customer: string
  team: string | null
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
  last_load_date: string | null
  days_since: number | null
  sparkline: number[]
}

export interface SaopDetailsTotals {
  customers: number
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
}

export interface SaopDetailsResp {
  rows: SaopDetailsRow[]
  totals: SaopDetailsTotals
  window: { start: string; end: string }
  teams_applied: string[]
  bucket: string | null
}

export interface SaopTrendPoint {
  month: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
}

export interface SaopTrendResp {
  series: SaopTrendPoint[]
  window: { start: string; end: string; months: number }
  teams_applied: string[]
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useSaopFilters() {
  return useQuery({
    queryKey: ["saop", "filters"],
    queryFn: () =>
      apiFetch<SaopFilterOptions>("custom/sales-attrition-to-ops/filters"),
    staleTime: 10 * 60 * 1000,
    ...RETRY,
  })
}

export function useSaopDetails(
  filters: SaopFilters,
  sort: string,
  page: number,
  limit = 100,
) {
  return useQuery({
    queryKey: ["saop", "details", ...keyFilters(filters), sort, page, limit],
    queryFn: () =>
      apiFetch<SaopDetailsResp>(
        `custom/sales-attrition-to-ops/details${qs(filters, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    ...RETRY,
  })
}

export function useSaopTrend(
  teams: string[] | undefined,
  customer: string | undefined,
) {
  const q = new URLSearchParams()
  if (teams && teams.length) q.set("teams", teams.join(","))
  if (customer) q.set("customer", customer)
  const s = q.toString()
  return useQuery({
    queryKey: [
      "saop",
      "trend",
      (teams ?? []).slice().sort().join(","),
      customer ?? "",
    ],
    queryFn: () =>
      apiFetch<SaopTrendResp>(
        `custom/sales-attrition-to-ops/trend${s ? `?${s}` : ""}`,
      ),
    staleTime: 10 * 60 * 1000,
    ...RETRY,
  })
}
