"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { mutationErrorToast } from "@/lib/mutation-error"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
}

async function apiFetch<T>(
  path: string,
  init?: RequestInit,
): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  if (!res.ok) {
    let msg = `API error: ${res.status}`
    try {
      const body = await res.json()
      if (body?.error || body?.detail) msg = body.error || body.detail
    } catch {
      /* ignore */
    }
    throw new Error(msg)
  }
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
// Date filter — YTD / MTD / WTD (Mon-anchored) / Custom (Bruno R2).
// Bounds are computed in JS so every tab passes the same
// `range=custom&start_date=…&end_date=…` shape to the backend (the parent
// ops-customer-score / xray-dfw endpoints don't know a `wtd` keyword, so we
// resolve it client-side and send an explicit window).
// ---------------------------------------------------------------------------

export type KamRange = "ytd" | "mtd" | "wtd" | "custom"
export interface KamBounds {
  start: string
  end: string
}

const KAM_YEAR_START = "2026-01-01"

function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

export function kamBounds(
  range: KamRange,
  customStart?: string,
  customEnd?: string,
): KamBounds {
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const todayIso = isoDay(today)
  if (range === "ytd") return { start: KAM_YEAR_START, end: todayIso }
  if (range === "mtd")
    return { start: isoDay(new Date(today.getFullYear(), today.getMonth(), 1)), end: todayIso }
  if (range === "wtd") {
    const daysFromMon = (today.getDay() + 6) % 7 // Mon-anchored
    const monday = new Date(today)
    monday.setDate(today.getDate() - daysFromMon)
    return { start: isoDay(monday), end: todayIso }
  }
  return { start: customStart || KAM_YEAR_START, end: customEnd || todayIso }
}

// Mon..today, kept for the legacy "this week" caption.
export function KAM_CURRENT_WEEK(): KamBounds {
  return kamBounds("wtd")
}

function rangeQuery(b: KamBounds): string {
  return `range=custom&start_date=${encodeURIComponent(b.start)}&end_date=${encodeURIComponent(b.end)}`
}

// DFW sub-team pill (TM1..TM4) — shared across the Service, Lanes, Worst Lanes
// and Carrier Sales tabs. Empty selection ⇒ no predicate (all sub-teams).
function subTeamsQuery(subTeams: string[]): string {
  return subTeams.length
    ? `&sub_teams=${encodeURIComponent(subTeams.join(","))}`
    : ""
}

// ---------------------------------------------------------------------------
// Tab 1 — SCORECARDS
// ---------------------------------------------------------------------------

export interface KamScorecardRow {
  id: string
  customer: string
  scorecard_date: string
  scorecard_frequency: string
  uploaded_by_email: string | null
  uploaded_by_name: string | null
  created_at: string
}

export function useKamScorecards() {
  return useQuery({
    queryKey: ["kam-performance-dfw", "scorecards"],
    queryFn: () =>
      apiFetch<KamScorecardRow[]>("custom/kam-performance-dfw/scorecards"),
    staleTime: 30 * 1000,
    ...RETRY,
  })
}

export function useCreateScorecard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      customer: string
      scorecard_date: string
      scorecard_frequency: string
    }) =>
      apiFetch<KamScorecardRow>("custom/kam-performance-dfw/scorecards", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["kam-performance-dfw", "scorecards"] }),
    onError: mutationErrorToast("Add scorecard"),
  })
}

export function useDeleteScorecard() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<{ deleted: boolean }>(
        `custom/kam-performance-dfw/scorecards/${id}`,
        { method: "DELETE" },
      ),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["kam-performance-dfw", "scorecards"] }),
    onError: mutationErrorToast("Delete scorecard"),
  })
}

// ---------------------------------------------------------------------------
// Tab 3 — Top-Lanes free-text note
// ---------------------------------------------------------------------------

export interface KamTopLanesNote {
  notes: string
  updated_at: string | null
}

export function useTopLanesNote() {
  return useQuery({
    queryKey: ["kam-performance-dfw", "top-lanes-note"],
    queryFn: () =>
      apiFetch<KamTopLanesNote>("custom/kam-performance-dfw/top-lanes-note"),
    staleTime: 30 * 1000,
    ...RETRY,
  })
}

export function useUpsertTopLanesNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (notes: string) =>
      apiFetch<KamTopLanesNote>("custom/kam-performance-dfw/top-lanes-note", {
        method: "PUT",
        body: JSON.stringify({ notes }),
      }),
    onSuccess: () =>
      qc.invalidateQueries({
        queryKey: ["kam-performance-dfw", "top-lanes-note"],
      }),
    onError: mutationErrorToast("Save note"),
  })
}

// ---------------------------------------------------------------------------
// Tab 4 — CUSTOMER DEV
// ---------------------------------------------------------------------------

export interface KamCustomerDevRow {
  id: string
  contact_name: string
  last_day_spoke: string | null
  opportunity_areas: string
  action_plan: string
  created_at: string
  updated_at: string
}

export function useCustomerDev() {
  return useQuery({
    queryKey: ["kam-performance-dfw", "customer-dev"],
    queryFn: () =>
      apiFetch<KamCustomerDevRow[]>("custom/kam-performance-dfw/customer-dev"),
    staleTime: 30 * 1000,
    ...RETRY,
  })
}

