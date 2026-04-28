"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total: number; page?: number; page_size?: number }
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

export interface RfpFilters {
  dateFrom: string | null
  dateTo: string | null
  divisions: string[]
  departments: string[]
  businessTypes: string[]
  customers: string[]
  types: string[]
  statuses: string[]
}

export const EMPTY_FILTERS: RfpFilters = {
  dateFrom: null,
  dateTo: null,
  divisions: [],
  departments: [],
  businessTypes: [],
  customers: [],
  types: [],
  statuses: [],
}

function qs(f: RfpFilters, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  if (f.dateFrom) q.set("date_from", f.dateFrom)
  if (f.dateTo) q.set("date_to", f.dateTo)
  if (f.divisions.length) q.set("division", f.divisions.join(","))
  if (f.departments.length) q.set("department", f.departments.join(","))
  if (f.businessTypes.length) q.set("business_type", f.businessTypes.join(","))
  if (f.customers.length) q.set("customer", f.customers.join(","))
  if (f.types.length) q.set("type_quotation", f.types.join(","))
  if (f.statuses.length) q.set("status", f.statuses.join(","))
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

function keyFilters(f: RfpFilters) {
  return [
    f.dateFrom ?? "",
    f.dateTo ?? "",
    f.divisions.slice().sort().join(","),
    f.departments.slice().sort().join(","),
    f.businessTypes.slice().sort().join(","),
    f.customers.slice().sort().join(","),
    f.types.slice().sort().join(","),
    f.statuses.slice().sort().join(","),
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface RfpFilterOptions {
  divisions: string[]
  departments: string[]
  business_types: string[]
  customers: string[]
  types: string[]
  statuses: string[]
  min_date: string | null
  max_date: string | null
  as_of: string | null
}

export interface RfpStatusBlock {
  rfps: number
  offer_lanes: number
  lane_quoted: number
  lane_participation_pct: number | null
  total_offer_loads: number
  load_count_quoted: number
  volume_participation_pct: number | null
  potential_revenue: number
  pct_potential_rev: number | null
}

export interface RfpWonBlock extends RfpStatusBlock {
  lane_awarded: number
  lane_awarded_ratio_pct: number | null
  load_awarded: number
  load_awarded_ratio_pct: number | null
  awarded_revenue: number
  awarded_convertio_ratio: number | null
}

export interface RfpSummary {
  grand_total_pot_rev: number
  open: RfpStatusBlock
  closed: RfpStatusBlock
  lost: RfpStatusBlock
  won: RfpWonBlock
}

export interface RfpConvertioRow {
  ratio: number
  revenue_awarded_at_ratio: number
  actual_vs_conv_ratio: number
  pot_rev_gp_15: number
}

export interface RfpConvertio {
  pot_rev_closed: number
  revenue_awarded: number
  rows: RfpConvertioRow[]
}

export interface RfpTrendRow {
  ym: string
  volume_won: number
  volume_conv_ratio: number | null
  revenue_won: number
  revenue_conv_ratio: number | null
}

export interface RfpPotentialMonthRow {
  ym: string
  potential_closed: number
  revenue_awarded: number
}

export interface RfpByTabRow {
  division: string
  potential_revenue: number
  potential_wo: number
  awarded: number
  conv: number | null
}

export interface RfpByTabTotals {
  potential_revenue: number
  potential_wo: number
  awarded: number
  conv: number | null
}

export interface RfpCustomerRow {
  customer: string
  bids: number
  total_lanes: number
  lanes_quoted: number
  lanes_ratio_pct: number | null
  total_volume: number
  volume_quoted: number
  volume_ratio_pct: number | null
  potential_revenue: number
  awarded_revenue: number
  awarded_conv_ratio_pct: number | null
}

export interface RfpCustomerDetailRow {
  customer: string
  ym: string | null
  type_quotation: string
  total_lanes: number
  lanes_quoted: number
  lane_part_pct: number | null
  lanes_awarded: number
  lanes_conv_rat_pct: number | null
  total_volume: number
  volume_quoted: number
  volume_part_pct: number | null
  loads_awarded: number
  loads_conv_rat_pct: number | null
  potential_revenue: number
  rev_awarded: number
  rev_conv_ratio_pct: number | null
}

export interface RfpDetailRow {
  rfp_id: number | null
  month: string
  year: number | null
  customer: string
  division: string
  type_quotation: string
  total_lanes: number
  lanes_quoted: number
  lane_participation_pct: number | null
  lanes_awarded: number
  total_volume: number
  volume_quoted: number
  volume_participation_pct: number | null
  loads_awarded: number
  potential_revenue: number
  revenue_awarded: number
  status: string
  sales_executive: string
  submitted_date: string | null
  end_date: string | null
}

export type RfpDetailSort =
  | "submitted_desc"
  | "submitted_asc"
  | "potential_desc"
  | "potential_asc"
  | "awarded_desc"
  | "awarded_asc"
  | "rfp_desc"
  | "rfp_asc"

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useRfpFilterOptions() {
  return useQuery({
    queryKey: ["rfp", "filter-options"],
    queryFn: () =>
      apiFetch<RfpFilterOptions>("custom/rfp-performance/filter-options"),
    staleTime: 10 * 60 * 1000,
    ...RETRY,
  })
}

export function useRfpSummary(f: RfpFilters) {
  return useQuery({
    queryKey: ["rfp", "summary", ...keyFilters(f)],
    queryFn: () =>
      apiFetch<RfpSummary>(`custom/rfp-performance/summary${qs(f)}`),
    ...RETRY,
  })
}

export function useRfpConvertioRatio(f: RfpFilters) {
  return useQuery({
    queryKey: ["rfp", "convertio-ratio", ...keyFilters(f)],
    queryFn: () =>
      apiFetch<RfpConvertio>(`custom/rfp-performance/convertio-ratio${qs(f)}`),
    staleTime: 10 * 60 * 1000,
    ...RETRY,
  })
}

export function useRfpTrend12m(f: RfpFilters) {
  return useQuery({
    queryKey: ["rfp", "trend-12m", ...keyFilters(f)],
    queryFn: () =>
      apiFetch<{ rows: RfpTrendRow[] }>(
        `custom/rfp-performance/trend-12m${qs(f)}`,
      ),
    staleTime: 10 * 60 * 1000,
    ...RETRY,
  })
}

export function useRfpPotentialByMonth(f: RfpFilters) {
  return useQuery({
    queryKey: ["rfp", "potential-by-month", ...keyFilters(f)],
    queryFn: () =>
      apiFetch<{ rows: RfpPotentialMonthRow[] }>(
        `custom/rfp-performance/potential-by-month${qs(f)}`,
      ),
    staleTime: 10 * 60 * 1000,
    ...RETRY,
  })
}

export function useRfpSummaryByTab(f: RfpFilters, tab: "operations" | "sales" | "division") {
  return useQuery({
    queryKey: ["rfp", "summary-by-tab", tab, ...keyFilters(f)],
    queryFn: () =>
      apiFetch<{ rows: RfpByTabRow[]; totals: RfpByTabTotals }>(
        `custom/rfp-performance/summary-by-tab${qs(f, { tab })}`,
      ),
    ...RETRY,
  })
}

export function useRfpSummaryByCustomer(f: RfpFilters) {
  return useQuery({
    queryKey: ["rfp", "summary-by-customer", ...keyFilters(f)],
    queryFn: () =>
      apiFetch<{ rows: RfpCustomerRow[] }>(
        `custom/rfp-performance/summary-by-customer${qs(f)}`,
      ),
    ...RETRY,
  })
}

export function useRfpSummaryByCustomerDetail(f: RfpFilters) {
  return useQuery({
    queryKey: ["rfp", "summary-by-customer-detail", ...keyFilters(f)],
    queryFn: () =>
      apiFetch<{ rows: RfpCustomerDetailRow[] }>(
        `custom/rfp-performance/summary-by-customer-detail${qs(f)}`,
      ),
    ...RETRY,
  })
}

export function useRfpDetails(f: RfpFilters, page: number, sort: RfpDetailSort) {
  return useQuery({
    queryKey: ["rfp", "details", page, sort, ...keyFilters(f)],
    queryFn: () =>
      apiFetch<{ rows: RfpDetailRow[] }>(
        `custom/rfp-performance/details${qs(f, { page: String(page), sort })}`,
      ),
    ...RETRY,
  })
}
