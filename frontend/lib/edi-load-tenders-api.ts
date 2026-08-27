"use client"

import { useQuery, keepPreviousData } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: Record<string, unknown>
}

async function apiFetch<T>(path: string, signal?: AbortSignal): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
    signal,
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

/** Unwrap the envelope, failing loudly.
 *
 *  Returning `res.data` directly hands React Query a `T | undefined`, and under
 *  `placeholderData: keepPreviousData` TypeScript then widens `data` to a union
 *  with the placeholder function itself — which fails the strict `next build`
 *  at the call site, not here. Throwing keeps the hook's type exactly `T`, and
 *  surfaces a `success: false` body instead of silently rendering an empty page.
 */
async function apiData<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await apiFetch<T>(path, signal)
  if (!res.success || res.data === undefined) {
    throw new Error(res.error || "Request failed")
  }
  return res.data
}

const EDI_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    // Never retry an auth failure, and never retry a client abort (§43).
    if (/\b401\b|\b403\b/.test(msg) || /abort/i.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Shared filter contract
// ---------------------------------------------------------------------------

export type EdiRange = "mtd" | "l30" | "l90" | "ytd" | "all" | "custom"
export type EdiPurpose = "ORIGINAL" | "CHANGE" | "CANCEL"
export type EdiGrain = "day" | "week" | "month"

export interface EdiFilters {
  range: EdiRange
  startDate?: string
  endDate?: string
  customer?: string[]
  purpose?: EdiPurpose[]
  team?: string[]
}

function ediQs(f: EdiFilters) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  // Repeated keys — the proxy forwards with .append() so multi-select survives
  // (§45). Never comma-join: customer names contain commas.
  for (const v of f.customer ?? []) q.append("customer", v)
  for (const v of f.purpose ?? []) q.append("purpose", v)
  for (const v of f.team ?? []) q.append("team", v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

/** The query key must cover EVERY field ediQs serialises, or a filter change
 *  silently serves a cached response for the previous scope (§50). */
function ediKey(f: EdiFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    (f.customer ?? []).slice().sort().join("|"),
    (f.purpose ?? []).slice().sort().join("|"),
    (f.team ?? []).slice().sort().join("|"),
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface EdiFilterOptions {
  customers: { value: string; label: string; tenders: number }[]
  teams: string[]
  purposes: EdiPurpose[]
  data_floor: string
}

export interface EdiSummary {
  /** Distinct shipments — the business grain. */
  shipments: number
  /** Raw EDI 204 rows. Higher than `shipments` because of CHANGE traffic. */
  tender_messages: number
  reply_errors: number
  created: number
  never_created: number
  cust_cancelled: number
  cust_cancelled_created: number
  we_cancelled: number
  cancel_not_actioned: number
  create_rate: number | null
  cancel_rate: number | null
  reply_error_rate: number | null
  actioned_rate: number | null
  start_date: string
  end_date: string
  /** A team filter can only match created orders, so `never_created` is
   *  structurally 0 under one. The UI must say so rather than render a lie. */
  team_filtered: boolean
}

export interface EdiChartPoint {
  bucket: string
  shipments: number
  created: number
  cust_cancelled: number
  cancel_not_actioned: number
  create_rate: number | null
}

export interface EdiCustomerRow {
  customer_id: string
  customer: string
  shipments: number
  tender_messages: number
  created: number
  never_created: number
  cust_cancelled: number
  we_cancelled: number
  cancel_not_actioned: number
  create_rate: number | null
  cancel_rate: number | null
}

export interface EdiExceptionRow {
  shipment_id: string
  order_id: string
  customer: string
  last_received: string | null
  status: string
  team_id: string | null
  total_charge: number
  margin_amt: number
  ordered_date: string | null
}

export interface EdiTableRow {
  shipment_id: string
  customer: string
  order_id: string | null
  tenders: number
  cancels: number
  created: boolean
  we_cancelled: boolean
  reply_errors: number
  first_received: string | null
  last_received: string | null
  status: string | null
  team_id: string | null
  total_charge: number
}

export interface EdiFreshness {
  received: string | null
  stale_minutes: number | null
  is_stale: boolean
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useEdiFilterOptions() {
  return useQuery({
    queryKey: ["edi-tenders", "filters"],
    queryFn: ({ signal }) =>
      apiData<EdiFilterOptions>("custom/edi-load-tenders/filters", signal),
    staleTime: 10 * 60 * 1000,
    ...EDI_RETRY,
  })
}

export function useEdiFreshness() {
  return useQuery({
    queryKey: ["edi-tenders", "freshness"],
    queryFn: ({ signal }) =>
      apiData<EdiFreshness>("custom/edi-load-tenders/freshness", signal),
    staleTime: 60 * 1000,
    ...EDI_RETRY,
  })
}

export function useEdiSummary(f: EdiFilters) {
  return useQuery({
    queryKey: ["edi-tenders", "summary", ...ediKey(f)],
    queryFn: ({ signal }) =>
      apiData<EdiSummary>(`custom/edi-load-tenders/summary${ediQs(f)}`, signal),
    placeholderData: keepPreviousData,
    ...EDI_RETRY,
  })
}

export function useEdiChart(f: EdiFilters, grain: EdiGrain) {
  return useQuery({
    queryKey: ["edi-tenders", "chart", grain, ...ediKey(f)],
    queryFn: ({ signal }) => {
      const qs = ediQs(f)
      const sep = qs ? "&" : "?"
      return apiData<EdiChartPoint[]>(
        `custom/edi-load-tenders/chart${qs}${sep}grain=${grain}`,
        signal,
      )
    },
    placeholderData: keepPreviousData,
    ...EDI_RETRY,
  })
}

export function useEdiByCustomer(f: EdiFilters) {
  return useQuery({
    queryKey: ["edi-tenders", "by-customer", ...ediKey(f)],
    queryFn: ({ signal }) =>
      apiData<EdiCustomerRow[]>(
        `custom/edi-load-tenders/by-customer${ediQs(f)}`,
        signal,
      ),
    placeholderData: keepPreviousData,
    ...EDI_RETRY,
  })
}

export function useEdiExceptions(f: EdiFilters, liveOnly: boolean) {
  return useQuery({
    queryKey: ["edi-tenders", "exceptions", liveOnly, ...ediKey(f)],
    queryFn: async ({ signal }) => {
      const qs = ediQs(f)
      const sep = qs ? "&" : "?"
      const r = await apiFetch<EdiExceptionRow[]>(
        `custom/edi-load-tenders/exceptions${qs}${sep}live_only=${liveOnly}`,
        signal,
      )
      return {
        rows: r.data ?? [],
        totalCharge: Number(r.meta?.total_charge ?? 0),
        truncated: Boolean(r.meta?.truncated),
      }
    },
    placeholderData: keepPreviousData,
    ...EDI_RETRY,
  })
}

export function useEdiTable(f: EdiFilters) {
  return useQuery({
    queryKey: ["edi-tenders", "table", ...ediKey(f)],
    queryFn: async ({ signal }) => {
      const r = await apiFetch<EdiTableRow[]>(
        `custom/edi-load-tenders/table${ediQs(f)}`,
        signal,
      )
      return { rows: r.data ?? [], truncated: Boolean(r.meta?.truncated) }
    },
    placeholderData: keepPreviousData,
    ...EDI_RETRY,
  })
}
