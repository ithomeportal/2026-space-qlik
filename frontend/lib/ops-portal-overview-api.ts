"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: Record<string, unknown>
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
// Filter contract
// ---------------------------------------------------------------------------

export type OppRange = "mtd" | "ytd" | "full" | "custom"
export type LoadType = "" | "contract" | "spot"

export interface OppFilters {
  range: OppRange
  startDate?: string
  endDate?: string
  team?: string
  customer?: string
  loadType?: LoadType
}

function qs(f: OppFilters, extra?: Record<string, string>): string {
  const q = new URLSearchParams()
  if (f.range) q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  if (f.team) q.set("team", f.team)
  if (f.customer) q.set("customer", f.customer)
  if (f.loadType) q.set("load_type", f.loadType)
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface OppFilterOptions {
  teams: string[]
  customers: string[]
  year_start: string
  year_end: string
}

export interface OppWorkdays {
  month_start: string
  month_end: string
  today: string
  total_workdays: number
  past_workdays: number
  pending_workdays: number
}

export interface OppMonthBucket {
  month_start: string
  volume: number
  revenue: number
  profit: number
  margin_pct: number
  losses: number
  budget_revenue: number
  budget_profit: number
  budget_loads: number
}

export interface OppCombo {
  months: OppMonthBucket[]
  projected_tm: number
  today: string
  month_start: string
  month_end: string
  pending_workdays: number
}

export interface OppTeamVariance {
  customers: number
  volume_var: number
  revenue_var: number
  profit_var: number
  margin_var_pct: number
  rev_x_l: number
  prof_x_l: number
  window: { start: string; end: string }
}

export interface OppCustomerVariance {
  customer_name: string
  volume_var: number
  revenue_var: number
  profit_var: number
}

export interface OppCustomerLoss {
  customer_name: string
  loss_loads: number
  loss_profit: number
}

export interface OppTeamPerformance {
  customers: number
  lanes: number
  volume: number
  revenue: number
  profit: number
  margin_pct: number
  rev_x_l: number
  prof_x_l: number
  team_ut: number
  otp_pct: number
  lates_pu: number
  otd_pct: number
  lates_del: number
  savings: number
  over_pay: number
  net_savings: number
  loss_loads: number
  profit_loss: number
  cust_attr_pct: number
  lane_attr_pct: number
  window: { start: string; end: string }
}

export interface OppTeamProjection {
  avg_vol_day: number
  avg_rev_day: number
  avg_prof_day: number
  pending_workdays: number
  proj_volume: number
  proj_revenue: number
  proj_profit: number
  proj_margin_pct: number
  proj_rev_x_l: number
  proj_prof_x_l: number
  proj_team_ut: number
  today: string
  month_start: string
  month_end: string
}

export interface OppProfitTmGauge {
  profit_mtd: number
  profit_budget: number
  pct_of_budget: number
  month_start: string
  month_end: string
}

export interface OppActualsRow {
  customer_name: string
  vol: number
  vol_budget: number
  vol_var: number
  rev: number
  rev_budget: number
  rev_var: number
  prof: number
  prof_budget: number
  prof_var: number
  margin_pct: number
  margin_budget_pct: number
  margin_var_pct: number
  otp_pct: number
  otd_pct: number
  rev_x_l: number
  prof_x_l: number
  vol_x_day: number
  prof_x_day: number
  proj_eom_vol: number
  proj_eom_prof: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

const BASE = "custom/ops-portal-overview"

export function useOppFilters() {
  return useQuery({
    queryKey: ["opp-filters"],
    queryFn: () => apiFetch<OppFilterOptions>(`${BASE}/filters`),
    staleTime: 60 * 60 * 1000,
    ...RETRY,
  })
}

export function useOppWorkdays() {
  return useQuery({
    queryKey: ["opp-workdays"],
    queryFn: () => apiFetch<OppWorkdays>(`${BASE}/workdays`),
    staleTime: 30 * 60 * 1000,
    ...RETRY,
  })
}

export function useOppCombo(f: Pick<OppFilters, "team" | "customer" | "loadType">) {
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    queryKey: ["opp-combo", f.team || "", f.customer || "", f.loadType || ""],
    queryFn: () => apiFetch<OppCombo>(`${BASE}/combo${qs(filters)}`),
    ...RETRY,
  })
}

