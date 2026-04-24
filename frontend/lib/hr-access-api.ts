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

// Cap retries at 2 so failures surface in ~10s instead of ~60s (same pattern
// as xray-api and ceo-api).
const HR_RETRY = {
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

export interface HrFilters {
  startDate: string // YYYY-MM-DD
  endDate: string // YYYY-MM-DD
  department?: string
  name?: string
  jobTitle?: string
}

function hrQs(f: Partial<HrFilters>, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  if (f.startDate) q.set("start_date", f.startDate)
  if (f.endDate) q.set("end_date", f.endDate)
  if (f.department) q.set("department", f.department)
  if (f.name) q.set("name", f.name)
  if (f.jobTitle) q.set("job_title", f.jobTitle)
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HrFilterOptions {
  departments: string[]
  job_titles: string[]
  names: string[]
  today: string
}

export interface HrKpis {
  log_in_employees: number
  not_on_time_ref: number
  on_time: number
  out_of_time: number
  total_rows: number
  pct_on_time: number | null
  pct_out_of_time: number | null
  window: { start: string; end: string }
}

export interface HrRow {
  full_name: string
  event_date: string
  event_time: string | null
  job_title: string | null
  department: string | null
  on_time_reference: string | null
  check_minutes: number | null
}

export interface HrTrendPoint {
  event_date: string
  on_time: number
  out_of_time: number
}

export interface HrDeptBar {
  department: string
  on_time: number
  out_of_time: number
  unscored: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useHrFilters() {
  return useQuery({
    ...HR_RETRY,
    queryKey: ["hr-access", "filters"],
    queryFn: () => apiFetch<HrFilterOptions>("custom/hr-access-doors/filters"),
    staleTime: 30 * 60 * 1000,
  })
}

export function useHrKpis(f: HrFilters, enabled = true) {
  return useQuery({
    ...HR_RETRY,
    enabled,
    queryKey: ["hr-access", "kpis", f],
    queryFn: () => apiFetch<HrKpis>(`custom/hr-access-doors/kpis${hrQs(f)}`),
  })
}

export function useHrRows(
  f: HrFilters & { sort?: string; page?: number; limit?: number },
  enabled = true,
) {
  return useQuery({
    ...HR_RETRY,
    enabled,
    queryKey: ["hr-access", "rows", f],
    queryFn: () =>
      apiFetch<HrRow[]>(
        `custom/hr-access-doors/rows${hrQs(f, {
          ...(f.sort ? { sort: f.sort } : {}),
          ...(f.page ? { page: String(f.page) } : {}),
          ...(f.limit ? { limit: String(f.limit) } : {}),
        })}`,
      ),
  })
}

// Trend + by-department both IGNORE the primary date filter (rolling 30d for
// trend, explicit window for dept). Both ignore the department filter too.
export function useHrTrend30d(
  f: Pick<HrFilters, "name" | "jobTitle">,
  enabled = true,
) {
  return useQuery({
    ...HR_RETRY,
    enabled,
    queryKey: ["hr-access", "trend-30d", f],
    queryFn: () =>
      apiFetch<HrTrendPoint[]>(
        `custom/hr-access-doors/trend-30d${hrQs({
          startDate: "",
          endDate: "",
          name: f.name,
          jobTitle: f.jobTitle,
        })}`,
      ),
    staleTime: 5 * 60 * 1000,
  })
}

export function useHrByDepartment(
  f: Omit<HrFilters, "department">,
  enabled = true,
) {
  return useQuery({
    ...HR_RETRY,
    enabled,
    queryKey: ["hr-access", "by-department", f],
    queryFn: () =>
      apiFetch<HrDeptBar[]>(
        `custom/hr-access-doors/by-department${hrQs(f)}`,
      ),
  })
}

// ---------------------------------------------------------------------------
// Formatters
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

/** Format a `YYYY-MM-DDTHH:MM:SS` event_time as `HH:MM:SS AM/PM`. */
export function fmtEventTime(iso: string | null): string {
  if (!iso) return "—"
  // ISO from backend looks like `2026-04-24T08:43:17` (no tz). Strip and
  // reformat so we don't accidentally shift hours through the Date object.
  const m = iso.match(/T(\d{2}):(\d{2}):(\d{2})/)
  if (!m) return iso
  const h24 = parseInt(m[1], 10)
  const h12 = ((h24 + 11) % 12) + 1
  const ampm = h24 >= 12 ? "PM" : "AM"
  return `${h12}:${m[2]}:${m[3]} ${ampm}`
}

/** Format `check_minutes` ± value like Qlik's `-733 min` / `+12 min`. */
export function fmtCheckMinutes(v: number | null): string {
  if (v === null || v === undefined) return ""
  if (v > 0) return `+${v} min`
  return `${v} min`
}

/** Color class for the Check column cell. */
export function checkColorClass(v: number | null): string {
  if (v === null || v === undefined) return "text-[#6B7280]"
  if (v >= 0) return "text-[#047857] font-semibold"
  if (v >= -14) return "text-[#D97706]"
  if (v >= -59) return "text-[#EA580C]"
  return "text-[#DC2626] font-semibold"
}

export function fmtDate(iso: string): string {
  // 2026-04-21 → 4/21/2026 (matches Bruno's Qlik display)
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return iso
  return `${parseInt(m[2], 10)}/${parseInt(m[3], 10)}/${m[1]}`
}

export function fmtExpectedTime(iso: string | null): string {
  if (!iso) return "—"
  return `${fmtDate(iso.substring(0, 10))} ${fmtEventTime(iso)}`
}
