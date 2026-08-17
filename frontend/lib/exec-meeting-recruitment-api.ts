"use client"

import { useQuery, keepPreviousData } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total: number }
}

async function apiFetch<T>(path: string, signal?: AbortSignal): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
    signal,
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const EMR_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    // Never retry an auth failure, and never retry a client abort (§43).
    if (/\b401\b|\b403\b/.test(msg) || /abort/i.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Contracts
// ---------------------------------------------------------------------------

export type PeopleRange = "6m" | "12m" | "all" | "custom"

/** `department` is the one filter shared by every panel — it must appear in
 *  every queryKey below, or one panel would scope while another did not. */
export interface EmrFilters {
  department?: string | null
}

export interface EmrSummary {
  active_employees: number
  open_roles: number
  open_vacancies: number
  avg_days_open: number
}

export interface EmrAnnual {
  year: number
  new_hires: number
  offboarding: number
  turnover_rate: number | null
  turnover_basis: string | null
  hires_are_historical: boolean
}

/** `departed_exit_unknown` = inactive with no recorded exit date. Its timeline
 *  must never be drawn through to today. */
export type PersonStatus = "active" | "departed" | "departed_exit_unknown"

export interface EmrPerson {
  id: string
  name: string
  job_title: string | null
  department: string
  hire_date: string
  exit_date: string | null
  status: PersonStatus
}

export interface EmrPeopleFlow {
  rows: EmrPerson[]
  window: { from: string; to: string }
  exit_source: string
}

export interface EmrOpenRole {
  id: string
  name: string
  department: string
  company: string
  opened_on: string
  days_open: number
  vacancies: number
  hired_count: number
  open_vacancies: number
}

export interface EmrOpenRoles {
  rows: EmrOpenRole[]
  open_roles: number
  open_vacancies: number
  avg_days_open: number
}

export interface EmrFilterOptions {
  departments: string[]
  years: number[]
}

export interface EmrFreshness {
  tickets: string | null
  people: string | null
  is_stale: boolean
}

// ---------------------------------------------------------------------------
// URL builder + query keys (§50: the key covers every field serialised here)
// ---------------------------------------------------------------------------

const BASE = "custom/exec-meeting-recruitment"

function qs(params: Record<string, string | number | null | undefined>) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== "") q.append(k, String(v))
  }
  const s = q.toString()
  return s ? `?${s}` : ""
}

const deptKey = (f: EmrFilters) => f.department ?? ""

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useEmrFilterOptions() {
  return useQuery({
    queryKey: ["emr", "filters"],
    queryFn: ({ signal }) => apiFetch<EmrFilterOptions>(`${BASE}/filters`, signal),
    staleTime: 5 * 60_000,
    ...EMR_RETRY,
  })
}

export function useEmrSummary(f: EmrFilters) {
  return useQuery({
    queryKey: ["emr", "summary", deptKey(f)],
    queryFn: ({ signal }) =>
      apiFetch<EmrSummary>(`${BASE}/summary${qs({ department: f.department })}`, signal),
    placeholderData: keepPreviousData,
    ...EMR_RETRY,
  })
}

export function useEmrAnnual(f: EmrFilters, year: number) {
  return useQuery({
    queryKey: ["emr", "annual", deptKey(f), year],
    queryFn: ({ signal }) =>
      apiFetch<EmrAnnual>(`${BASE}/annual${qs({ department: f.department, year })}`, signal),
    placeholderData: keepPreviousData,
    ...EMR_RETRY,
  })
}

export function useEmrPeopleFlow(
  f: EmrFilters,
  range: PeopleRange,
  startDate?: string,
  endDate?: string
) {
  const custom = range === "custom"
  return useQuery({
    queryKey: [
      "emr",
      "people-flow",
      deptKey(f),
      range,
      custom ? startDate ?? "" : "",
      custom ? endDate ?? "" : "",
    ],
    queryFn: ({ signal }) =>
      apiFetch<EmrPeopleFlow>(
        `${BASE}/people-flow${qs({
          department: f.department,
          range,
          start_date: custom ? startDate : null,
          end_date: custom ? endDate : null,
        })}`,
        signal
      ),
    placeholderData: keepPreviousData,
    ...EMR_RETRY,
  })
}

export function useEmrOpenRoles(f: EmrFilters) {
  return useQuery({
    queryKey: ["emr", "open-roles", deptKey(f)],
    queryFn: ({ signal }) =>
      apiFetch<EmrOpenRoles>(`${BASE}/open-roles${qs({ department: f.department })}`, signal),
    placeholderData: keepPreviousData,
    ...EMR_RETRY,
  })
}

export function useEmrFreshness() {
  return useQuery({
    queryKey: ["emr", "freshness"],
    queryFn: ({ signal }) => apiFetch<EmrFreshness>(`${BASE}/freshness`, signal),
    staleTime: 5 * 60_000,
    ...EMR_RETRY,
  })
}

// ---------------------------------------------------------------------------
// Formatters — an em-dash for null, so a missing figure can never read as a
// real zero.
// ---------------------------------------------------------------------------

export function fmtCount(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : n.toLocaleString("en-US")
}

/** Two digits, matching the mockup's "05" / "06" treatment. */
export function fmtKpi(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—"
  return n < 10 ? `0${n}` : n.toLocaleString("en-US")
}

export function fmtPct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(`${iso.slice(0, 10)}T12:00:00`)
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" })
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "?"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}