export function useCreateCustomerDev() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      contact_name: string
      last_day_spoke?: string | null
      opportunity_areas?: string
      action_plan?: string
    }) =>
      apiFetch<KamCustomerDevRow>("custom/kam-performance-dfw/customer-dev", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () =>
      qc.invalidateQueries({
        queryKey: ["kam-performance-dfw", "customer-dev"],
      }),
    onError: mutationErrorToast("Add customer dev row"),
  })
}

export function useUpdateCustomerDev() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: string
      contact_name?: string
      last_day_spoke?: string | null
      last_day_spoke_set?: boolean
      opportunity_areas?: string
      action_plan?: string
    }) =>
      apiFetch<KamCustomerDevRow>(
        `custom/kam-performance-dfw/customer-dev/${id}`,
        {
          method: "PATCH",
          body: JSON.stringify(body),
        },
      ),
    onSuccess: () =>
      qc.invalidateQueries({
        queryKey: ["kam-performance-dfw", "customer-dev"],
      }),
    onError: mutationErrorToast("Save customer dev row"),
  })
}

export function useDeleteCustomerDev() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<{ deleted: boolean }>(
        `custom/kam-performance-dfw/customer-dev/${id}`,
        { method: "DELETE" },
      ),
    onSuccess: () =>
      qc.invalidateQueries({
        queryKey: ["kam-performance-dfw", "customer-dev"],
      }),
    onError: mutationErrorToast("Delete customer dev row"),
  })
}

// ---------------------------------------------------------------------------
// Tab 5 — TEAM DEV
// ---------------------------------------------------------------------------

export interface KamTeamDevRow {
  id: string
  team_member: string
  last_one_on_one: string
  specific_area: string
  action_plan: string
  created_at: string
  updated_at: string
}

export function useTeamDev() {
  return useQuery({
    queryKey: ["kam-performance-dfw", "team-dev"],
    queryFn: () =>
      apiFetch<KamTeamDevRow[]>("custom/kam-performance-dfw/team-dev"),
    staleTime: 30 * 1000,
    ...RETRY,
  })
}

export function useCreateTeamDev() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      team_member: string
      last_one_on_one?: string
      specific_area?: string
      action_plan?: string
    }) =>
      apiFetch<KamTeamDevRow>("custom/kam-performance-dfw/team-dev", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["kam-performance-dfw", "team-dev"] }),
    onError: mutationErrorToast("Add team dev row"),
  })
}

