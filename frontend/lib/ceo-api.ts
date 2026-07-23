"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
}

async function apiFetch<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

const CEO_RETRY = {
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

// Bruno 2026-06-30: "week" / "today" / "day" are client-resolved windows. The
// page computes their explicit start/end and they ride to the backend as a
// "custom" range (see ceoQs), so the backend contract stays mtd|ytd|full|custom.
// "lastMonth" (Bruno 2026-07-01) is a client-resolved window like week/today/
// day — the page computes its explicit start/end and it rides to the backend
// as "custom" (see ceoQs). "full" stays in the type (default range logic still
// references it) even though its pill was removed from the UI.
export type CeoRange =
  | "mtd"
  | "ytd"
  | "full"
  | "custom"
  | "week"
  | "today"
  | "day"
  | "lastMonth"
export type CeoDivision = "CORP" | "DFW"
// Bruno 2026-07-01 (Overview Request 3): global Contract/Spot filter.
export type CeoLoadType = "contract" | "spot"

export interface CeoFilters {
  range: CeoRange
  startDate?: string
  endDate?: string
  division?: CeoDivision
  team?: string
  customer?: string
  contractType?: CeoLoadType
}

function ceoQs(f: CeoFilters) {
  const q = new URLSearchParams()
  // Presets (mtd/ytd/full) are resolved server-side; everything else — custom
  // plus the client-resolved week/today/day windows — sends explicit bounds as
  // a "custom" range.
  const preset = f.range === "mtd" || f.range === "ytd" || f.range === "full"
  const backendRange = preset ? f.range : "custom"
  q.set("range", backendRange)
  if (backendRange === "custom") {
    if (f.startDate) q.set("start_date", f.startDate)
    if (f.endDate) q.set("end_date", f.endDate)
  }
  if (f.division) q.set("division", f.division)
  if (f.team) q.set("team", f.team)
  if (f.customer) q.set("customer", f.customer)
  if (f.contractType) q.set("load_type", f.contractType)
  return `?${q.toString()}`
}

// Same-origin proxy path for the All Orders CSV export (Bruno 2026-06-09).
// The backend streams every row for the current filter scope; the proxy
// passes the text/csv body through with its Content-Disposition intact, so
// an <a href download> saves it via the NextAuth session cookie.
export function ceoOrdersCsvPath(f: CeoFilters): string {
  return `custom/ceo-executive/orders.csv${ceoQs(f)}`
}

// ---------------------------------------------------------------------------
// Response types
// ---------------------------------------------------------------------------

export interface CeoFilterOptions {
  divisions?: CeoDivision[]
  teams: string[]
  teams_by_division?: Record<CeoDivision, string[]>
  customers: string[]
  year_start: string
  year_end: string
}

export interface CeoKpis {
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  avg_r_per_l: number
  avg_p_per_l: number
}

export interface CeoTeamRow {
  team: string
  cust: number
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  avg_r_per_l: number
  avg_p_per_l: number
}

export interface CeoAtpRow {
  team: string
  yd_loads: number
  yd_profit: number
  yd_margin_pct: number
  wk_loads: number
  wk_profit: number
  wk_margin_pct: number
  mo_loads: number
  mo_profit: number
  mo_margin_pct: number
  mo_p_per_l: number
}

export interface CeoOverview {
  kpis: CeoKpis
  profit_tm: number
  // Bruno 2026-07-01 (Overview Request 4): date-scoped profit budget target
  // for the PROFIT gauge (from daily_production_budget_report."Profit Budget").
  profit_budget: number
  window: { start: string; end: string }
  summary_by_team: CeoTeamRow[]
  all_teams_performance: CeoAtpRow[]
  atp_window: { yesterday: string; week_start: string; month_start: string }
}

export interface CeoTrendPoint {
  bucket: string
  customers: number
  margin_pct: number
  profit: number
  loads: number
}

export interface CeoTrends {
  monthly: CeoTrendPoint[]
  daily: CeoTrendPoint[]
  monthly_window: { start: string; end: string }
  daily_window: { start: string; end: string }
}

export interface CeoCustomerRow {
  customer: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  conc_pct: number
  avg_p_per_l: number
}

export interface CeoTop5Row {
  customer: string
  revenue: number
  profit: number
  conc_pct: number
}

export interface CeoCustomerTotals {
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  conc_pct: number
  avg_p_per_l: number
}

export interface CeoCustomers {
  by_customer: CeoCustomerRow[]
  /** Distinct customers in the FULL filtered universe. Server-side — `by_customer`
   *  is LIMIT 200, so its length would freeze at 200 once the cap binds (§44). */
  customer_count: number
  /** Pinned Totals row for BOTH customer tables, over the FULL filtered
   *  universe (§44 — never a client reduce() over the LIMIT-200 array).
   *  `by_customer` and `worst_by_customer` share one universe, so they share
   *  these totals; that is what makes the two tables reconcile. */
  totals: CeoCustomerTotals
  worst_by_customer: CeoCustomerRow[]
  top5_revenue: CeoTop5Row[]
  top5_profit: CeoTop5Row[]
  // Bruno R7: full remaining-customer lists behind the "Others" slice.
  top5_revenue_others: CeoTop5Row[]
  top5_profit_others: CeoTop5Row[]
  window: { start: string; end: string }
}

export interface CeoWeekRow {
  week_start: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
}

export interface CeoSummaryWeekRow {
  week_start: string
  lanes: number
  loads: number
  revenue: number
  profit: number
  margin_pct: number
}

export interface CeoWeekly {
  weeks: CeoWeekRow[]
  summary_by_week: CeoSummaryWeekRow[]
}

export interface CeoWorstLane {
  customer: string
  origin: string
  destination: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  diff_15: number
  diff_18: number
  diff_20: number
}

export interface CeoNegOrder {
  id: string
  team: string
  contract_type: string
  customer: string
  carrier: string
  origin: string
  destination: string
  departure: string | null
  revenue: number
  profit: number
  margin_pct: number
  conc_pct: number
}

export interface CeoNegCustomer {
  customer: string
  loads: number
  revenue: number
  profit: number
  conc_pct: number
}

export interface CeoRiskTotals {
  loads: number
  revenue: number
  profit: number
  margin_pct: number
}

export interface CeoRisk {
  totals: CeoRiskTotals
  worst_lanes: CeoWorstLane[]
  neg_orders: CeoNegOrder[]
  neg_customers: CeoNegCustomer[]
  window: { start: string; end: string }
}

export interface CeoLaneAnalysis {
  customer: string
  origin: string
  destination: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  conc_pct: number
  diff_15: number
  diff_18: number
  diff_20: number
}

export interface CeoAllOrder {
  team: string
  contract_type: string
  id: string
  customer: string
  carrier: string
  origin: string
  destination: string
  departure: string | null
  revenue: number
  profit: number
  margin_pct: number
  diff_15: number
  diff_18: number
  diff_20: number
}

export interface CeoOrders {
  lane_analysis: CeoLaneAnalysis[]
  all_orders: CeoAllOrder[]
  all_orders_total: number
  page: number
  page_size: number
  window: { start: string; end: string }
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useCeoFilters() {
  return useQuery({
    ...CEO_RETRY,
    queryKey: ["ceo", "filters"],
    queryFn: () => apiFetch<CeoFilterOptions>("custom/ceo-executive/filters"),
    staleTime: 30 * 60 * 1000,
  })
}

export function useCeoOverview(f: CeoFilters, enabled = true) {
  return useQuery({
    ...CEO_RETRY,
    enabled,
    queryKey: ["ceo", "overview", f],
    queryFn: () => apiFetch<CeoOverview>(`custom/ceo-executive/overview${ceoQs(f)}`),
  })
}

// Bruno R4 (2026-05-12): Trends/Weekly honor Division + Team.
// R5 (2026-05-21): Customer too. Date windows stay fixed.
type CeoScopeFilters = Pick<CeoFilters, "division" | "team" | "customer" | "contractType">

function ceoScopeQs(f: CeoScopeFilters) {
  const q = new URLSearchParams()
  if (f.division) q.set("division", f.division)
  if (f.team) q.set("team", f.team)
  if (f.customer) q.set("customer", f.customer)
  if (f.contractType) q.set("load_type", f.contractType)
  const s = q.toString()
  return s ? `?${s}` : ""
}

export function useCeoTrends(f: CeoScopeFilters, enabled = true) {
  return useQuery({
    ...CEO_RETRY,
    enabled,
    queryKey: ["ceo", "trends", f.division ?? "", f.team ?? "", f.customer ?? "", f.contractType ?? ""],
    queryFn: () => apiFetch<CeoTrends>(`custom/ceo-executive/trends${ceoScopeQs(f)}`),
    staleTime: 5 * 60 * 1000,
  })
}

export function useCeoCustomers(f: CeoFilters, enabled = true) {
  return useQuery({
    ...CEO_RETRY,
    enabled,
    queryKey: ["ceo", "customers", f],
    queryFn: () => apiFetch<CeoCustomers>(`custom/ceo-executive/customers${ceoQs(f)}`),
  })
}

export function useCeoWeekly(f: CeoScopeFilters, enabled = true) {
  return useQuery({
    ...CEO_RETRY,
    enabled,
    queryKey: ["ceo", "weekly", f.division ?? "", f.team ?? "", f.customer ?? "", f.contractType ?? ""],
    queryFn: () => apiFetch<CeoWeekly>(`custom/ceo-executive/weekly${ceoScopeQs(f)}`),
    staleTime: 5 * 60 * 1000,
  })
}

export function useCeoRisk(f: CeoFilters, enabled = true) {
  return useQuery({
    ...CEO_RETRY,
    enabled,
    queryKey: ["ceo", "risk", f],
    queryFn: () => apiFetch<CeoRisk>(`custom/ceo-executive/risk${ceoQs(f)}`),
  })
}

// Bruno R7 (2026-05-26): All Orders is server-paginated. `page` is 1-based;
// page_size fixed at 100. Lane analysis is returned on every page (cheap
// aggregate) so the lane table stays populated while paging the order list.
export function useCeoOrders(f: CeoFilters, page = 1, enabled = true) {
  return useQuery({
    ...CEO_RETRY,
    enabled,
    placeholderData: (prev) => prev,
    queryKey: ["ceo", "orders", f, page],
    queryFn: () => {
      const qs = ceoQs(f)
      const sep = qs.includes("?") ? "&" : "?"
      return apiFetch<CeoOrders>(
        `custom/ceo-executive/orders${qs}${sep}page=${page}&page_size=100`,
      )
    },
  })
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

export const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
export const COUNT = new Intl.NumberFormat("en-US")
export const PCT1 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
})
export const PCT2 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
})

export const fmtUsd = (v?: number | null) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))
export const fmtCount = (v?: number | null) =>
  v === null || v === undefined ? "—" : COUNT.format(Math.round(Number(v)))
export const fmtPct = (v?: number | null) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : `${PCT1.format(Number(v))}%`
export const fmtPct2 = (v?: number | null) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : `${PCT2.format(Number(v))}%`

export function fmtMonth(iso: string): string {
  const d = new Date(iso + "T00:00:00")
  return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" })
}

export function fmtDay(iso: string): string {
  const d = new Date(iso + "T00:00:00")
  return `${d.getDate()}/${d.getMonth() + 1}`
}

export function fmtWeekRange(iso: string): string {
  const start = new Date(iso + "T00:00:00")
  const end = new Date(start)
  end.setDate(end.getDate() + 6)
  const s = `${String(start.getMonth() + 1).padStart(2, "0")}/${String(start.getDate()).padStart(2, "0")}`
  const e = `${String(end.getMonth() + 1).padStart(2, "0")}/${String(end.getDate()).padStart(2, "0")}`
  return `${s} – ${e}`
}
