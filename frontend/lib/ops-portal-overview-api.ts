"use client"

import { createContext, createElement, useContext, type ReactNode } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"

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
  // Keep showing the previous result (dimmed) while a filter change refetches,
  // instead of every panel blanking to a spinner / "Failed to load" at once.
  // This both removes the visible flash and lets a slow/cold backend catch up
  // without the user perceiving a failure.
  placeholderData: keepPreviousData,
}

// ---------------------------------------------------------------------------
// API prefix context — default points at the cross-team
// `/custom/ops-portal-overview` router. Per-team pages
// (e.g. /reports/corp-t1-ops-kam-portal) wrap their content in
// <OppApiProvider prefix="custom/ops-portal-overview-t1"> so every hook below
// transparently hits the team-locked endpoints. The prefix is also baked into
// every queryKey so the 4 team copies cache independently of each other and of
// the cross-team report.
// ---------------------------------------------------------------------------

const DEFAULT_PREFIX = "custom/ops-portal-overview"

const ApiPrefixContext = createContext<string>(DEFAULT_PREFIX)

export function OppApiProvider({
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

// Bruno R5 (2026-06-01): "full" dropped from the UI but kept here as the
// silent default for the rolling endpoints (combo/service/projection/gauge).
// Bruno (PDF 2026-07-20) R2: "ytd" dropped from the UI in favour of
// "yesterday". The backend still honours range=ytd for stale clients, but no
// button produces it any more, so it is off the union.
export type OppRange = "mtd" | "yesterday" | "this_month" | "last_month" | "full" | "custom"
export type LoadType = "" | "contract" | "spot"

export interface OppFilters {
  range: OppRange
  startDate?: string
  endDate?: string
  team?: string
  customer?: string
  loadType?: LoadType
  /** Bruno R5: "Losses" button — restrict tables to margin_amt < 0 rows. */
  lossesOnly?: boolean
  /** Bruno (PDF 2026-07-13): "Unbilled" button — restrict to bill_date < sentinel. */
  unbilledOnly?: boolean
  /** Bruno R7 (2026-06-05): Lane multi-select — include list. */
  lanes?: string[]
  /** Bruno R7: Lane multi-select — exclude list (mode toggle). */
  excludeLanes?: string[]
  /** Bruno (PDF 2026-07-15) R1: Carrier multi-select — include list. */
  carriers?: string[]
  /** Bruno (PDF 2026-07-15) R1: Carrier multi-select — exclude list. */
  excludeCarriers?: string[]
}

/** Stable queryKey fragment for the lane + carrier arrays. */
function laneKey(
  f: Pick<OppFilters, "lanes" | "excludeLanes" | "carriers" | "excludeCarriers">,
): string {
  return (
    `${(f.lanes ?? []).join("|")}~${(f.excludeLanes ?? []).join("|")}` +
    `~${(f.carriers ?? []).join("|")}~${(f.excludeCarriers ?? []).join("|")}`
  )
}

function qs(f: OppFilters, extra?: Record<string, string>): string {
  const q = new URLSearchParams()
  if (f.range) q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  if (f.team) q.set("team", f.team)
  if (f.customer) q.set("customer", f.customer)
  if (f.loadType) q.set("load_type", f.loadType)
  if (f.lossesOnly) q.set("losses_only", "true")
  if (f.unbilledOnly) q.set("unbilled_only", "true")
  for (const lane of f.lanes ?? []) q.append("lanes", lane)
  for (const lane of f.excludeLanes ?? []) q.append("exclude_lanes", lane)
  for (const c of f.carriers ?? []) q.append("carriers", c)
  for (const c of f.excludeCarriers ?? []) q.append("exclude_carriers", c)
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
  /** Bruno R7: distinct "origin - dest" lane keys (YTD scope). */
  lanes: string[]
  /** Bruno (PDF 2026-07-15) R1: distinct carrier names (YTD scope). */
  carriers: string[]
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

export type OppGrain = "day" | "week" | "month"

export interface OppBucket {
  bucket_start: string
  volume: number
  revenue: number
  profit: number
  margin_pct: number
  // Per-tab losses variants (Bruno round 3, 2026-05-19).
  losses_vol: number
  losses_rev: number
  losses_prof: number
  losses_margin_pct: number
  // Per-tab budget variants.
  budget_loads: number
  budget_revenue: number
  budget_profit: number
  budget_margin_pct: number
}

export interface OppCombo {
  grain: OppGrain
  buckets: OppBucket[]
  projected_vol: number
  projected_revenue: number
  projected_profit: number
  projected_margin_pct: number
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

// Bruno 2026-07-01 R14: per-customer "Not Billed" (bill_date < sentinel).
export interface OppCustomerNotBilledRow {
  customer_name: string
  loads: number
  revenue: number
}
export interface OppCustomerNotBilledTotals {
  loads: number
  revenue: number
}

export interface OppTeamPerformance {
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
  savings: number
  over_pay: number
  net_savings: number
  loss_loads: number
  profit_loss: number
  /** Bruno 2026-07-01 R12 — below Profit Loss. */
  avg_days_billed: number
  avg_days_not_billed: number
  pct_del_bill: number
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

export interface OppLaneRow {
  lane: string
  origin: string
  dest: string
  vol: number
  /** Bruno 2026-07-01 R3: distinct carriers on the lane (COUNT DISTINCT payee_name). */
  carriers: number
  rev: number
  prof: number
  margin_pct: number
  loss_loads: number
  loss_profit: number
  otp_pct: number
  otd_pct: number
  rev_x_l: number
  prof_x_l: number
}

// Bruno R4 (2026-05-27): totals rows surfaced in meta for the bottom tables.
export interface OppActualsTotals {
  vol: number; vol_budget: number; vol_var: number
  rev: number; rev_budget: number; rev_var: number
  prof: number; prof_budget: number; prof_var: number
  margin_pct: number; margin_budget_pct: number; margin_var_pct: number
  otp_pct: number; otd_pct: number; rev_x_l: number; prof_x_l: number
  // Bruno (PDF 2026-07-23) R4: TOTAL-row sums for the 4 projection columns.
  vol_x_day: number; prof_x_day: number
  proj_eom_vol: number; proj_eom_prof: number
}

export interface OppLaneTotals {
  vol: number; carriers: number; rev: number; prof: number; margin_pct: number
  loss_loads: number; loss_profit: number
  otp_pct: number; otd_pct: number; rev_x_l: number; prof_x_l: number
}

export interface OppOrderTotals {
  n_orders: number; revenue: number; profit: number; margin_pct: number
}

// Bruno R4: per-bucket OTP/OTD time series ("Service" KPI MANAGEMENT chart).
export interface OppServiceBucket {
  bucket_start: string
  volume: number
  otp_pct: number
  otd_pct: number
  lates_pu: number
  lates_del: number
}
export interface OppService {
  grain: OppGrain
  buckets: OppServiceBucket[]
  today: string
}

// Bruno R4: load-level Production rows ("By Order" table).
// Bruno R5 (2026-06-01): + OTP/OTD %, Transit Time, in-progress live timer.
export interface OppOrderRow {
  order_id: string
  team_id: string
  status: string
  departure: string
  customer_name: string
  /** Bruno 2026-07-01 R2: carrier (movement.payee_name), '' if unmatched. */
  carrier: string
  lane: string
  revenue: number
  profit: number
  margin_pct: number
  otp_pct: number
  otd_pct: number
  /** ISO timestamp the load departed origin (sentinel-guarded, may be null). */
  departed_at: string | null
  /** ISO timestamp the load arrived destination (null while in transit). */
  arrived_at: string | null
  /** Completed transit seconds (arrival − departure); null if unknown. */
  transit_seconds: number | null
  /** Open 'P' load that departed but has not arrived — UI ticks a live clock. */
  in_progress: boolean
  /** Bruno 2026-07-01 R11: bill_date > sentinel → billed (checkmark). */
  billed: boolean
  /** Bruno 2026-07-01 R11: bill_date − dest departure (or NOW − departure). */
  days_to_bill: number | null
  /** Bruno (PDF 2026-07-13): order already has a POD Tracker document. */
  pod: boolean
  /** Bruno (PDF 2026-07-15) R14: hours since delivery — shown (green<24/red>24)
   *  only for orders lacking a POD. Null when no delivery timestamp. */
  pod_age_hours: number | null
}

// Bruno (PDF 2026-07-15) R16: "Pending to Cover" — status='A', no carrier yet.
export interface OppPendingRow {
  order_id: string
  team_id: string
  /** Bruno (PDF 2026-07-30) R2: Customer, between Team and Orig Sched Early. */
  customer_name: string
  lane: string
  revenue: number
  /** ISO orig scheduled early/late pickup (customer_windows); may be null. */
  orig_sched_early: string | null
  orig_sched_late: string | null
  /** Hours remaining until the late pickup deadline (Orig Sched Late − now). */
  time_to_cover_hours: number | null
}

// Bruno (PDF 2026-07-20) R1: "Cover" — every status='A' load (superset of
// Pending to Cover, which is only the status='A' loads with no carrier).
export interface OppCoverRow {
  order_id: string
  team_id: string
  customer_name: string
  /** First-movement payee_name; '' when no carrier is assigned yet. */
  carrier: string
  /**
   * First-movement `override_driver_nm` — Bruno (PDF 2026-08-12) R2's new
   * **"Driver Name"** column, rendered between Carrier and Carrier Phone.
   * Free text in McLeod; '' on ~75% of covered loads (28/112 measured).
   */
  driver_name: string
  /**
   * First-movement **`override_drvr_cell`** — Bruno (PDF 2026-08-12) R1 replaced
   * the old `movement.carrier_phone` source here. The wire name is deliberately
   * unchanged (§34 inverted: the header still reads "Carrier Phone", only the
   * source column moved). '' on ~77% of covered loads (26/112 measured, down
   * from 59/112 under carrier_phone — an accepted, requested regression).
   * Free text: values like "TBD" / "x" / "will advise" occur, so never assume
   * this is dialable.
   */
  carrier_phone: string
  /** ISO orig scheduled early/late pickup (customer_windows); may be null. */
  orig_sched_early: string | null
  /**
   * `customer_windows.orig_orig_sched_late`. Bruno (PDF 2026-07-30) R3 relabels
   * this column **"Orig Orig Late"** — the wire name is deliberately unchanged
   * (§34: no mid-flight rename), only the header moved.
   */
  orig_sched_late: string | null
  /**
   * `customer_windows.orig_sched_arrive_late` — Bruno (PDF 2026-07-30) R3's new
   * **"Orig Sched Late"** column, and the board's default sort. Populated on
   * 94.6% of open loads vs 65% for `orig_sched_late`.
   */
  orig_sched_arrive_late: string | null
  lane: string
  revenue: number
  /** `total_carrier_pay` — reconciles to revenue − profit within $1 (rounding). */
  carrier_cost: number
  profit: number
  /** profit / revenue × 100, computed server-side so it agrees with both (§16). */
  margin_pct: number
}

// Bruno (PDF 2026-07-30) R4: the "Forecast" pill — Cover totals bucketed on
// `orig_sched_arrive_late`, stacked on top of the Production bars in KPI
// Management. Buckets can run past today's period (open loads scheduled for
// next month), so the chart appends any bucket /combo doesn't already carry.
export interface OppCoverForecastBucket {
  bucket_start: string
  cover_vol: number
  cover_rev: number
  cover_prof: number
}

/** §44 pinned Totals for the Cover board — server-side, full-universe. */
/**
 * A row on the **Hold** board (Bruno PDF 2026-08-19 R1).
 *
 * NOT date-windowed: `on_hold='Y' AND status NOT IN ('V','A')` matches ~18 rows
 * in the whole table, stuck for months at a time, so a date filter would hide
 * exactly the stale rows the board exists to surface.
 *
 * Bruno PDF 2026-08-20 R2 changed the rule from `on_hold='Y'` to "not billed"
 * (`bill_date` below McLeod's 1900-01-01 sentinel), with a hard floor at
 * `meta.unbilled_from` — the 2021 feed never wrote bill_date, so without the
 * floor ~58,500 phantom rows bury the ~570 real ones. `on_hold` survives as a
 * displayed column. Division-scoped: CORP on the five CORP portals, TEAM-DFW
 * on Ops Managers Portal – DFW.
 */
export interface OppHoldRow {
  order_id: string
  team_id: string
  /** 'D' or 'P' today; the endpoint excludes 'V'/'A' rather than allow-listing. */
  status: string
  /** `origin_actual_departure`, YYYY-MM-DD. Back since PDF 2026-08-24 R1;
   *  null when McLeod held its 1900-01-01 sentinel. */
  departure: string | null
  /** Bruno PDF 2026-08-24 R1 — "Delay Time", replacing `date_days`. DAYS, and
   *  NEGATIVE = overdue. Non-null only on status 'P' rows whose scheduled
   *  delivery has already passed, so most rows are legitimately null. */
  delay_days: number | null
  /** `dest_sched_arrive_late`, CST wall-clock ISO. Null when absent. */
  sched_dest_late: string | null
  /** `dest_actual_departure`, CST wall-clock ISO. Null on virtually every
   *  in-progress row — the load has not delivered yet. */
  actual_delivery: string | null
  customer_name: string
  carrier: string
  lane: string
  revenue: number
  /** `total_carrier_pay`, same source as the Cover board — NOT revenue − profit.
   *  Still served; the TABLE dropped the column on PDF 2026-08-24 R1, but the
   *  totals row still sums it. */
  carrier_cost: number
  profit: number
  margin_pct: number
  /** Always true given the filter; rendered from the data, not assumed. */
  on_hold: boolean
  /** Free text, varchar(20), mixed case ('CLAIM', 'accident'). Shown verbatim. */
  hold_reason: string
  pod: boolean
  pod_age_hours: number | null
  days_to_bill: number | null
  /** null when unbilled — McLeod's 1900-01-01 sentinel is stripped server-side. */
  bill_date: string | null
  billed: boolean
}

export interface OppHoldTotals {
  n_orders: number
  revenue: number
  carrier_cost: number
  profit: number
  margin_pct: number
}

export interface OppCoverTotals {
  n_orders: number
  revenue: number
  carrier_cost: number
  profit: number
  margin_pct: number
}

export interface OppCoverMeta {
  returned: number
  limit: number
  /** Whole status='A' universe (covered + not covered). */
  total: number
  /** The carrier-assigned subset the board actually renders. */
  covered: number
  totals: OppCoverTotals
}

/** "Data as of …" — headline is the STALEST source, not the newest. */
export interface OppFreshnessSource {
  key: string
  label: string
  updated_at: string | null
  age_minutes: number | null
}

export interface OppFreshness {
  sources: OppFreshnessSource[]
  as_of: string | null
  age_minutes: number | null
  stalest: string | null
  checked_at: string
}

// Bruno R4: "Team Weekly Performance" modal — last 5 Mon-Sun weeks.
export interface OppWeekPerf {
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
  savings: number
  over_pay: number
  net_savings: number
  loss_loads: number
  profit_loss: number
  cust_attr_pct: number
  lane_attr_pct: number
}

// Per-team breakdown of Team Performance (one row per team_id + a Total).
export interface OppTeamPerfByTeam {
  total: OppTeamPerformance
  teams: (OppTeamPerformance & { team_id: string })[]
}

// Per-customer service-fail breakdown ("On time P&D" incident table).
export interface OppServiceIncidentRow {
  customer_name: string
  orders: number
  fail: number
  pct_on_time: number
}

export interface OppServiceIncidentTotals {
  orders: number
  fail: number
  pct_on_time: number
}

// Bruno (PDF 2026-07-15) R8: "by Carrier" table — Vol / %Vol / OTP / OTD.
export interface OppServiceByCarrierRow {
  carrier: string
  vol: number
  pct_vol: number
  otp_pct: number
  otd_pct: number
}

// Margin-bucket distribution (orders + revenue + profit per margin band).
export interface OppMarginBucket {
  bucket: string
  orders: number
  revenue: number
  /** Bruno (PDF 2026-07-13): Profit total (SUM(margin_amt)) per bucket. */
  profit: number
}

// Bruno (PDF 2026-07-13): Week / Team breakouts of the Team Budget Variance
// and Team Monthly Projection panels.
export interface OppTeamVarianceWeek extends OppTeamVariance {
  start: string
  end: string
  label: string
}
export interface OppTeamVarianceByTeam {
  total: OppTeamVariance
  teams: (OppTeamVariance & { team_id: string })[]
}
export interface OppTeamProjectionWeek {
  start: string
  end: string
  label: string
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
}
export interface OppTeamProjectionByTeam {
  total: OppTeamProjection
  teams: (OppTeamProjection & { team_id: string })[]
}

// ---------------------------------------------------------------------------
// Team Monthly Projection history — request 2026-08-25 ("as the stock markets")
// ---------------------------------------------------------------------------
// `tracked` is false when the panel carries a customer / lane / carrier /
// load-type filter, or when the team selection is not one of the scopes we
// snapshot. History is UNFILTERED, so showing a High/Low next to a filtered
// number would put a range beside a population it does not describe.

export interface OppProjectionPoint {
  as_of_date: string
  proj_profit: number
  proj_revenue: number
  proj_volume: number
  proj_margin_pct: number
  pending_workdays: number
  /** "live" = observed that morning; "backfill" = replayed from v4. */
  source: "live" | "backfill"
}

export interface OppProjectionMonthStats {
  open: number | null
  close: number | null
  high: number | null
  low: number | null
  high_date: string | null
  low_date: string | null
  range_pct: number | null
  latest: number | null
  prev: number | null
  chg_pct: number | null
  settled_high: number | null
  settled_low: number | null
  settled_range_pct: number | null
  settled_from_business_day: number
  days: number
  backfilled_days: number
  points: OppProjectionPoint[]
}

export interface OppProjectionMonthRow {
  month_start: string
  open: number | null
  close: number | null
  high: number
  low: number
  range_pct: number | null
  days: number
  live_days: number
  actual_profit: number | null
  error_pct: number | null
  high_error_pct: number | null
  low_error_pct: number | null
}

export interface OppProjectionHistory {
  scope_key: string
  team_key: string | null
  today: string
  month_start: string
  month_end: string
  live_proj_profit: number
  tracked: boolean
  untracked_reason?: "filtered" | "team_scope"
  current_month: OppProjectionMonthStats | null
  months: OppProjectionMonthRow[]
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useOppFilters() {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-filters"],
    queryFn: () => apiFetch<OppFilterOptions>(`${prefix}/filters`),
    staleTime: 60 * 60 * 1000,
    ...RETRY,
  })
}

export function useOppWorkdays() {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-workdays"],
    queryFn: () => apiFetch<OppWorkdays>(`${prefix}/workdays`),
    staleTime: 30 * 60 * 1000,
    ...RETRY,
  })
}

export function useOppCombo(
  f: Pick<OppFilters, "team" | "customer" | "loadType" | "lanes" | "excludeLanes" | "carriers" | "excludeCarriers">,
  grain: OppGrain = "month",
) {
  const prefix = useApiPrefix()
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    queryKey: [prefix, "opp-combo", grain, f.team || "", f.customer || "", f.loadType || "", laneKey(f)],
    queryFn: () => apiFetch<OppCombo>(`${prefix}/combo${qs(filters, { grain })}`),
    ...RETRY,
  })
}

