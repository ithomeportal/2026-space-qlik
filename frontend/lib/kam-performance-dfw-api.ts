"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

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
// This-week (Mon..today, CST) bounds used for service KPIs and Top-10 KPIs.
// Computed in JS so callers can pass `range=custom&start_date=…&end_date=…`
// to the existing ops-customer-score / xray-dfw endpoints.
// ---------------------------------------------------------------------------

function currentWeekBoundsIso(): { start: string; end: string } {
  const now = new Date()
  // Use the browser's local clock; backend pins CST so any tz < 6h off is fine.
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const dow = today.getDay() // Sun=0, Mon=1, ...
  const daysFromMon = (dow + 6) % 7 // Mon-anchored
  const monday = new Date(today)
  monday.setDate(today.getDate() - daysFromMon)
  const iso = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
  return { start: iso(monday), end: iso(today) }
}

export const KAM_CURRENT_WEEK = currentWeekBoundsIso

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

export function useDfwServiceKpi(side: "pu" | "del") {
  const { start, end } = KAM_CURRENT_WEEK()
  return useQuery({
    queryKey: ["kam-performance-dfw", "service-kpi", side, start, end],
    queryFn: () =>
      apiFetch<ServiceOverviewResponse>(
        `custom/ops-customer-score/${side}/overview?range=custom&start_date=${start}&end_date=${end}&division=DFW`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export interface ServiceFailureRow {
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

export function useDfwServiceFailures(
  side: "pu" | "del",
  fault: "our" | "not",
  page: number,
  limit = 200,
) {
  const { start, end } = KAM_CURRENT_WEEK()
  return useQuery({
    queryKey: [
      "kam-performance-dfw",
      "service-failures",
      side,
      fault,
      start,
      end,
      page,
      limit,
    ],
    queryFn: () =>
      apiFetch<ServiceFailureRow[]>(
        `custom/ops-customer-score/${side}/${fault === "our" ? "our-fault" : "not-our-fault"}?range=custom&start_date=${start}&end_date=${end}&division=DFW&page=${page}&limit=${limit}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

// xray-dfw KPIs accept range=custom for an arbitrary window
interface XrayDfwKpis {
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
  loss_loads: number
}

export function useDfwLaneKpi() {
  const { start, end } = KAM_CURRENT_WEEK()
  return useQuery({
    queryKey: ["kam-performance-dfw", "dfw-kpi", start, end],
    queryFn: () =>
      apiFetch<XrayDfwKpis>(
        `custom/xray-dfw/kpis?range=custom&start_date=${start}&end_date=${end}`,
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

export function useDfwTop10Lanes() {
  const { start, end } = KAM_CURRENT_WEEK()
  return useQuery({
    queryKey: ["kam-performance-dfw", "top10-lanes", start, end],
    queryFn: () =>
      apiFetch<DfwLaneRow[]>(
        `custom/xray-dfw/by-lane?range=custom&start_date=${start}&end_date=${end}&limit=10`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}
