"use client"

import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { parseLocalDate } from "@/lib/local-date"

// Collections Settlement Forecast (request 2026-10-27). Definitions live in
// backend/app/services/cash_forecast*.py — this file only fetches and formats.

const BASE = "custom/collections-settlement-forecast"

export interface Freshness {
  ar_snapshot_date: string | null
  latest_receipt_gl_date: string | null
  receipts_checked_at: string | null
  settlements_snapshot_date: string | null
  ap_snapshot_date: string | null
  shipped_as_of: string | null
  failed_sources: string[]
  now_ct: string
}

interface Envelope<T, M = object> {
  success: boolean
  data: T
  error?: string
  meta: { freshness: Freshness } & M
}

export interface ThisWeek {
  week_start: string
  week_end: string
  company: string
  cash_in: {
    collected_so_far: number | null
    receipts_included: boolean
    remaining_due: number | null
    due_customers: number | null
    remaining_past_due: number | null
    committed: number | null
    expected: number | null
    still_expected: number | null
    typical_week: number | null
  }
  cash_out: {
    settlements: number | null
    settlement_pay_dates: string[]
    ap_due: number | null
    ap_past_due_older: number | null
    ap_undated: number | null
    total: number | null
  }
  net: { committed: number | null; expected: number | null }
}

export interface WeekRow {
  week_offset: number
  week_start: string
  week_end: string
  cash_in: number | null
  in_run_rate: number | null
  in_due_terms: number | null
  settlements: number | null
  out_basis: "scheduled" | "run-rate" | null
  ap: number | null
  cash_out: number | null
  net: number | null
  cumulative: number | null
}

export interface WeeksMeta {
  this_week_committed_in: number | null
  typical_week: number | null
  settlements_unplaced: number | null
}

export interface CustomerRow {
  customer_id: string
  customer_name: string
  avg_pay_days: number | null
  pay_days_known: boolean | null
  open: number
  past_due: number
  weeks: number[]
  run_rate_weeks: number
  expected_5w: number
}

export interface AccuracyRow {
  week_start: string
  week_end: string
  complete: boolean
  forecast_in: number | null
  forecast_in_committed: number | null
  forecast_in_prior_week: number | null
  actual_in: number | null
  variance_in: number | null
  forecast_settlements: number | null
  actual_settlements: number | null
  variance_settlements: number | null
  forecast_taken: string | null
}

async function apiGet<T>(section: string): Promise<T> {
  const res = await fetch(`/api/proxy/${BASE}/${section}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) {
    let detail = ""
    try {
      detail = (await res.json())?.detail ?? ""
    } catch {
      detail = ""
    }
    throw new Error(`API error: ${res.status}${detail ? ` — ${detail}` : ""}`)
  }
  return res.json()
}

// Never retry an auth refusal or a client abort (§43).
const RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b|abort/i.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

function useSection<T>(section: string) {
  return useQuery({
    queryKey: ["collections-settlement-forecast", section],
    queryFn: () => apiGet<T>(section),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    ...RETRY,
  })
}

export const useThisWeek = () => useSection<Envelope<ThisWeek>>("this-week")
export const useWeeks = () => useSection<Envelope<WeekRow[], WeeksMeta>>("weeks")
export const useByCustomer = () => useSection<Envelope<CustomerRow[], { total: number }>>("by-customer")
export const useAccuracy = () =>
  useSection<Envelope<AccuracyRow[], { first_snapshot: string | null }>>("accuracy")

// ---------------------------------------------------------------- formatting

const USD0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })
const USD_COMPACT = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 2,
})

/** "—" for unknown — a source that failed must never read as $0 (§93). */
export const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : USD0.format(v)

export const fmtUsdCompact = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : USD_COMPACT.format(v)

/** "Oct 24" from a date-only string, parsed as a LOCAL date (§116). */
export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return "—"
  return parseLocalDate(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

export const weekLabel = (start: string, end: string) => `${fmtDay(start)} – ${fmtDay(end)}`

export const signTone = (v: number | null | undefined) =>
  v === null || v === undefined ? "text-[#6B7280]" : v < 0 ? "text-[#B91C1C]" : "text-[#047857]"
