"use client"

import { createContext, createElement, useContext, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total?: number; page?: number; limit?: number; cached?: boolean }
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
// API prefix context — default points at the cross-team
// `/custom/ops-customer-score` router. Per-team pages
// (e.g. /reports/corp-t1-customer-score) wrap their content in
// <OcsApiProvider prefix="custom/ops-customer-score-t1"> so every hook below
// transparently hits the team-locked endpoints. The prefix is also baked into
// every queryKey so the 4 team copies cache independently of each other and of
// the cross-team report.
// ---------------------------------------------------------------------------

const DEFAULT_PREFIX = "custom/ops-customer-score"

const ApiPrefixContext = createContext<string>(DEFAULT_PREFIX)

export function OcsApiProvider({
  prefix,
  children,
}: {
  prefix: string
  children: ReactNode
}) {
  return createElement(ApiPrefixContext.Provider, { value: prefix }, children)
}

function useApiPrefix() {
  return useContext(ApiPrefixContext)
}

// ---------------------------------------------------------------------------
// Filter contract
// ---------------------------------------------------------------------------

export type OcsRange = "mtd" | "last_month" | "ytd" | "custom"
export type OcsDivision = "All" | "CORP" | "DFW"

export interface OcsFilters {
  range: OcsRange
  startDate?: string
  endDate?: string
  division: OcsDivision
  teams?: string[]
  companies?: string[]
  subTeams?: string[]
  customer?: string
  carrier?: string
}

function applyScopeQs(q: URLSearchParams, f: OcsFilters | Partial<OcsFilters>) {
  if (f.division && f.division !== "All") q.set("division", f.division)
  if (f.teams && f.teams.length) q.set("teams", f.teams.join(","))
  if (f.companies && f.companies.length) q.set("companies", f.companies.join(","))
  if (f.subTeams && f.subTeams.length) q.set("sub_teams", f.subTeams.join(","))
  if (f.customer) q.set("customer", f.customer)
  if (f.carrier) q.set("carrier", f.carrier)
}

function qs(f: OcsFilters, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  applyScopeQs(q, f)
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

function pinnedQs(f: OcsFilters) {
  // Pinned panels ignore the date filter — only scope params travel.
  const q = new URLSearchParams()
  applyScopeQs(q, f)
  const s = q.toString()
  return s ? `?${s}` : ""
}

function key(f: OcsFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    f.division,
    (f.teams ?? []).slice().sort().join(","),
    (f.companies ?? []).slice().sort().join(","),
    (f.subTeams ?? []).slice().sort().join(","),
    f.customer ?? "",
    f.carrier ?? "",
  ]
}

