"use client"

import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { parseLocalDate } from "@/lib/local-date"

// Customer Lifespan (#69, request 2026-10-29). Definitions live in
// backend/app/services/customer_lifespan_core.py + _trends.py — this file only
// fetches and formats. The division is a PATH segment (§100).

const BASE = "custom/customer-lifespan"

export type Division = "all" | "corp" | "dfw"
export type Status = "active" | "at_risk" | "lost"
export type Grain = "month" | "quarter" | "year"
export type RangeKey = "last_365" | "mtd" | "last_month" | "ytd" | "custom" | "all"
export const WINDOWS = [60, 90, 180] as const
export type Window = (typeof WINDOWS)[number]

/** The filter bar. `teams` null = every team; [] = every chip off. */
export interface ReportFilters {
  range: RangeKey
  start: string
  end: string
  teams: string[] | null
  customer: string
}

export const DEFAULT_FILTERS: ReportFilters = { range: "last_365", start: "", end: "", teams: null, customer: "" }

/** Team chips are never comma-split: one repeated param each, as the proxy forwards them. */
export function filtersQuery(f: ReportFilters): string {
  const qs = new URLSearchParams({ range: f.range })
  if (f.range === "custom") {
    qs.set("start", f.start)
    qs.set("end", f.end)
  }
  if (f.teams !== null) {
    if (f.teams.length === 0) qs.append("teams", "")
    f.teams.forEach((t) => qs.append("teams", t))
  }
  if (f.customer) qs.set("customer", f.customer)
  return `&${qs.toString()}`
}

export interface Meta {
  division: Division
  window_days: number
  /** The last day of the selected dates: statuses are judged here. */
  as_of: string
  /** The newest load in the table, whatever the filter. */
  data_as_of: string
  range: RangeKey
  range_label: string
  start: string
  end: string
  grain?: Grain
  total?: number
}

interface Envelope<T> {
  success: boolean
  data: T
  meta: Meta
}

export interface Summary {
  customers_total: number
  customers_in_period: number
  base: number
  active: number
  at_risk: number
  lost: number
  new_period: number
  lost_period: number
  reactivated_period: number
  avg_lifespan_lost: number | null
  median_lifespan_lost: number | null
  avg_lifespan_base: number | null
  revenue_period: number
  margin_period: number
  top10_share: number | null
  first_ship: string | null
}

export interface TrendRow {
  period: string
  active: number
  avg_monthly_active: number
  new: number
  reactivated: number
  lost: number
  net: number
  base: number
  revenue: number
  margin: number
  margin_pct: number | null
  margin_per_active: number | null
  partial: boolean
}

export interface CohortRow {
  cohort: number
  new: number
  base_now: number
  active_now: number
  at_risk_now: number
  lost: number
  retained_pct: number | null
  avg_lifespan_base: number | null
  avg_lifespan_lost: number | null
  revenue: number
  margin: number
  avg_monthly_margin: number | null
  retention: { year: number; customers: number; pct: number | null }[]
}

export interface LifespanData {
  buckets: { bucket: string; active: number; at_risk: number; lost: number; revenue: number }[]
  survival: { points: { month: number; survival: number; at_risk: number }[]; median_months: number | null }
}

/** Team in charge (active / at risk) or Pipedrive Sales Exec. (lost). */
export interface Assignment {
  team: string | null
  assigned_to: string | null
  pending_assignment: boolean
}

export interface CustomerRow extends Assignment {
  customer_id: string
  name: string
  divisions: string[]
  first_ship: string
  last_ship: string
  lifespan_months: number
  lifespan_bucket: string
  age_months: number
  active_months: number
  loads: number
  revenue: number
  margin: number
  margin_pct: number | null
  avg_monthly_margin: number
  reactivations: number
  days_since_last: number
  status: Status
  cohort_year: number
  months_active: string[]
  spark_24m: number[]
}

export interface CustomerDetail extends CustomerRow {
  series: { month: string; loads: number; revenue: number; margin: number; margin_pct: number | null }[]
}

export interface FlowMember extends Assignment {
  customer_id: string
  name: string
  status: Status
  days_since_last: number
  date: string
}

export interface FlowMembers {
  new: FlowMember[]
  reactivated: FlowMember[]
  lost: FlowMember[]
}

export interface BoardTile {
  value: number
  prior: number | null
  delta_pct: number | null
}

export interface BoardRow extends Assignment {
  customer_id: string
  name: string
  status: Status
  age_months: number
  days_since_last: number
  last_ship: string
}

export interface DecliningRow extends Assignment {
  customer_id: string
  name: string
  avg_monthly_loads: number
  loads_30d: number
  change: number
  change_pct: number
}

export interface Board {
  tiles: Record<"active" | "at_risk" | "first_year" | "lost" | "recovered", BoardTile>
  at_risk: (BoardRow & { profit_90d: number })[]
  first_year: BoardRow[]
  declining: DecliningRow[]
  lost: BoardRow[]
  lost_since_returned: number
  recovered: (BoardRow & { returned_on: string })[]
}

export interface FilterOptions {
  teams: string[]
  customers: { customer_id: string; name: string }[]
}

export interface RefreshStatus {
  last_ok_at: string | null
  last_status: string
}

export interface Reconciliation {
  window: [string, string]
  excel_orders: number
  matched: number
  missing_in_datalake: number
  voided_in_datalake: number
  excel_revenue: number
  datalake_revenue: number
  revenue_diff: number
  orders_revenue_off_over_1usd: number
  orders_ship_month_moved: number
  gap_fill_orders: number
  gap_fill_revenue: number
}