export function useOppTeamVariance(f: OppFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-team-variance", f.range, f.startDate, f.endDate, f.team, f.customer],
    queryFn: () => apiFetch<OppTeamVariance>(`${prefix}/team-variance${qs(f)}`),
    ...RETRY,
  })
}

export function useOppCustomerVariance(f: OppFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-customer-variance", f.range, f.startDate, f.endDate, f.team, f.customer],
    queryFn: () => apiFetch<OppCustomerVariance[]>(`${prefix}/customer-variance${qs(f)}`),
    ...RETRY,
  })
}

export function useOppCustomerLosses(f: OppFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-customer-losses", f.range, f.startDate, f.endDate, f.team, f.customer, f.loadType, laneKey(f)],
    queryFn: () => apiFetch<OppCustomerLoss[]>(`${prefix}/customer-losses${qs(f)}`),
    ...RETRY,
  })
}

export function useOppTeamPerformance(f: OppFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-team-performance", f.range, f.startDate, f.endDate, f.team, f.customer, f.loadType, laneKey(f)],
    queryFn: () => apiFetch<OppTeamPerformance>(`${prefix}/team-performance${qs(f)}`),
    ...RETRY,
  })
}

// Bruno 2026-07-01 R14: per-customer "Not Billed" table (meta.totals carries
// the full-universe Loads/Revenue totals).
export function useOppCustomerNotBilled(f: OppFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-customer-not-billed", f.range, f.startDate, f.endDate, f.team, f.customer, f.loadType, laneKey(f)],
    queryFn: () => apiFetch<OppCustomerNotBilledRow[]>(`${prefix}/customer-not-billed${qs(f)}`),
    ...RETRY,
  })
}

