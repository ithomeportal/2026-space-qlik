"use client"

import { createContext, createElement, useContext, type ReactNode } from "react"
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

const XRAY_DFW_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// API prefix context — default points at the cross-team `/custom/xray-dfw`
// router. Per-team pages (e.g. /reports/xray-dfw-tm1) wrap their content in
// <XrayDfwApiProvider prefix="custom/xray-dfw-tm1"> so every hook below
// transparently hits the team-locked endpoints.
// ---------------------------------------------------------------------------

const DEFAULT_PREFIX = "custom/xray-dfw"

const ApiPrefixContext = createContext<string>(DEFAULT_PREFIX)

export function XrayDfwApiProvider({
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
// Filter contract — DFW variant uses sub_teams (CSV) instead of single team.
// ---------------------------------------------------------------------------

export type XrayDfwRange = "mtd" | "ytd" | "full" | "custom"
export type XrayDfwView = "ruan"

export interface XrayDfwFilters {
  range: XrayDfwRange
  startDate?: string
  endDate?: string
  subTeams?: string[] // empty / undefined = all 4
  customers?: string[] // multi-select customer (or RUAN client) filter
  lanes?: string[] // multi-select lane filter
  contractTypes?: string[] // multi-select contract-type filter
  equipment?: string[] // multi-select equipment-group filter
  view?: XrayDfwView // "ruan" swaps customer_name → client
}

function dfwQs(f: XrayDfwFilters) {
  const q = new URLSearchParams()
  if (f.range) q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  if (f.subTeams && f.subTeams.length) q.set("sub_teams", f.subTeams.join(","))
  if (f.customers && f.customers.length) q.set("customers", f.customers.join(","))
  if (f.lanes && f.lanes.length) q.set("lanes", f.lanes.join(","))
  if (f.contractTypes && f.contractTypes.length)
    q.set("contract_type", f.contractTypes.join(","))
  if (f.equipment && f.equipment.length) q.set("equipment", f.equipment.join(","))
  if (f.view) q.set("view", f.view)
  const s = q.toString()
  return s ? `?${s}` : ""
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface XrayDfwFilterOptions {
  sub_teams: string[]
  customers: string[]
  lanes: string[]
  contract_types?: string[]
  equipment_groups?: string[]
  year_start: string
  year_end: string
  locked_team?: string
}

export interface XrayDfwKpis {
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
  loss_loads: number
  profit_tm: number
  total_savings: number
  total_overpay: number
  net_variance: number
  window: { start: string; end: string }
}

export interface XrayDfwTrioRow {
  team: string
  vol: number
  rev: number
  prof: number
  m_pct: number | null
  otp_pct: number | null
  otd_pct: number | null
  tu: number
  r_per_l: number
  p_per_l: number
}

export interface XrayDfwTrio {
  yesterday: { from: string; to: string; totals: XrayDfwTrioRow | null; teams: XrayDfwTrioRow[] }
  week: { from: string; to: string; totals: XrayDfwTrioRow | null; teams: XrayDfwTrioRow[] }
  month: { from: string; to: string; totals: XrayDfwTrioRow | null; teams: XrayDfwTrioRow[] }
}

export interface XrayDfwProjection {
  total_customers: number
  total_lanes: number
  avg_vol_day: number
  avg_vol_week: number
  projected_vol_month: number
  avg_profit_day: number
  avg_profit_week: number
  projected_profit_month: number
  past_days: number
  pending_days: number
}

export interface XrayDfwCustomerRow {
  customer_name: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
}

export interface XrayDfwLaneRow {
  lane: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
}

export interface XrayDfwAttritionRow {
  customer_name: string
  lane: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
  last_load_date: string | null
  days_since: number
}

export interface XrayDfwTeamBucket {
  loads: number
  revenue: number
  profit: number
  margin_pct: number
}

export interface XrayDfwTeamBreakdownRow {
  team?: string
  tm: XrayDfwTeamBucket
  tw: XrayDfwTeamBucket
  l1w: XrayDfwTeamBucket
  l2w: XrayDfwTeamBucket
  l3w: XrayDfwTeamBucket
  l4w: XrayDfwTeamBucket
  l5w: XrayDfwTeamBucket
  avg_l5w: XrayDfwTeamBucket
  avg_l5w_minus_lw: XrayDfwTeamBucket
}

export interface XrayDfwTeamBreakdown {
  teams: XrayDfwTeamBreakdownRow[]
  totals: Omit<XrayDfwTeamBreakdownRow, "team">
}

export interface XrayDfwTrendPoint {
  bucket: string
  loads: number
  revenue: number
  profit: number
  carrier_pay: number
  margin_pct: number
  avg_r_per_l: number
  avg_p_per_l: number
  avg_cc_per_l: number
}

export interface XrayDfwTrends {
  day: XrayDfwTrendPoint[]
  week: XrayDfwTrendPoint[]
  month: XrayDfwTrendPoint[]
}

export interface XrayDfwSummaryRow {
  bucket: string
  lanes: number
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
}

export interface XrayDfwSummaryTable {
  months: XrayDfwSummaryRow[]
  weeks: XrayDfwSummaryRow[]
}

export interface XrayDfwWorstLane {
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

export interface XrayDfwNegOrder {
  id: string
  customer: string
  carrier: string
  origin: string
  destination: string
  revenue: number
  profit: number
  margin_pct: number
  conc_pct: number
}

export interface XrayDfwNegCustomer {
  customer: string
  loads: number
  revenue: number
  profit: number
  conc_pct: number
}

export interface XrayDfwLossPoint {
  bucket: string
  loads: number
  profit: number
}

// Bruno 2026-06-03: server-side full-universe Totals rows (independent of the
// per-table display LIMITs).
export interface XrayDfwWorstLaneTotals {
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  diff_15: number
  diff_18: number
  diff_20: number
}

export interface XrayDfwNegTotals {
  loads: number
  revenue: number
  profit: number
  margin_pct: number
}

export interface XrayDfwRisk {
  worst_lanes: XrayDfwWorstLane[]
  neg_orders: XrayDfwNegOrder[]
  neg_customers: XrayDfwNegCustomer[]
  losses_month: XrayDfwLossPoint[]
  losses_week: XrayDfwLossPoint[]
  totals: {
    worst_lanes: XrayDfwWorstLaneTotals
    neg: XrayDfwNegTotals
  }
}

export interface XrayDfwContractSpotPoint {
  bucket: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
}

export interface XrayDfwContractSpot {
  contract: XrayDfwContractSpotPoint[]
  spot: XrayDfwContractSpotPoint[]
}

export interface XrayDfwContractSpotKpiBlock {
  profit: number
  losses: number
  total: number
}

export interface XrayDfwContractSpotKpis {
  contract: XrayDfwContractSpotKpiBlock
  spot: XrayDfwContractSpotKpiBlock
}

export interface XrayDfwAllOrder {
  team: string
  id: string
  /** ⚠ `id` alone is not unique in v4 — key rows on `id`+`company_id`. */
  company_id: string
  customer: string
  carrier: string
  origin: string
  destination: string
  departure: string | null
  revenue: number
  profit: number
  margin_pct: number
  contract_type: string
  equipment_group: string
  /**
   * Bruno PDF 2026-09-15 R4 — from `mcleod_gld_customer_view`, joined on BOTH
   * `id` and `company_id` (that pair is its PRIMARY KEY, so no fan-out).
   * null when McLeod has none: the server NULLIFs the empty string McLeod
   * actually writes, so the cell renders an em-dash rather than a silent gap.
   */
  bol: string | null
  po: string | null
}

export interface XrayDfwLaneAnalysisRow {
  customer: string
  origin: string
  destination: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  avg_r_per_l: number
  avg_p_per_l: number
  conc_pct: number
  diff_15: number
  diff_18: number
  diff_20: number
}

// Bruno 2026-06-03: /all-orders is server-paginated (500/page) and both
// Contract-vs-Spot tables carry full-universe Totals rows.
export interface XrayDfwAllOrdersTotals {
  loads: number
  /**
   * Orders with `total_charge = 0` — real moving loads whose revenue has not
   * been billed yet, so `margin_amt = −carrier_pay` on each. Always 0 unless
   * the caller passed `includeZeroCharge`. The GM tab prints it beside the
   * order count so the profit those rows drag down reads as a billing lag
   * rather than a loss.
   */
  unbilled: number
  revenue: number
  profit: number
  margin_pct: number
}

export interface XrayDfwAllOrdersPage {
  rows: XrayDfwAllOrder[]
  total: number
  page: number
  page_size: number
  totals: XrayDfwAllOrdersTotals
}

export interface XrayDfwLaneAnalysisTotals {
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  avg_r_per_l: number
  avg_p_per_l: number
  conc_pct: number
  diff_15: number
  diff_18: number
  diff_20: number
}

export interface XrayDfwLaneAnalysisData {
  rows: XrayDfwLaneAnalysisRow[]
  totals: XrayDfwLaneAnalysisTotals
}

// Bruno 2026-06-10: Overview "Last 8 weeks" pop-up — production KPI set per
// Mon-Sun ISO week (mirrors the Ops Portal Overview Team Weekly modal).
export interface XrayDfwWeekPerf {
  start: string
  end: string
  label: string
  customers: number
  lanes: number
  volume: number
  revenue: number
  total_cost: number
  profit: number
  margin_pct: number
  rev_x_l: number
  prof_x_l: number
  team_ut: number
  otp_pct: number
  lates_pu: number
  otd_pct: number
  lates_del: number
}

// ---------------------------------------------------------------------------
// Hooks — every URL is built from the prefix in context so the same hooks
// power the cross-team report (`/reports/xray-dfw-mng`) and the per-team
// reports (`/reports/xray-dfw-tm{1..4}`).
// ---------------------------------------------------------------------------

export function useXrayDfwFilters(view?: XrayDfwView) {
  const prefix = useApiPrefix()
  const qs = view ? `?view=${view}` : ""
  return useQuery({
    ...XRAY_DFW_RETRY,
    queryKey: [prefix, "filters", view ?? "default"],
    queryFn: () => apiFetch<XrayDfwFilterOptions>(`${prefix}/filters${qs}`),
    staleTime: 30 * 60 * 1000,
  })
}

export function useXrayDfwKpis(f: XrayDfwFilters, enabled = true) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "kpis", f],
    queryFn: () => apiFetch<XrayDfwKpis>(`${prefix}/kpis${dfwQs(f)}`),
  })
}

