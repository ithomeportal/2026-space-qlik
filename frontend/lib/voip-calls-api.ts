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
    cached?: boolean
    days?: string[]
  }
}

async function apiFetch<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const VOIP_RETRY = {
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

export type VoipRange =
  | "today"
  | "wtd"
  | "last_7d"
  | "mtd"
  | "last_month"
  | "ytd"
  | "custom"

export type VoipDirection = "ALL" | "INBOUND" | "OUTBOUND" | "INTRA_PBX"

export interface VoipFilters {
  range: VoipRange
  startDate?: string // YYYY-MM-DD (only used when range === 'custom')
  endDate?: string
  direction: VoipDirection
  q?: string
}

function voipQs(f: VoipFilters, extra?: Record<string, string>): string {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  if (f.direction && f.direction !== "ALL") q.set("direction", f.direction)
  if (f.q && f.q.trim()) q.set("q", f.q.trim())
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface VoipSummary {
  total_calls: number
  unique_users: number
  avg_duration_min: number
  total_duration_min: number
  inbound: number
  outbound: number
  intra_pbx: number
  pct_inbound: number | null
  pct_outbound: number | null
  pct_intra_pbx: number | null
  short_calls: number
  pct_short_calls: number | null
}

export interface VoipDirectionPoint {
  direction: string
  count: number
}

export interface VoipTrendPoint {
  day: string
  count: number
  avg_duration_min: number | null
}

export interface VoipHourPoint {
  hour: number
  count: number
}

export interface VoipHeatPoint {
  dow: number // 0=Mon
  hour: number
  count: number
}

export interface VoipUser {
  username: string
  calls: number
  minutes: number
}

export interface VoipDetailRow {
  call_id: string | null
  type: string | null
  identif: string | null
  call_details: string | null
  start: string | null
  end: string | null
  duration_min: number | null
  username: string | null
}

// ---------------------------------------------------------------------------
// Hooks (one query per panel, all keyed on the same filter object so the
// cache is sliced cleanly by filter combination).
// ---------------------------------------------------------------------------

export function useVoipSummary(f: VoipFilters) {
  return useQuery({
    ...VOIP_RETRY,
    queryKey: ["voip-calls", "summary", f],
    queryFn: () => apiFetch<VoipSummary>(`custom/voip-calls/summary${voipQs(f)}`),
  })
}

export function useVoipByDirection(f: VoipFilters) {
  return useQuery({
    ...VOIP_RETRY,
    queryKey: ["voip-calls", "by-direction", f],
    queryFn: () =>
      apiFetch<VoipDirectionPoint[]>(`custom/voip-calls/by-direction${voipQs(f)}`),
  })
}

export function useVoipTrend(f: VoipFilters) {
  return useQuery({
    ...VOIP_RETRY,
    queryKey: ["voip-calls", "trend-daily", f],
    queryFn: () =>
      apiFetch<VoipTrendPoint[]>(`custom/voip-calls/trend-daily${voipQs(f)}`),
    staleTime: 60 * 1000, // matches backend in-process TTL
  })
}

export function useVoipByHour(f: VoipFilters) {
  return useQuery({
    ...VOIP_RETRY,
    queryKey: ["voip-calls", "by-hour", f],
    queryFn: () => apiFetch<VoipHourPoint[]>(`custom/voip-calls/by-hour${voipQs(f)}`),
  })
}

export function useVoipHeatmap(f: VoipFilters) {
  return useQuery({
    ...VOIP_RETRY,
    queryKey: ["voip-calls", "heatmap", f],
    queryFn: () => apiFetch<VoipHeatPoint[]>(`custom/voip-calls/heatmap${voipQs(f)}`),
  })
}

export function useVoipTopUsers(f: VoipFilters, limit = 20) {
  return useQuery({
    ...VOIP_RETRY,
    queryKey: ["voip-calls", "top-users", f, limit],
    queryFn: () =>
      apiFetch<{ by_count: VoipUser[]; by_talk_time: VoipUser[] }>(
        `custom/voip-calls/top-users${voipQs(f, { limit: String(limit) })}`,
      ),
  })
}

export function useVoipDetail(
  f: VoipFilters,
  page: number,
  limit: number,
  sort: string,
) {
  return useQuery({
    ...VOIP_RETRY,
    queryKey: ["voip-calls", "detail", f, page, limit, sort],
    queryFn: () =>
      apiFetch<VoipDetailRow[]>(
        `custom/voip-calls/detail${voipQs(f, {
          page: String(page),
          limit: String(limit),
          sort,
        })}`,
      ),
  })
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

export const INT = new Intl.NumberFormat("en-US")
export const DEC1 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
})
export const PCT1 = new Intl.NumberFormat("en-US", {
  style: "percent",
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
})

export const fmtInt = (v?: number | null) =>
  v === null || v === undefined ? "—" : INT.format(Math.round(Number(v)))

export const fmtMin = (v?: number | null) =>
  v === null || v === undefined ? "—" : `${DEC1.format(Number(v))} min`

export const fmtHours = (v?: number | null) => {
  if (v === null || v === undefined) return "—"
  const hours = Number(v) / 60
  if (hours >= 100) return `${INT.format(Math.round(hours))} h`
  return `${DEC1.format(hours)} h`
}

export const fmtPct = (v?: number | null) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : PCT1.format(Number(v))

/** Render a Postgres timestamp string `YYYY-MM-DDTHH:MM:SS` as `M/D/YYYY h:mm:ss AM/PM`. */
export function fmtDateTime(iso: string | null): string {
  if (!iso) return "—"
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/)
  if (!m) return iso
  const h24 = parseInt(m[4], 10)
  const h12 = ((h24 + 11) % 12) + 1
  const ampm = h24 >= 12 ? "PM" : "AM"
  return `${parseInt(m[2], 10)}/${parseInt(m[3], 10)}/${m[1]} ${h12}:${m[5]}:${m[6]} ${ampm}`
}

export function fmtIsoDay(iso: string): string {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return iso
  return `${parseInt(m[2], 10)}/${parseInt(m[3], 10)}`
}