export function useOppTeamProjection(f: Pick<OppFilters, "team" | "customer" | "loadType" | "lanes" | "excludeLanes" | "carriers" | "excludeCarriers">) {
  const prefix = useApiPrefix()
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    queryKey: [prefix, "opp-team-projection", f.team || "", f.customer || "", f.loadType || "", laneKey(f)],
    queryFn: () => apiFetch<OppTeamProjection>(`${prefix}/team-projection${qs(filters)}`),
    ...RETRY,
  })
}

export function useOppProfitTmGauge(f: Pick<OppFilters, "team" | "customer" | "loadType" | "lanes" | "excludeLanes" | "carriers" | "excludeCarriers">) {
  const prefix = useApiPrefix()
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    queryKey: [prefix, "opp-profit-tm-gauge", f.team || "", f.customer || "", f.loadType || "", laneKey(f)],
    queryFn: () => apiFetch<OppProfitTmGauge>(`${prefix}/profit-tm-gauge${qs(filters)}`),
    ...RETRY,
  })
}

export function useOppActuals(f: OppFilters, opts?: { sort?: string; limit?: number }) {
  const prefix = useApiPrefix()
  const sort = opts?.sort ?? "revenue_desc"
  const limit = opts?.limit ?? 100
  return useQuery({
    queryKey: [
      prefix, "opp-actuals",
      f.range, f.startDate, f.endDate,
      f.team, f.customer, f.loadType, f.lossesOnly ?? false, f.unbilledOnly ?? false, laneKey(f),
      sort, limit,
    ],
    queryFn: () =>
      apiFetch<OppActualsRow[]>(
        `${prefix}/actuals${qs(f, { sort, limit: String(limit) })}`,
      ),
    ...RETRY,
  })
}

