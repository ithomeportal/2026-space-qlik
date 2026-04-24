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

// Cap retries at 2 for every XRay hook so a failing endpoint surfaces an
// error state within seconds instead of the Provider's default 5-retry +
// exponential backoff (which silently hides failures for ~1 minute).
const XRAY_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Shared filter contract for XRay CORP Mng
// ---------------------------------------------------------------------------

export type XrayRange = "full" | "ytd" | "custom"

export interface XrayFilters {
  range: XrayRange
  startDate?: string
  endDate?: string
  team?: string
  customer?: string
}

function xrayQs(f: XrayFilters, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  if (f.range) q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  if (f.team) q.set("team", f.team)
  if (f.customer) q.set("customer", f.customer)
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface XrayFilterOptions {
  teams: string[]
  customers: string[]
  year_start: string
  year_end: string
}

export interface XrayKpis {
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

export interface XrayTrioRow {
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

export interface XrayTrio {
  yesterday: { from: string; to: string; totals: XrayTrioRow | null; teams: XrayTrioRow[] }
  week: { from: string; to: string; totals: XrayTrioRow | null; teams: XrayTrioRow[] }
  month: { from: string; to: string; totals: XrayTrioRow | null; teams: XrayTrioRow[] }
}

export interface XrayProjection {
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

export interface XrayCustomerRow {
  customer_name: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
}

export interface XrayLaneRow {
  lane: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
}

export interface XrayAttritionRow {
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

export interface XrayTeamBucket {
  loads: number
  revenue: number
  profit: number
  margin_pct: number
}

export interface XrayTeamBreakdownRow {
  team?: string
  tm: XrayTeamBucket
  tw: XrayTeamBucket
  l1w: XrayTeamBucket
  l2w: XrayTeamBucket
  l3w: XrayTeamBucket
  l4w: XrayTeamBucket
  l5w: XrayTeamBucket
  avg_l5w: XrayTeamBucket
  avg_l5w_minus_lw: XrayTeamBucket
}

export interface XrayTeamBreakdown {
  teams: XrayTeamBreakdownRow[]
  totals: Omit<XrayTeamBreakdownRow, "team">
}

export interface XrayTrendPoint {
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

export interface XrayTrends {
  day: XrayTrendPoint[]
  week: XrayTrendPoint[]
  month: XrayTrendPoint[]
}

export interface XraySummaryRow {
  bucket: string
  lanes: number
  loads: number
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
}

export interface XraySummaryTable {
  months: XraySummaryRow[]
  weeks: XraySummaryRow[]
}

export interface XrayWorstLane {
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

export interface XrayNegOrder {
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

export interface XrayNegCustomer {
  customer: string
  loads: number
  revenue: number
  profit: number
  conc_pct: number
}

export interface XrayLossPoint {
  bucket: string
  loads: number
  profit: number
}

export interface XrayRisk {
  worst_lanes: XrayWorstLane[]
  neg_orders: XrayNegOrder[]
  neg_customers: XrayNegCustomer[]
  losses_month: XrayLossPoint[]
  losses_week: XrayLossPoint[]
}

export interface XrayContractSpotPoint {
  bucket: string
  loads: number
  revenue: number
  profit: number
  margin_pct: number
}

export interface XrayContractSpot {
  contract: XrayContractSpotPoint[]
  spot: XrayContractSpotPoint[]
}

export interface XrayAllOrder {
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

export interface XrayLaneAnalysisRow {
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
// Hooks — filter options shared across all tabs (long stale time)
// ---------------------------------------------------------------------------

export function useXrayFilters() {
  return useQuery({
    ...XRAY_RETRY,
    queryKey: ["xray", "filters"],
    queryFn: () => apiFetch<XrayFilterOptions>("custom/xray-corp/filters"),
    staleTime: 30 * 60 * 1000,
  })
}

export function useXrayKpis(f: XrayFilters, enabled = true) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "kpis", f],
    queryFn: () => apiFetch<XrayKpis>(`custom/xray-corp/kpis${xrayQs(f)}`),
  })
}

export function useXrayTrio(f: Pick<XrayFilters, "team" | "customer">, enabled = true) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "trio", f],
    queryFn: () =>
      apiFetch<XrayTrio>(
        `custom/xray-corp/trio-tables${xrayQs({ range: "full", ...f })}`,
      ),
    staleTime: 5 * 60 * 1000,
  })
}

export function useXrayProjection(
  f: Pick<XrayFilters, "team" | "customer">,
  enabled = true,
) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "projection", f],
    queryFn: () =>
      apiFetch<XrayProjection>(
        `custom/xray-corp/projection${xrayQs({ range: "full", ...f })}`,
      ),
    staleTime: 5 * 60 * 1000,
  })
}

