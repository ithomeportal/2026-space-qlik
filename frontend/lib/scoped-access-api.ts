"use client"

import { useQuery } from "@tanstack/react-query"

/**
 * Shared React Query layer for the scope-locked "Access Log Doors" reports
 * (OPS / Pricing / Carrier Procurement — Bruno PDF 2026-08-12).
 *
 * Every hook takes the report `slug` as its first argument and threads it into
 * both the URL and the `queryKey`, so the three reports never share a cache
 * entry. Department is deliberately absent from the filter contract — it's
 * locked server-side by the router's `gate_sql` and can't be widened from here.
 *
 * Backed by `backend/app/routers/scoped_access_doors.py`.
 */

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: {
    total?: number
    page?: number
    limit?: number
    window?: { start: string; end: string }
  }
}

async function apiFetch<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

// Never retry an auth failure — a 403 here means "no TagRole", not "flaky".
const SCOPED_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Slugs — must match `report_key` in scoped_access_doors.py exactly
// ---------------------------------------------------------------------------

export type ScopedAccessSlug =
  | "ops-access-doors"
  | "pricing-access-doors"
  | "carrier-procurement-access-doors"

// ---------------------------------------------------------------------------
// Shared filter contract (Department is locked server-side — not exposed)
// ---------------------------------------------------------------------------

export interface ScopedAccessFilters {
  startDate: string // YYYY-MM-DD
  endDate: string // YYYY-MM-DD
  name?: string
  jobTitle?: string
}

function scopedQs(
  f: Partial<ScopedAccessFilters>,
  extra?: Record<string, string>,
) {
  const q = new URLSearchParams()
  if (f.startDate) q.set("start_date", f.startDate)
  if (f.endDate) q.set("end_date", f.endDate)
  if (f.name) q.set("name", f.name)
  if (f.jobTitle) q.set("job_title", f.jobTitle)
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ScopedAccessFilterOptions {
  job_titles: string[]
  names: string[]
  today: string
}

export interface ScopedAccessKpis {
  log_in_employees: number
  not_on_time_ref: number
  on_time: number
  out_of_time: number
  total_rows: number
  pct_on_time: number | null
  pct_out_of_time: number | null
  window: { start: string; end: string }
}

export interface ScopedAccessRow {
  full_name: string
  event_date: string
  event_time: string | null
  job_title: string | null
  department: string | null
  on_time_reference: string | null
  check_minutes: number | null
}

export interface ScopedAccessTrendPoint {
  event_date: string
  on_time: number
  out_of_time: number
}

export interface ScopedAccessJobTitleBar {
  job_title: string
  on_time: number
  out_of_time: number
  unscored: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useScopedAccessFilters(slug: ScopedAccessSlug) {
  return useQuery({
    ...SCOPED_RETRY,
    queryKey: [slug, "filters"],
    queryFn: () =>
      apiFetch<ScopedAccessFilterOptions>(`custom/${slug}/filters`),
    staleTime: 30 * 60 * 1000,
  })
}

export function useScopedAccessKpis(
  slug: ScopedAccessSlug,
  f: ScopedAccessFilters,
  enabled = true,
) {
  return useQuery({
    ...SCOPED_RETRY,
    enabled,
    queryKey: [slug, "kpis", f],
    queryFn: () =>
      apiFetch<ScopedAccessKpis>(`custom/${slug}/kpis${scopedQs(f)}`),
  })
}

export function useScopedAccessRows(
  slug: ScopedAccessSlug,
  f: ScopedAccessFilters & { sort?: string; page?: number; limit?: number },
  enabled = true,
) {
  return useQuery({
    ...SCOPED_RETRY,
    enabled,
    queryKey: [slug, "rows", f],
    queryFn: () =>
      apiFetch<ScopedAccessRow[]>(
        `custom/${slug}/rows${scopedQs(f, {
          ...(f.sort ? { sort: f.sort } : {}),
          ...(f.page ? { page: String(f.page) } : {}),
          ...(f.limit ? { limit: String(f.limit) } : {}),
        })}`,
      ),
  })
}

// Rolling 30d ignores the user-selected date filter but stays inside the
// server-side scope gate.
export function useScopedAccessTrend30d(
  slug: ScopedAccessSlug,
  f: Pick<ScopedAccessFilters, "name" | "jobTitle">,
  enabled = true,
) {
  return useQuery({
    ...SCOPED_RETRY,
    enabled,
    queryKey: [slug, "trend-30d", f],
    queryFn: () =>
      apiFetch<ScopedAccessTrendPoint[]>(
        `custom/${slug}/trend-30d${scopedQs({
          startDate: "",
          endDate: "",
          name: f.name,
          jobTitle: f.jobTitle,
        })}`,
      ),
    staleTime: 5 * 60 * 1000,
  })
}

export function useScopedAccessByJobTitle(
  slug: ScopedAccessSlug,
  f: Omit<ScopedAccessFilters, "jobTitle">,
  enabled = true,
) {
  return useQuery({
    ...SCOPED_RETRY,
    enabled,
    queryKey: [slug, "by-job-title", f],
    queryFn: () =>
      apiFetch<ScopedAccessJobTitleBar[]>(
        `custom/${slug}/by-job-title${scopedQs(f)}`,
      ),
  })
}

// ---------------------------------------------------------------------------
// Formatters (kept identical to hr-access-api / dfw-access-api so the five
// Access Log Doors reports render the same numbers the same way)
// ---------------------------------------------------------------------------

export const INT_COUNT = new Intl.NumberFormat("en-US")
export const PCT1 = new Intl.NumberFormat("en-US", {
  style: "percent",
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
})

export const fmtCount = (v?: number | null) =>
  v === null || v === undefined ? "—" : INT_COUNT.format(Math.round(Number(v)))

export const fmtPct = (v?: number | null) =>
  v === null || v === undefined || Number.isNaN(Number(v))
    ? "—"
    : PCT1.format(Number(v))

export function fmtEventTime(iso: string | null): string {
  if (!iso) return "—"
  const m = iso.match(/T(\d{2}):(\d{2}):(\d{2})/)
  if (!m) return iso
  const h24 = parseInt(m[1], 10)
  const h12 = ((h24 + 11) % 12) + 1
  const ampm = h24 >= 12 ? "PM" : "AM"
  return `${h12}:${m[2]}:${m[3]} ${ampm}`
}

export function fmtCheckMinutes(v: number | null): string {
  if (v === null || v === undefined) return ""
  if (v > 0) return `+${v} min`
  return `${v} min`
}

export function checkColorClass(v: number | null): string {
  if (v === null || v === undefined) return "text-[#6B7280]"
  if (v >= 0) return "text-[#047857] font-semibold"
  if (v >= -14) return "text-[#D97706]"
  if (v >= -59) return "text-[#EA580C]"
  return "text-[#DC2626] font-semibold"
}

export function fmtDate(iso: string): string {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return iso
  return `${parseInt(m[2], 10)}/${parseInt(m[3], 10)}/${m[1]}`
}

export function fmtExpectedTime(iso: string | null): string {
  if (!iso) return "—"
  return `${fmtDate(iso.substring(0, 10))} ${fmtEventTime(iso)}`
}