export function useUpdateTeamDev() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: string
      team_member?: string
      last_one_on_one?: string
      specific_area?: string
      action_plan?: string
    }) =>
      apiFetch<KamTeamDevRow>(`custom/kam-performance-dfw/team-dev/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["kam-performance-dfw", "team-dev"] }),
    onError: mutationErrorToast("Save team dev row"),
  })
}

export function useDeleteTeamDev() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) =>
      apiFetch<{ deleted: boolean }>(
        `custom/kam-performance-dfw/team-dev/${id}`,
        { method: "DELETE" },
      ),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["kam-performance-dfw", "team-dev"] }),
    onError: mutationErrorToast("Delete team dev row"),
  })
}

// ---------------------------------------------------------------------------
// Tab 2 — SERVICE: ride on existing ops-customer-score endpoints.
// Tab 3 — TOP LANES: ride on existing xray-dfw endpoints.
// Both gated by their own report_key, so KAM users need access to the
// underlying reports too. See seed.py — DFW + Executive + CEO + Operations
// already share access.
// ---------------------------------------------------------------------------

interface ServiceOverviewKpi {
  orders: number
  fail: number
  pct_on_time: number | null
}
interface ServiceOverviewResponse {
  kpi: ServiceOverviewKpi
}

export function useDfwServiceKpi(
  side: "pu" | "del",
  bounds: KamBounds,
  subTeams: string[] = [],
) {
  return useQuery({
    queryKey: [
      "kam-performance-dfw",
      "service-kpi",
      side,
      bounds.start,
      bounds.end,
      subTeams.join(","),
    ],
    queryFn: () =>
      apiFetch<ServiceOverviewResponse>(
        `custom/ops-customer-score/${side}/overview?${rangeQuery(bounds)}&division=DFW${subTeamsQuery(subTeams)}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export interface ServiceFailureRow {
  id: string
  team_id: string | null
  team_dfw: string | null
  customer_name: string | null
  actual_arrival: string | null
  sched_late: string | null
  edi_standard_code: string | null
  edi_code_descr: string | null
  dsp_comment: string | null
  payee_name: string | null
  entered_user_id: string | null
}

export function useDfwServiceFailures(
  side: "pu" | "del",
  fault: "our" | "not",
  bounds: KamBounds,
  page: number,
  limit = 200,
  subTeams: string[] = [],
) {
  return useQuery({
    queryKey: [
      "kam-performance-dfw",
      "service-failures",
      side,
      fault,
      bounds.start,
      bounds.end,
      page,
      limit,
      subTeams.join(","),
    ],
    queryFn: () =>
      apiFetch<ServiceFailureRow[]>(
        `custom/ops-customer-score/${side}/${fault === "our" ? "our-fault" : "not-our-fault"}?${rangeQuery(bounds)}&division=DFW&page=${page}&limit=${limit}${subTeamsQuery(subTeams)}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

// ---------------------------------------------------------------------------
// Tab 3 — Top 10 lanes filters (customer + sub-team), rides on xray-dfw.
// "GM C/O CTSI" is always dropped (Bruno KAM update — was GENERAL MOTORS +
// HOMEDEPOT; Home Depot is now returned and only GM C/O CTSI stays excluded).
// ---------------------------------------------------------------------------

const KAM_LANE_EXCLUDE = "GM C/O CTSI"

interface XrayDfwFilters {
  sub_teams: string[]
  customers: string[]
}

export function useXrayDfwFilters() {
  return useQuery({
    queryKey: ["kam-performance-dfw", "xray-filters"],
    queryFn: () => apiFetch<XrayDfwFilters>("custom/xray-dfw/filters"),
    staleTime: 5 * 60 * 1000,
    ...RETRY,
  })
}

function laneFilterQuery(customer: string, subTeams: string[]): string {
  let q = `&exclude_customers=${encodeURIComponent(KAM_LANE_EXCLUDE)}`
  if (customer) q += `&customer=${encodeURIComponent(customer)}`
  if (subTeams.length) q += `&sub_teams=${encodeURIComponent(subTeams.join(","))}`
  return q
}

interface XrayDfwKpis {
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
  loss_loads: number
}

export function useDfwLaneKpi(bounds: KamBounds, customer: string, subTeams: string[]) {
  return useQuery({
    queryKey: ["kam-performance-dfw", "dfw-kpi", bounds.start, bounds.end, customer, subTeams.join(",")],
    queryFn: () =>
      apiFetch<XrayDfwKpis>(
        `custom/xray-dfw/kpis?${rangeQuery(bounds)}${laneFilterQuery(customer, subTeams)}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export interface DfwLaneRow {
  lane: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
}

export function useDfwTop10Lanes(bounds: KamBounds, customer: string, subTeams: string[]) {
  return useQuery({
    queryKey: ["kam-performance-dfw", "top10-lanes", bounds.start, bounds.end, customer, subTeams.join(",")],
    queryFn: () =>
      apiFetch<DfwLaneRow[]>(
        `custom/xray-dfw/by-lane?${rangeQuery(bounds)}&limit=10${laneFilterQuery(customer, subTeams)}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

// ---------------------------------------------------------------------------
// Tab 6 — WORST 10 LANES (Bruno R2). Worst losing (customer, lane) pairs for
// DFW + per-lane editable Expiration Date / Action Plan.
// ---------------------------------------------------------------------------

export interface KamWorstLaneRow {
  lane_key: string
  customer: string
  lane: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number | null
  expiration_date: string | null
  action_plan: string
}

export function useWorstLanes(bounds: KamBounds, subTeams: string[] = []) {
  return useQuery({
    queryKey: [
      "kam-performance-dfw",
      "worst-lanes",
      bounds.start,
      bounds.end,
      subTeams.join(","),
    ],
    queryFn: () =>
      apiFetch<KamWorstLaneRow[]>(
        `custom/kam-performance-dfw/worst-lanes?${rangeQuery(bounds)}&limit=10${subTeamsQuery(subTeams)}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export function useUpsertWorstLaneNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      lane_key: string
      expiration_date?: string | null
      action_plan?: string
    }) =>
      apiFetch<{ lane_key: string; expiration_date: string | null; action_plan: string }>(
        "custom/kam-performance-dfw/worst-lane-notes",
        { method: "PUT", body: JSON.stringify(body) },
      ),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["kam-performance-dfw", "worst-lanes"] }),
    onError: mutationErrorToast("Save lane note"),
  })
}

// ---------------------------------------------------------------------------
// Tab 7 — CARRIER SALES (Bruno R2). Per-lane latest carriers + avg cost +
// per-lane editable Comments.
// ---------------------------------------------------------------------------

export interface KamCarrierSalesRow {
  lane_key: string
  lane: string
  carriers: string
  avg_cost: number | null
  movements: number
  comments: string
}

export function useCarrierSales(bounds: KamBounds, subTeams: string[] = []) {
  return useQuery({
    queryKey: [
      "kam-performance-dfw",
      "carrier-sales",
      bounds.start,
      bounds.end,
      subTeams.join(","),
    ],
    queryFn: () =>
      apiFetch<KamCarrierSalesRow[]>(
        `custom/kam-performance-dfw/carrier-sales?${rangeQuery(bounds)}${subTeamsQuery(subTeams)}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export function useUpsertCarrierComment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { lane_key: string; comments: string }) =>
      apiFetch<{ lane_key: string; comments: string }>(
        "custom/kam-performance-dfw/carrier-comments",
        { method: "PUT", body: JSON.stringify(body) },
      ),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["kam-performance-dfw", "carrier-sales"] }),
    onError: mutationErrorToast("Save carrier comment"),
  })
}