export function useOppActualsByLane(
  f: OppFilters,
  opts?: { sort?: string; limit?: number },
) {
  const prefix = useApiPrefix()
  const sort = opts?.sort ?? "revenue_desc"
  const limit = opts?.limit ?? 100
  return useQuery({
    queryKey: [
      prefix, "opp-actuals-by-lane",
      f.range, f.startDate, f.endDate,
      f.team, f.customer, f.loadType, f.lossesOnly ?? false, f.unbilledOnly ?? false, laneKey(f),
      sort, limit,
    ],
    queryFn: () =>
      apiFetch<OppLaneRow[]>(
        `${prefix}/actuals-by-lane${qs(f, { sort, limit: String(limit) })}`,
      ),
    ...RETRY,
  })
}

// Bruno R4: "Service" KPI MANAGEMENT chart — OTP/OTD over the grain.
export function useOppService(
  f: Pick<OppFilters, "team" | "customer" | "loadType" | "lanes" | "excludeLanes" | "carriers" | "excludeCarriers">,
  grain: OppGrain = "month",
) {
  const prefix = useApiPrefix()
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    queryKey: [prefix, "opp-service", grain, f.team || "", f.customer || "", f.loadType || "", laneKey(f)],
    queryFn: () => apiFetch<OppService>(`${prefix}/service${qs(filters, { grain })}`),
    ...RETRY,
  })
}