export function useXrayDfwTrio(
  f: Pick<XrayDfwFilters, "subTeams" | "customers" | "lanes" | "view">,
  enabled = true,
) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "trio", f],
    queryFn: () =>
      apiFetch<XrayDfwTrio>(`${prefix}/trio-tables${dfwQs({ range: "full", ...f })}`),
    staleTime: 5 * 60 * 1000,
  })
}

export function useXrayDfwProjection(
  f: Pick<XrayDfwFilters, "subTeams" | "customers" | "lanes" | "view">,
  enabled = true,
) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "projection", f],
    queryFn: () =>
      apiFetch<XrayDfwProjection>(`${prefix}/projection${dfwQs({ range: "full", ...f })}`),
    staleTime: 5 * 60 * 1000,
  })
}

export function useXrayDfwWeeklyPerformance(
  f: Pick<XrayDfwFilters, "subTeams" | "customers" | "lanes" | "view">,
  enabled = true,
) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "weekly-performance", f],
    queryFn: () =>
      apiFetch<{ weeks: XrayDfwWeekPerf[] }>(
        `${prefix}/weekly-performance${dfwQs({ range: "full", ...f })}`,
      ),
    staleTime: 5 * 60 * 1000,
  })
}

export function useXrayDfwByCustomer(f: XrayDfwFilters, enabled = true) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "by-customer", f],
    queryFn: () => apiFetch<XrayDfwCustomerRow[]>(`${prefix}/by-customer${dfwQs(f)}`),
  })
}