function pinnedKey(f: OcsFilters) {
  return [
    f.division,
    (f.teams ?? []).slice().sort().join(","),
    (f.companies ?? []).slice().sort().join(","),
    (f.subTeams ?? []).slice().sort().join(","),
    f.customer ?? "",
    f.carrier ?? "",
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OcsFilterOptions {
  divisions: string[]
  teams: string[]
  corp_teams: string[]
  dfw_team: string
  dfw_sub_teams: string[]
  companies: string[]
  customers: string[]
  carriers: string[]
  year_start: string
  year_end: string
}

export interface OcsKpi {
  orders: number
  fail: number
  pct_on_time: number | null
}

export interface OcsRollingPoint {
  bucket: string | null
  orders: number
  fail: number
  pct_on_time: number | null
  iso_year?: number
  iso_week?: number
  label?: string
}

export interface OcsPinned {
  kpi_month: OcsKpi
  kpi_quarter: OcsKpi
  kpi_year: OcsKpi
  rolling_12m: OcsRollingPoint[]
  rolling_10w: OcsRollingPoint[]
  windows: {
    month_start: string
    quarter_start: string
    year_start: string
    today: string
    rolling_12m_start: string
    rolling_10w_start: string
  }
}

export interface OcsTeamRow {
  team_id: string | null
  orders: number
  fail: number
  pct_on_time: number | null
}

export interface OcsCustomerRow {
  customer_name: string | null
  orders: number
  fail: number
  pct_on_time: number | null
}

export interface OcsDelayRow {
  edi_standard_code: string | null
  fail: number
}

export interface OcsOverview {
  kpi: OcsKpi
  by_team: OcsTeamRow[]
  by_customer: OcsCustomerRow[]
  by_delay: OcsDelayRow[]
  window: { start: string; end: string }
  teams_applied: string[]
  companies_applied: string[]
  sub_teams_applied: string[] | null
}

export interface OcsLaneRow {
  customer_name: string | null
  origin: string | null
  destination: string | null
  orders: number
  fail: number
  pct_on_time: number | null
}

export interface OcsDetail {
  kpi: OcsKpi
  our_fault_kpi: { fail: number; pct_on_time: number | null }
  not_fault_kpi: { fail: number; pct_on_time: number | null }
  by_customer: OcsCustomerRow[]
  by_lane: OcsLaneRow[]
  window: { start: string; end: string }
  teams_applied: string[]
  companies_applied: string[]
  sub_teams_applied: string[] | null
}

export interface OcsFaultRow {
  id: string
  team_id: string | null
  customer_name: string | null
  actual_arrival: string | null
  sched_late: string | null
  edi_standard_code: string | null
  edi_code_descr: string | null
  dsp_comment: string | null
  payee_name: string | null
  entered_user_id: string | null
}

export interface OcsFreshness {
  last_updated: string | null
  last_pu: string | null
  last_del: string | null
  rows_in_scope: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useOcsFilters(f: Partial<OcsFilters>) {
  const prefix = useApiPrefix()
  const q = new URLSearchParams()
  applyScopeQs(q, f)
  const queryString = q.toString()
  return useQuery({
    queryKey: [
      prefix,
      "ops-customer-score",
      "filters",
      f.division ?? "All",
      (f.teams ?? []).slice().sort().join(","),
      (f.companies ?? []).slice().sort().join(","),
      (f.subTeams ?? []).slice().sort().join(","),
      f.customer ?? "",
      f.carrier ?? "",
    ],
    queryFn: () =>
      apiFetch<OcsFilterOptions>(
        `${prefix}/filters${queryString ? "?" + queryString : ""}`,
      ),
    staleTime: 5 * 60_000,
    ...RETRY,
  })
}

export function useOcsPuPinned(f: OcsFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "ops-customer-score", "pu-pinned", ...pinnedKey(f)],
    queryFn: () => apiFetch<OcsPinned>(`${prefix}/pu/pinned${pinnedQs(f)}`),
    staleTime: 10 * 60_000,
    ...RETRY,
  })
}

export function useOcsDelPinned(f: OcsFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "ops-customer-score", "del-pinned", ...pinnedKey(f)],
    queryFn: () => apiFetch<OcsPinned>(`${prefix}/del/pinned${pinnedQs(f)}`),
    staleTime: 10 * 60_000,
    ...RETRY,
  })
}

export function useOcsPuOverview(f: OcsFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "ops-customer-score", "pu-overview", ...key(f)],
    queryFn: () => apiFetch<OcsOverview>(`${prefix}/pu/overview${qs(f)}`),
    ...RETRY,
  })
}

export function useOcsDelOverview(f: OcsFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "ops-customer-score", "del-overview", ...key(f)],
    queryFn: () => apiFetch<OcsOverview>(`${prefix}/del/overview${qs(f)}`),
    ...RETRY,
  })
}

export function useOcsPuDetail(f: OcsFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "ops-customer-score", "pu-detail", ...key(f)],
    queryFn: () => apiFetch<OcsDetail>(`${prefix}/pu/detail${qs(f)}`),
    ...RETRY,
  })
}

export function useOcsDelDetail(f: OcsFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "ops-customer-score", "del-detail", ...key(f)],
    queryFn: () => apiFetch<OcsDetail>(`${prefix}/del/detail${qs(f)}`),
    ...RETRY,
  })
}

export function useOcsFaultRows(
  f: OcsFilters,
  side: "pu" | "del",
  fault: "our" | "not",
  page: number,
  limit: number,
) {
  const prefix = useApiPrefix()
  const path =
    side === "pu"
      ? fault === "our"
        ? "pu/our-fault"
        : "pu/not-our-fault"
      : fault === "our"
        ? "del/our-fault"
        : "del/not-our-fault"
  return useQuery({
    queryKey: [prefix, "ops-customer-score", "fault", side, fault, page, limit, ...key(f)],
    queryFn: () =>
      apiFetch<OcsFaultRow[]>(
        `${prefix}/${path}${qs(f, {
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    ...RETRY,
  })
}

export function useOcsFreshness() {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "ops-customer-score", "freshness"],
    queryFn: () => apiFetch<OcsFreshness>(`${prefix}/freshness`),
    staleTime: 60_000,
    ...RETRY,
  })
}