export interface Freshness {
  sources: { source: "excel" | "v4"; orders: number; first_ship: string; last_ship: string; voided: number }[]
  excel_last_ship: string
  cutover: string
  reconciliation_window_start: string
  last_sync: { status: string; finished_at: string | null; started_at: string; error: string | null } | null
  last_ok_sync_at: string | null
  reconciliation: string | null
  teams_refresh: RefreshStatus | null
  owners_refresh: RefreshStatus | null
}

async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`/api/proxy/${BASE}/${path}`, { headers: { "Content-Type": "application/json" } })
  if (!res.ok) {
    let detail = ""
    try {
      detail = (await res.json())?.detail ?? ""
    } catch {
      detail = ""
    }
    throw new Error(`API error: ${res.status}${detail ? ` — ${detail}` : ""}`)
  }
  return res.json()
}

// Never retry an auth refusal or a client abort (§43).
const RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b|\b404\b|abort/i.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

function useSection<T>(path: string, enabled = true) {
  return useQuery({
    queryKey: ["customer-lifespan", path],
    queryFn: () => apiGet<T>(path),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
    enabled,
    ...RETRY,
  })
}

const q = (division: Division, section: string, window: Window, f: ReportFilters, extra = "") =>
  `${division}/${section}?window=${window}${extra}${filtersQuery(f)}`

export const useFreshness = () => useSection<{ success: boolean; data: Freshness }>("freshness")
export const useFilterOptions = (d: Division) =>
  useSection<{ success: boolean; data: FilterOptions }>(`${d}/filters`)
export const useSummary = (d: Division, w: Window, f: ReportFilters) =>
  useSection<Envelope<Summary>>(q(d, "summary", w, f))
export const useBoard = (d: Division, w: Window, f: ReportFilters) =>
  useSection<Envelope<Board>>(q(d, "board", w, f))
export const useTrend = (d: Division, w: Window, g: Grain, f: ReportFilters) =>
  useSection<Envelope<TrendRow[]>>(q(d, "trend", w, f, `&grain=${g}`))
export const useFlowMembers = (d: Division, w: Window, g: Grain, period: string | null, f: ReportFilters) =>
  useSection<Envelope<FlowMembers>>(
    q(d, "flow-customers", w, f, `&grain=${g}&period=${encodeURIComponent(period ?? "")}`),
    period !== null,
  )
export const useCohorts = (d: Division, w: Window, f: ReportFilters) =>
  useSection<Envelope<CohortRow[]>>(q(d, "cohorts", w, f))
export const useLifespan = (d: Division, w: Window, f: ReportFilters) =>
  useSection<Envelope<LifespanData>>(q(d, "lifespan", w, f))
export const useCustomers = (d: Division, w: Window, f: ReportFilters) =>
  useSection<Envelope<CustomerRow[]>>(q(d, "customers", w, f))
export const useCustomer = (d: Division, w: Window, id: string | null, f: ReportFilters) =>
  useSection<Envelope<CustomerDetail>>(q(d, `customers/${encodeURIComponent(id ?? "")}`, w, f), id !== null)

// ---------------------------------------------------------------- formatting

const USD0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 })
const USD_COMPACT = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1,
})
const INT = new Intl.NumberFormat("en-US")

const missing = (v: number | null | undefined): v is null | undefined =>
  v === null || v === undefined || Number.isNaN(v)

export const fmtUsd = (v: number | null | undefined) => (missing(v) ? "—" : USD0.format(v))
export const fmtUsdCompact = (v: number | null | undefined) => (missing(v) ? "—" : USD_COMPACT.format(v))
export const fmtInt = (v: number | null | undefined) => (missing(v) ? "—" : INT.format(v))
export const fmtPct = (v: number | null | undefined, digits = 1) => (missing(v) ? "—" : `${v.toFixed(digits)}%`)

/** Months → "3 mo" / "2.5 yrs". */
export function fmtMonths(v: number | null | undefined): string {
  if (missing(v)) return "—"
  return v >= 24 ? `${(v / 12).toFixed(1)} yrs` : `${Math.round(v * 10) / 10} mo`
}

/** One unit for a whole column: always months (deck 2026-11-03). */
export function fmtMo(v: number | null | undefined): string {
  return missing(v) ? "—" : `${v.toFixed(1)} mo`
}

/** "2026 YTD" while that year is still running at the end of the selected dates. */
export function yearLabel(year: number, asOf: string | undefined): string {
  if (!asOf || !asOf.startsWith(String(year)) || asOf.endsWith("-12-31")) return String(year)
  return `${year} YTD`
}

/** "Oct 24, 2026" from a date-only string, parsed as a LOCAL date (§116). */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  return parseLocalDate(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
}

/** "2026-03" → "Mar 2026" without touching Date (§116). */
export function fmtMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number)
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  return m ? `${names[m - 1]} ${y}` : ym
}

export const STATUS_META: Record<Status, { label: string; color: string; chip: string }> = {
  active: { label: "Active", color: "#059669", chip: "bg-[#D1FAE5] text-[#065F46]" },
  at_risk: { label: "At risk", color: "#D97706", chip: "bg-[#FEF3C7] text-[#92400E]" },
  lost: { label: "Lost", color: "#DC2626", chip: "bg-[#FEE2E2] text-[#991B1B]" },
}

export const COLORS = {
  navy: "#1B3A5C",
  new: "#059669",
  reactivated: "#2563EB",
  lost: "#DC2626",
  base: "#1B3A5C",
  active: "#7C3AED",
  revenue: "#94A3B8",
  margin: "#0D9488",
}