// Bruno R4: "By Order" load-level table — server-side sort on every column.
export function useOppByOrder(
  f: OppFilters,
  opts?: { sort?: string; limit?: number },
) {
  const prefix = useApiPrefix()
  const sort = opts?.sort ?? "revenue_desc"
  const limit = opts?.limit ?? 500
  return useQuery({
    queryKey: [
      prefix, "opp-by-order",
      f.range, f.startDate, f.endDate,
      f.team, f.customer, f.loadType, f.lossesOnly ?? false, f.unbilledOnly ?? false, laneKey(f),
      sort, limit,
    ],
    queryFn: () =>
      apiFetch<OppOrderRow[]>(
        `${prefix}/by-order${qs(f, { sort, limit: String(limit) })}`,
      ),
    ...RETRY,
  })
}

// The status='A' board endpoints (/pending-to-cover, /cover) are NOT
// date-windowed and ignore load_type / losses_only / unbilled_only. Previously
// they passed the whole filter to `qs()`, which serialised those fields into
// the URL while the queryKey omitted them — so two genuinely different requests
// collapsed onto one cache entry and served stale rows after a range or
// Unbilled toggle. Narrowing the query string to exactly the fields the
// endpoints honour makes URL and cache key agree by construction.
function scopeQs(f: OppFilters, extra?: Record<string, string>): string {
  const scoped = {
    team: f.team,
    customer: f.customer,
    lanes: f.lanes,
    excludeLanes: f.excludeLanes,
  } as OppFilters
  return qs(scoped, extra)
}