export function useXrayByCustomer(f: XrayFilters, enabled = true) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "by-customer", f],
    queryFn: () => apiFetch<XrayCustomerRow[]>(`custom/xray-corp/by-customer${xrayQs(f)}`),
  })
}

export function useXrayByLane(f: XrayFilters, enabled = true) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "by-lane", f],
    queryFn: () => apiFetch<XrayLaneRow[]>(`custom/xray-corp/by-lane${xrayQs(f)}`),
  })
}

export function useXrayAttrition(
  f: Pick<XrayFilters, "team" | "customer">,
  enabled = true,
) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "attrition", f],
    queryFn: () =>
      apiFetch<XrayAttritionRow[]>(
        `custom/xray-corp/attrition${xrayQs({ range: "full", ...f })}`,
      ),
  })
}

export function useXrayTeamsBreakdown(
  f: Pick<XrayFilters, "customer">,
  enabled = true,
) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "teams-breakdown", f],
    queryFn: () =>
      apiFetch<XrayTeamBreakdown>(
        `custom/xray-corp/teams-breakdown${xrayQs({ range: "full", ...f })}`,
      ),
  })
}

export function useXrayTrends(
  f: Pick<XrayFilters, "team" | "customer">,
  enabled = true,
) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "trends", f],
    queryFn: () =>
      apiFetch<XrayTrends>(`custom/xray-corp/trends${xrayQs({ range: "full", ...f })}`),
    staleTime: 5 * 60 * 1000,
  })
}

export function useXraySummaryTable(
  f: Pick<XrayFilters, "team" | "customer">,
  enabled = true,
) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "summary-table", f],
    queryFn: () =>
      apiFetch<XraySummaryTable>(
        `custom/xray-corp/summary-table${xrayQs({ range: "full", ...f })}`,
      ),
    staleTime: 5 * 60 * 1000,
  })
}

export function useXrayRisk(f: XrayFilters, enabled = true) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "risk", f],
    queryFn: () => apiFetch<XrayRisk>(`custom/xray-corp/risk${xrayQs(f)}`),
  })
}

export function useXrayContractSpot(
  f: Pick<XrayFilters, "team" | "customer">,
  enabled = true,
) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "contract-spot", f],
    queryFn: () =>
      apiFetch<XrayContractSpot>(
        `custom/xray-corp/contract-spot${xrayQs({ range: "full", ...f })}`,
      ),
    staleTime: 5 * 60 * 1000,
  })
}

export function useXrayAllOrders(f: XrayFilters, enabled = true) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "all-orders", f],
    queryFn: () => apiFetch<XrayAllOrder[]>(`custom/xray-corp/all-orders${xrayQs(f)}`),
  })
}

export function useXrayLaneAnalysis(f: XrayFilters, enabled = true) {
  return useQuery({
    ...XRAY_RETRY,
    enabled,
    queryKey: ["xray", "lane-analysis", f],
    queryFn: () => apiFetch<XrayLaneAnalysisRow[]>(`custom/xray-corp/lane-analysis${xrayQs(f)}`),
  })
}

// ---------------------------------------------------------------------------
// Formatters — shared by all tabs
// ---------------------------------------------------------------------------

export const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
export const USD2 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
})
export const COUNT = new Intl.NumberFormat("en-US")
export const PCT1 = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
})

export const fmtUsd = (v?: number | null) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))
export const fmtUsd2 = (v?: number | null) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD2.format(Number(v))
export const fmtCount = (v?: number | null) =>
  v === null || v === undefined ? "—" : COUNT.format(Math.round(Number(v)))
export const fmtPct = (v?: number | null) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : `${PCT1.format(Number(v))}%`