export function useXrayDfwByLane(f: XrayDfwFilters, enabled = true) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "by-lane", f],
    queryFn: () => apiFetch<XrayDfwLaneRow[]>(`${prefix}/by-lane${dfwQs(f)}`),
  })
}

export function useXrayDfwAttrition(
  f: Pick<XrayDfwFilters, "subTeams" | "customers" | "lanes" | "view">,
  enabled = true,
) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "attrition", f],
    queryFn: () =>
      apiFetch<XrayDfwAttritionRow[]>(`${prefix}/attrition${dfwQs({ range: "full", ...f })}`),
  })
}

export function useXrayDfwTeamsBreakdown(
  f: Pick<XrayDfwFilters, "customers" | "lanes" | "view">,
  enabled = true,
) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "teams-breakdown", f],
    queryFn: () =>
      apiFetch<XrayDfwTeamBreakdown>(
        `${prefix}/teams-breakdown${dfwQs({ range: "full", ...f })}`,
      ),
  })
}

export function useXrayDfwTrends(
  f: Pick<XrayDfwFilters, "subTeams" | "customers" | "lanes" | "view">,
  enabled = true,
) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "trends", f],
    queryFn: () =>
      apiFetch<XrayDfwTrends>(`${prefix}/trends${dfwQs({ range: "full", ...f })}`),
    staleTime: 5 * 60 * 1000,
  })
}