function scopeKey(f: OppFilters): unknown[] {
  return [f.team, f.customer, laneKey(f)]
}

// Bruno (PDF 2026-07-15) R16: "Pending to Cover" — status='A', no carrier.
// Not date-windowed; respects team / customer / lane filters. `enabled` so the
// fetch only fires when the By Order panel is on the Pending-to-Cover view.
export function useOppPendingToCover(f: OppFilters, enabled: boolean) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-pending-to-cover", ...scopeKey(f)],
    queryFn: () => apiFetch<OppPendingRow[]>(`${prefix}/pending-to-cover${scopeQs(f)}`),
    enabled,
    ...RETRY,
  })
}

// Bruno (PDF 2026-07-20) R1: "Cover" — every status='A' load, with carrier +
// carrier phone and the orig scheduled pickup window. Same scope contract as
// Pending to Cover: not date-windowed, `enabled` so it only fires on that view.
// Bruno PDF 2026-08-19 R1 — the Hold board. `scopeQs`/`scopeKey` (NOT `qs`):
// the endpoint declares no date params, and serialising fields it ignores is
// what previously collapsed two different requests onto one cache entry.
export function useOppHold(f: OppFilters, opts?: { sort?: string }) {
  const prefix = useApiPrefix()
  // Must track hold.py's default — a key the whitelist no longer holds would
  // silently fall back to it instead of erroring (§ dead sort key).
  const sort = opts?.sort ?? "delay_asc"
  return useQuery({
    queryKey: [prefix, "opp-hold", ...scopeKey(f), sort],
    queryFn: () =>
      apiFetch<OppHoldRow[]>(`${prefix}/hold${scopeQs(f, { sort })}`),
    ...RETRY,
  })
}

