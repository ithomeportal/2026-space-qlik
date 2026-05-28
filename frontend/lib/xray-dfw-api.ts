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

export interface XrayDfwRisk {
  worst_lanes: XrayDfwWorstLane[]
  neg_orders: XrayDfwNegOrder[]
  neg_customers: XrayDfwNegCustomer[]
  losses_month: XrayDfwLossPoint[]
  losses_week: XrayDfwLossPoint[]
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

export interface XrayDfwAllOrder {
  team: string
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

export function useXrayDfwAllOrders(f: XrayDfwFilters, enabled = true) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "all-orders", f],
    queryFn: () => apiFetch<XrayDfwAllOrder[]>(`${prefix}/all-orders${dfwQs(f)}`),
  })
}

export function useXrayDfwLaneAnalysis(f: XrayDfwFilters, enabled = true) {
  const prefix = useApiPrefix()
  return useQuery({
    ...XRAY_DFW_RETRY,
    enabled,
    queryKey: [prefix, "lane-analysis", f],
    queryFn: () => apiFetch<XrayDfwLaneAnalysisRow[]>(`${prefix}/lane-analysis${dfwQs(f)}`),
  })
}

// ---------------------------------------------------------------------------
// Formatters — re-export from xray-api so both reports stay aligned.
// ---------------------------------------------------------------------------

export { fmtUsd, fmtUsd2, fmtCount, fmtPct } from "@/lib/xray-api"