export function useXrayDfwSummaryTable(
  f: Pick<XrayDfwFilters, "subTeams" | "customers" | "lanes" | "view">,
  enabled = true,
) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "summary-table", f],
    queryFn: () =>
      apiFetch<XrayDfwSummaryTable>(
        `${prefix}/summary-table${dfwQs({ range: "full", ...f })}`,
      ),
    staleTime: 5 * 60 * 1000,
  })
}

export function useXrayDfwRisk(f: XrayDfwFilters, enabled = true) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "risk", f],
    queryFn: () => apiFetch<XrayDfwRisk>(`${prefix}/risk${dfwQs(f)}`),
  })
}

export function useXrayDfwContractSpot(
  f: Pick<XrayDfwFilters, "subTeams" | "customers" | "lanes" | "view">,
  enabled = true,
) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "contract-spot", f],
    queryFn: () =>
      apiFetch<XrayDfwContractSpot>(
        `${prefix}/contract-spot${dfwQs({ range: "full", ...f })}`,
      ),
    staleTime: 5 * 60 * 1000,
  })
}

// Contract vs Spot summary KPIs (Bruno 2026-07-09). Honors the global Range
// bar + all scope filters (parity with the All Orders / Lane Analysis tables),
// so it takes the full `filters` — unlike the 9-week charts above.
export function useXrayDfwContractSpotKpis(f: XrayDfwFilters, enabled = true) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "contract-spot-kpis", f],
    queryFn: () =>
      apiFetch<XrayDfwContractSpotKpis>(`${prefix}/contract-spot-kpis${dfwQs(f)}`),
    staleTime: 5 * 60 * 1000,
  })
}

// Server-paginated (Bruno 2026-06-03, 500/page). `placeholderData` keeps the
// previous page visible while the next one loads (no spinner flash).
/**
 * Server-side default order (Bruno PDF 2026-09-15 R5). ⚠ These tokens are a
 * contract with `_ALL_ORDERS_SORT` in `backend/app/routers/xray_dfw.py`; an
 * unknown one is a 400, not a silent fallback.
 */
export type XrayDfwAllOrdersSort =
  | "departure_desc" | "departure_asc"
  | "order_desc" | "order_asc"
  | "revenue_desc" | "revenue_asc"
  | "profit_desc" | "profit_asc"

export interface XrayDfwAllOrdersOpts {
  /** Server-side ORDER BY. Default `departure_desc` = today's behaviour. */
  sort?: XrayDfwAllOrdersSort
  /**
   * Drop the `total_charge <> 0` filter (Bruno PDF 2026-09-15 R3, GM tab).
   * ⚠ Not cosmetic — it admits unbilled loads whose margin is pure negative
   * carrier pay. Measured for GM on 2026-09-15: MTD 89 → 147 orders, Totals
   * profit $192,837 → $56,462. Defaults false so every other tab is unmoved.
   */
  includeZeroCharge?: boolean
}

export function useXrayDfwAllOrders(
  f: XrayDfwFilters,
  page = 1,
  enabled = true,
  opts: XrayDfwAllOrdersOpts = {},
) {
  const prefix = useApiPrefix()
  const { sort = "departure_desc", includeZeroCharge = false } = opts
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    // ⚠ Both options belong in the key: they change the response, and a key
    // that does not cover every query-string input serves another tab's
    // cached rows under this tab's heading.
    queryKey: [prefix, "all-orders", f, page, sort, includeZeroCharge],
    queryFn: () => {
      const qs = dfwQs(f)
      const sep = qs ? "&" : "?"
      const extra = `page=${page}&sort=${sort}${
        includeZeroCharge ? "&include_zero_charge=true" : ""
      }`
      return apiFetch<XrayDfwAllOrdersPage>(`${prefix}/all-orders${qs}${sep}${extra}`)
    },
    placeholderData: (prev) => prev,
  })
}

export function useXrayDfwLaneAnalysis(f: XrayDfwFilters, enabled = true) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "lane-analysis", f],
    queryFn: () => apiFetch<XrayDfwLaneAnalysisData>(`${prefix}/lane-analysis${dfwQs(f)}`),
  })
}

// ---------------------------------------------------------------------------
// Formatters — re-export from xray-api so both reports stay aligned.
// ---------------------------------------------------------------------------

export { fmtUsd, fmtUsd2, fmtCount, fmtPct } from "@/lib/xray-api"