export function useOppCover(f: OppFilters, enabled: boolean) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-cover", ...scopeKey(f)],
    queryFn: () => apiFetch<OppCoverRow[]>(`${prefix}/cover${scopeQs(f)}`),
    enabled,
    ...RETRY,
  })
}

// "Data as of …" for the page header. Refetched on an interval because the
// whole point is noticing when a feed stops moving; backend caches 60s so the
// poll is nearly free.
export function useOppFreshness() {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-data-freshness"],
    queryFn: () => apiFetch<OppFreshness>(`${prefix}/data-freshness`),
    refetchInterval: 120_000,
    ...RETRY,
  })
}

// Bruno (PDF 2026-07-30) R4: Cover totals per chart bucket, for the "Forecast"
// pill in KPI Management. Same filter contract as /combo so the two agree;
// `enabled` keeps the default (Forecast off) page load unchanged.
export function useOppCoverForecast(
  f: Pick<OppFilters, "team" | "customer" | "loadType" | "lanes" | "excludeLanes" | "carriers" | "excludeCarriers">,
  grain: OppGrain,
  enabled: boolean,
) {
  const prefix = useApiPrefix()
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    // §50: the key covers every field qs() serialises for this call.
    queryKey: [prefix, "opp-cover-forecast", grain, f.team || "", f.customer || "", f.loadType || "", laneKey(f)],
    queryFn: () =>
      apiFetch<{ grain: OppGrain; buckets: OppCoverForecastBucket[]; unscheduled: number }>(
        `${prefix}/cover-forecast${qs(filters, { grain })}`,
      ),
    enabled,
    ...RETRY,
  })
}

// Bruno R4: "Team Weekly Performance" modal data.
export function useOppTeamWeekly(
  f: Pick<OppFilters, "team" | "customer" | "loadType" | "lanes" | "excludeLanes" | "carriers" | "excludeCarriers">,
  enabled: boolean,
) {
  const prefix = useApiPrefix()
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    queryKey: [prefix, "opp-team-weekly", f.team || "", f.customer || "", f.loadType || "", laneKey(f)],
    queryFn: () => apiFetch<{ weeks: OppWeekPerf[] }>(`${prefix}/team-weekly-performance${qs(filters)}`),
    enabled,
    ...RETRY,
  })
}

// Per-team breakdown of the Team Performance table (Total + one row per team).
export function useOppTeamPerformanceByTeam(f: OppFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-team-performance-by-team", f.range, f.startDate, f.endDate, f.team, f.customer, f.loadType, laneKey(f)],
    queryFn: () => apiFetch<OppTeamPerfByTeam>(`${prefix}/team-performance-by-team${qs(f)}`),
    ...RETRY,
  })
}

// Per-customer service-fail breakdown by stop type (Pickup or Delivery).
export function useOppServiceIncident(f: OppFilters, stopType: "pu" | "del") {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [
      prefix, "opp-service-incident",
      stopType,
      f.range, f.startDate, f.endDate, f.team, f.customer, f.loadType, laneKey(f),
    ],
    queryFn: () =>
      apiFetch<OppServiceIncidentRow[]>(
        `${prefix}/service-incident-by-customer${qs(f, { stop_type: stopType })}`,
      ),
    ...RETRY,
  })
}

// Bruno (PDF 2026-07-15) R8: per-carrier Vol / %Vol / OTP / OTD.
export function useOppServiceByCarrier(f: OppFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [
      prefix, "opp-service-by-carrier",
      f.range, f.startDate, f.endDate, f.team, f.customer, f.loadType, laneKey(f),
    ],
    queryFn: () =>
      apiFetch<OppServiceByCarrierRow[]>(`${prefix}/service-by-carrier${qs(f)}`),
    ...RETRY,
  })
}

// Margin-band distribution (orders + revenue per bucket).
export function useOppMarginDistribution(f: OppFilters) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-margin-distribution", f.range, f.startDate, f.endDate, f.team, f.customer, f.loadType, laneKey(f)],
    queryFn: () => apiFetch<OppMarginBucket[]>(`${prefix}/margin-distribution${qs(f)}`),
    ...RETRY,
  })
}

