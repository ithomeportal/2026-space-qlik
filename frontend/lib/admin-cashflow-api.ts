"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: {
    total?: number
    page?: number
    limit?: number
    grand_total_revenue?: number
    le_threshold_count?: number
    gt_threshold_count?: number
    threshold?: number
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
// Filter contract — shared across every admin-cashflow endpoint
// ---------------------------------------------------------------------------

export type AdminCashflowRange =
  | "today"
  | "wtd"
  | "last_7d"
  | "mtd"
  | "last_month"
  | "ytd"
  | "custom"

export interface AdminCashflowFilters {
  range: AdminCashflowRange
  startDate?: string
  endDate?: string
  teams?: string[]
  companies?: string[]
  customer?: string
  contractType?: string
}

function buildQs(
  f: AdminCashflowFilters,
  extra?: Record<string, string | number>,
) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  if (f.teams && f.teams.length) q.set("teams", f.teams.join(","))
  if (f.companies && f.companies.length) q.set("companies", f.companies.join(","))
  if (f.customer) q.set("customer", f.customer)
  if (f.contractType) q.set("contract_type", f.contractType)
  if (extra) {
    for (const [k, v] of Object.entries(extra)) q.set(k, String(v))
  }
  const s = q.toString()
  return s ? `?${s}` : ""
}

function keyFromFilters(f: AdminCashflowFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    (f.teams ?? []).slice().sort().join(","),
    (f.companies ?? []).slice().sort().join(","),
    f.customer ?? "",
    f.contractType ?? "",
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AdminCashflowFacets {
  teams: string[]
  companies: string[]
  customers: string[]
  contract_types: string[]
  today: string
  year_floor: string
  alarm_usd: number
}

export interface AdminCashflowKpis {
  pct_del_bill_le10: number
  pct_bol_bill_le2: number
  pct_carrinv_bill_le2: number
  delivered_not_billed_usd: number
  ready_not_billed_usd: number
  total_unbilled_usd: number
  alarm: boolean
  alarm_threshold_usd: number
  rows_in_scope: number
  window: { start: string; end: string }
}

export interface AdminCashflowSparklines {
  weeks: string[]
  del_bill_le10: (number | null)[]
  bol_bill_le2: (number | null)[]
  carrinv_bill_le2: (number | null)[]
}

export interface DeliveredNotBilledRow {
  id: string | null
  orig_sched_early: string | null
  ship_date: string | null
  dest_actual_arrival: string | null
  customer_name: string
  team_id: string
  company_id: string
  total_charge: number
  days_since_delivery: number | null
}

export interface ReadyNotBilledRow {
  id: string | null
  orig_sched_early: string | null
  ship_date: string | null
  status: string
  customer_name: string
  team_id: string
  company_id: string
  total_charge: number
}

export interface AgingRow {
  id: string | null
  company_id: string
  team_id: string
  customer_name: string
  left_date: string | null
  bill_date: string | null
  days: number | null
  total_charge: number
}

export interface AgingBucketsData {
  buckets: { label: string; count: number }[]
  total: number
}

export interface TopDelayedCustomerRow {
  customer_name: string
  n_loads: number
  n_late: number
  late_revenue: number
  avg_days: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useAdminCashflowFacets() {
  return useQuery({
    queryKey: ["admin-cashflow", "facets"],
    queryFn: () =>
      apiFetch<AdminCashflowFacets>("custom/admin-cashflow/facets"),
    staleTime: 5 * 60 * 1000,
    ...RETRY,
  })
}

export function useAdminCashflowKpis(f: AdminCashflowFilters) {
  return useQuery({
    queryKey: ["admin-cashflow", "kpis", ...keyFromFilters(f)],
    queryFn: () =>
      apiFetch<AdminCashflowKpis>(`custom/admin-cashflow/kpis${buildQs(f)}`),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export function useAdminCashflowSparklines(f: AdminCashflowFilters) {
  // Sparklines ignore the Date filter — use a cached, scope-only key
  return useQuery({
    queryKey: [
      "admin-cashflow",
      "sparklines",
      (f.teams ?? []).slice().sort().join(","),
      (f.companies ?? []).slice().sort().join(","),
      f.customer ?? "",
      f.contractType ?? "",
    ],
    queryFn: () => {
      const q = new URLSearchParams()
      if (f.teams?.length) q.set("teams", f.teams.join(","))
      if (f.companies?.length) q.set("companies", f.companies.join(","))
      if (f.customer) q.set("customer", f.customer)
      if (f.contractType) q.set("contract_type", f.contractType)
      const s = q.toString()
      return apiFetch<AdminCashflowSparklines>(
        `custom/admin-cashflow/sparklines${s ? `?${s}` : ""}`,
      )
    },
    staleTime: 5 * 60 * 1000,
    ...RETRY,
  })
}

export function useDeliveredNotBilled(
  f: AdminCashflowFilters,
  opts: { sort: string; page: number; limit: number },
) {
  return useQuery({
    queryKey: [
      "admin-cashflow",
      "delivered-not-billed",
      ...keyFromFilters(f),
      opts.sort,
      opts.page,
      opts.limit,
    ],
    queryFn: () =>
      apiFetch<DeliveredNotBilledRow[]>(
        `custom/admin-cashflow/delivered-not-billed${buildQs(f, {
          sort: opts.sort,
          page: opts.page,
          limit: opts.limit,
        })}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export function useReadyNotBilled(
  f: AdminCashflowFilters,
  opts: { sort: string; page: number; limit: number },
) {
  return useQuery({
    queryKey: [
      "admin-cashflow",
      "ready-not-billed",
      ...keyFromFilters(f),
      opts.sort,
      opts.page,
      opts.limit,
    ],
    queryFn: () =>
      apiFetch<ReadyNotBilledRow[]>(
        `custom/admin-cashflow/ready-not-billed${buildQs(f, {
          sort: opts.sort,
          page: opts.page,
          limit: opts.limit,
        })}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export type AgingTab =
  | "delivery-vs-bill"
  | "bol-vs-bill"
  | "carrinv-vs-bill"

export function useAging(
  tab: AgingTab,
  f: AdminCashflowFilters,
  opts: { sort: string; page: number; limit: number; enabled?: boolean },
) {
  return useQuery({
    queryKey: [
      "admin-cashflow",
      "aging",
      tab,
      ...keyFromFilters(f),
      opts.sort,
      opts.page,
      opts.limit,
    ],
    queryFn: () =>
      apiFetch<AgingRow[]>(
        `custom/admin-cashflow/aging/${tab}${buildQs(f, {
          sort: opts.sort,
          page: opts.page,
          limit: opts.limit,
        })}`,
      ),
    staleTime: 60 * 1000,
    enabled: opts.enabled ?? true,
    ...RETRY,
  })
}

export function useAgingBuckets(f: AdminCashflowFilters) {
  return useQuery({
    queryKey: ["admin-cashflow", "aging-buckets", ...keyFromFilters(f)],
    queryFn: () =>
      apiFetch<AgingBucketsData>(
        `custom/admin-cashflow/aging-buckets${buildQs(f)}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export function useTopDelayedCustomers(f: AdminCashflowFilters, limit = 10) {
  return useQuery({
    queryKey: [
      "admin-cashflow",
      "top-delayed",
      ...keyFromFilters(f),
      limit,
    ],
    queryFn: () =>
      apiFetch<TopDelayedCustomerRow[]>(
        `custom/admin-cashflow/top-delayed-customers${buildQs(f, { limit })}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}