export function useOppTeamVariance(f: OppFilters) {
  return useQuery({
    queryKey: ["opp-team-variance", f.range, f.startDate, f.endDate, f.team, f.customer],
    queryFn: () => apiFetch<OppTeamVariance>(`${BASE}/team-variance${qs(f)}`),
    ...RETRY,
  })
}

export function useOppCustomerVariance(f: OppFilters) {
  return useQuery({
    queryKey: ["opp-customer-variance", f.range, f.startDate, f.endDate, f.team, f.customer],
    queryFn: () => apiFetch<OppCustomerVariance[]>(`${BASE}/customer-variance${qs(f)}`),
    ...RETRY,
  })
}

export function useOppCustomerLosses(f: OppFilters) {
  return useQuery({
    queryKey: ["opp-customer-losses", f.range, f.startDate, f.endDate, f.team, f.customer, f.loadType],
    queryFn: () => apiFetch<OppCustomerLoss[]>(`${BASE}/customer-losses${qs(f)}`),
    ...RETRY,
  })
}

export function useOppTeamPerformance(f: OppFilters) {
  return useQuery({
    queryKey: ["opp-team-performance", f.range, f.startDate, f.endDate, f.team, f.customer, f.loadType],
    queryFn: () => apiFetch<OppTeamPerformance>(`${BASE}/team-performance${qs(f)}`),
    ...RETRY,
  })
}

export function useOppTeamProjection(f: Pick<OppFilters, "team" | "customer" | "loadType">) {
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    queryKey: ["opp-team-projection", f.team || "", f.customer || "", f.loadType || ""],
    queryFn: () => apiFetch<OppTeamProjection>(`${BASE}/team-projection${qs(filters)}`),
    ...RETRY,
  })
}

export function useOppProfitTmGauge(f: Pick<OppFilters, "team" | "customer" | "loadType">) {
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    queryKey: ["opp-profit-tm-gauge", f.team || "", f.customer || "", f.loadType || ""],
    queryFn: () => apiFetch<OppProfitTmGauge>(`${BASE}/profit-tm-gauge${qs(filters)}`),
    ...RETRY,
  })
}

export function useOppActuals(f: OppFilters, opts?: { sort?: string; limit?: number }) {
  const sort = opts?.sort ?? "revenue_desc"
  const limit = opts?.limit ?? 100
  return useQuery({
    queryKey: [
      "opp-actuals",
      f.range, f.startDate, f.endDate,
      f.team, f.customer, f.loadType,
      sort, limit,
    ],
    queryFn: () =>
      apiFetch<OppActualsRow[]>(
        `${BASE}/actuals${qs(f, { sort, limit: String(limit) })}`,
      ),
    ...RETRY,
  })
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

const usdFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})

const numFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 })

export function fmtUsd(v: number): string {
  if (!Number.isFinite(v)) return "$0"
  return usdFmt.format(v)
}

export function fmtUsdSigned(v: number): string {
  if (!Number.isFinite(v)) return "$0"
  return v < 0 ? `-${usdFmt.format(Math.abs(v))}` : usdFmt.format(v)
}

export function fmtCount(v: number): string {
  if (!Number.isFinite(v)) return "0"
  return numFmt.format(Math.round(v))
}

export function fmtPct(v: number): string {
  if (!Number.isFinite(v)) return "0%"
  return `${v.toFixed(2)}%`
}

export function fmtMonth(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleString("en-US", { month: "short", year: "2-digit" })
}