// Bruno (PDF 2026-07-13): Week / Team breakouts (lazy — only fetched when the
// modal opens). Variance-weekly + projection variants use a fixed rolling
// window, so they carry no date range in the querystring.
export function useOppTeamVarianceWeekly(f: OppFilters, enabled: boolean) {
  const prefix = useApiPrefix()
  const filters: OppFilters = { range: "full", team: f.team, customer: f.customer }
  return useQuery({
    queryKey: [prefix, "opp-team-variance-weekly", f.team || "", f.customer || ""],
    queryFn: () => apiFetch<{ weeks: OppTeamVarianceWeek[] }>(`${prefix}/team-variance-weekly${qs(filters)}`),
    enabled,
    ...RETRY,
  })
}

export function useOppTeamVarianceByTeam(f: OppFilters, enabled: boolean) {
  const prefix = useApiPrefix()
  return useQuery({
    queryKey: [prefix, "opp-team-variance-by-team", f.range, f.startDate, f.endDate, f.customer || ""],
    queryFn: () => apiFetch<OppTeamVarianceByTeam>(`${prefix}/team-variance-by-team${qs(f)}`),
    enabled,
    ...RETRY,
  })
}

export function useOppTeamProjectionHistory(
  f: Pick<OppFilters, "team" | "customer" | "loadType" | "lanes" | "excludeLanes" | "carriers" | "excludeCarriers">,
  enabled = true,
  months = 13,
) {
  const prefix = useApiPrefix()
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    // ⚠ The key must cover everything qs() emits — `months` included. The
    // panel strip and the Trend modal both take the default, so they share one
    // cache entry and the modal opens without a second round trip; omit
    // `months` from the key and the day someone varies it they would silently
    // read each other's response.
    queryKey: [prefix, "opp-team-projection-history", f.team || "", f.customer || "", f.loadType || "", laneKey(f), months],
    queryFn: () =>
      apiFetch<OppProjectionHistory>(
        `${prefix}/team-projection-history${qs(filters, { months: String(months) })}`,
      ),
    enabled,
    ...RETRY,
  })
}

export function useOppTeamProjectionWeekly(
  f: Pick<OppFilters, "team" | "customer" | "loadType" | "lanes" | "excludeLanes" | "carriers" | "excludeCarriers">,
  enabled: boolean,
) {
  const prefix = useApiPrefix()
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    queryKey: [prefix, "opp-team-projection-weekly", f.team || "", f.customer || "", f.loadType || "", laneKey(f)],
    queryFn: () => apiFetch<{ weeks: OppTeamProjectionWeek[] }>(`${prefix}/team-projection-weekly${qs(filters)}`),
    enabled,
    ...RETRY,
  })
}

export function useOppTeamProjectionByTeam(
  f: Pick<OppFilters, "team" | "customer" | "loadType" | "lanes" | "excludeLanes" | "carriers" | "excludeCarriers">,
  enabled: boolean,
) {
  const prefix = useApiPrefix()
  const filters: OppFilters = { range: "full", ...f }
  return useQuery({
    queryKey: [prefix, "opp-team-projection-by-team", f.customer || "", f.loadType || "", laneKey(f)],
    queryFn: () => apiFetch<OppTeamProjectionByTeam>(`${prefix}/team-projection-by-team${qs(filters)}`),
    enabled,
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

// Bruno R5: Transit Time / live in-transit timer → "Nd Nh" or "Nh Nm".
export function fmtDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "—"
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

export function fmtMonth(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleString("en-US", { month: "short", year: "2-digit" })
}

// Bruno round 3 (2026-05-19): bucket label depends on the chart grain.
export function fmtBucket(iso: string, grain: OppGrain): string {
  const d = new Date(`${iso}T00:00:00`)
  if (grain === "day") {
    return d.toLocaleString("en-US", { month: "short", day: "numeric" })
  }
  if (grain === "week") {
    // ISO week number — same anchor (Monday of the week) the backend uses.
    const tmp = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
    const dayNum = tmp.getUTCDay() || 7
    tmp.setUTCDate(tmp.getUTCDate() + 4 - dayNum)
    const yearStart = new Date(Date.UTC(tmp.getUTCFullYear(), 0, 1))
    const weekNo = Math.ceil(((+tmp - +yearStart) / 86400000 + 1) / 7)
    const yy = String(tmp.getUTCFullYear()).slice(-2)
    return `W${weekNo} '${yy}`
  }
  return fmtMonth(iso)
}
