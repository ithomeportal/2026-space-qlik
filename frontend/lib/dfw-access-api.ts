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

const DFW_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Shared filter contract (Department is locked server-side — not exposed)
// ---------------------------------------------------------------------------

export interface DfwAccessFilters {
  startDate: string // YYYY-MM-DD
  endDate: string // YYYY-MM-DD
  name?: string
  jobTitle?: string
}

function dfwQs(f: Partial<DfwAccessFilters>, extra?: Record<string, string>) {
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

export interface DfwAccessFilterOptions {
  job_titles: string[]
  names: string[]
  today: string
}

export interface DfwAccessKpis {
  log_in_employees: number
  not_on_time_ref: number
  on_time: number
  out_of_time: number
  total_rows: number
  pct_on_time: number | null
  pct_out_of_time: number | null
  window: { start: string; end: string }
}

export interface DfwAccessRow {
  full_name: string
  event_date: string
  event_time: string | null
  job_title: string | null
  department: string | null
  on_time_reference: string | null
  check_minutes: number | null
}

export interface DfwAccessTrendPoint {
  event_date: string
  on_time: number
  out_of_time: number
}

export interface DfwAccessJobTitleBar {
  job_title: string
  on_time: number
  out_of_time: number
  unscored: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useDfwFilters() {
  return useQuery({
    ...DFW_RETRY,
    queryKey: ["dfw-access", "filters"],
    queryFn: () =>
      apiFetch<DfwAccessFilterOptions>("custom/dfw-access-doors/filters"),
    staleTime: 30 * 60 * 1000,
  })
}

export function useDfwKpis(f: DfwAccessFilters, enabled = true) {
  return useQuery({
    ...DFW_RETRY,
    enabled,
    queryKey: ["dfw-access", "kpis", f],
    queryFn: () =>
      apiFetch<DfwAccessKpis>(`custom/dfw-access-doors/kpis${dfwQs(f)}`),
  })
}

export function useDfwRows(
  f: DfwAccessFilters & { sort?: string; page?: number; limit?: number },
  enabled = true,
) {
  return useQuery({
    ...DFW_RETRY,
    enabled,
    queryKey: ["dfw-access", "rows", f],
    queryFn: () =>
      apiFetch<DfwAccessRow[]>(
        `custom/dfw-access-doors/rows${dfwQs(f, {
          ...(f.sort ? { sort: f.sort } : {}),
          ...(f.page ? { page: String(f.page) } : {}),
          ...(f.limit ? { limit: String(f.limit) } : {}),
        })}`,
      ),
  })
}

// Trend rolling 30d ignores the user-selected date filter but stays locked
// to Operations (DFW) (server-side gate).
export function useDfwTrend30d(
  f: Pick<DfwAccessFilters, "name" | "jobTitle">,
  enabled = true,
) {
  return useQuery({
    ...DFW_RETRY,
    enabled,
    queryKey: ["dfw-access", "trend-30d", f],
    queryFn: () =>
      apiFetch<DfwAccessTrendPoint[]>(
        `custom/dfw-access-doors/trend-30d${dfwQs({
          startDate: "",
          endDate: "",
          name: f.name,
          jobTitle: f.jobTitle,
        })}`,
      ),
    staleTime: 5 * 60 * 1000,
  })
}

export function useDfwByJobTitle(
  f: Omit<DfwAccessFilters, "jobTitle">,
  enabled = true,
) {
  return useQuery({
    ...DFW_RETRY,
    enabled,
    queryKey: ["dfw-access", "by-job-title", f],
    queryFn: () =>
      apiFetch<DfwAccessJobTitleBar[]>(
        `custom/dfw-access-doors/by-job-title${dfwQs(f)}`,
      ),
  })
}

// ---------------------------------------------------------------------------
// Formatters (kept identical to hr-access-api so visuals match)
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
