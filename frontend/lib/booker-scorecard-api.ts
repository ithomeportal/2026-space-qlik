"use client"

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { mutationErrorToast } from "@/lib/mutation-error"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { total: number; page: number; limit: number }
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
// Shared filter contract (Bruno Request 2)
// ---------------------------------------------------------------------------

export type BookerRange = "today" | "wtd" | "mtd" | "custom"

/** Scenario steps (Bruno PDF 2026-08-18 R2). Mirrors SCENARIO_STEPS on the
 *  backend, which whitelists the value — anything else is a 400. */
export const SCENARIO_STEPS = [15, 25, 50] as const
export type ScenarioStep = (typeof SCENARIO_STEPS)[number]

export interface BookerFilters {
  range: BookerRange
  startDate?: string
  endDate?: string
  contractTypes?: string[]
  customers?: string[]
  postedBy?: string[]
  /** Scenario what-if: profit +adjustment, carrier cost −adjustment per order.
   *  Omitted / 0 = the real numbers. */
  adjustment?: number
}

/** Only the non-date filters. The 10-week chart takes exactly these. */
export type BookerScopeFilters = Pick<
  BookerFilters,
  "contractTypes" | "customers" | "postedBy"
>

function scopeParams(q: URLSearchParams, f: BookerScopeFilters) {
  // Repeated keys, never a comma-join — the proxy forwards with .append(), and
  // customer names legitimately contain commas (§45).
  for (const c of f.contractTypes ?? []) q.append("contract_type", c)
  for (const c of f.customers ?? []) q.append("customer_name", c)
  for (const c of f.postedBy ?? []) q.append("posted_by", c)
}

function bookerQs(f: BookerFilters, extra?: Record<string, string>) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  scopeParams(q, f)
  if (f.adjustment) q.set("adjustment", String(f.adjustment))
  if (extra) for (const [k, v] of Object.entries(extra)) q.set(k, v)
  const s = q.toString()
  return s ? `?${s}` : ""
}

/** §50 — the React Query key must cover every field the URL builder serialises. */
function scopeKey(f: BookerScopeFilters) {
  return [
    (f.contractTypes ?? []).slice().sort().join("|"),
    (f.customers ?? []).slice().sort().join("|"),
    (f.postedBy ?? []).slice().sort().join("|"),
  ]
}

function bookerKey(f: BookerFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    ...scopeKey(f),
    // §50 — without this the Scenario tab would serve the baseline's cached
    // response, i.e. render "15" while showing unadjusted money.
    f.adjustment ?? 0,
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface BookerFilterOptions {
  customers: string[]
  contract_types: string[]
  posted_by: string[]
  year_start: string
  year_end: string
  window: { start: string; end: string }
}

export interface BookerSummary {
  orders: number
  profit: number | null
  revenue: number | null
  margin_pct: number | null
  avg_margin_per_load: number | null
  /** null when the AP threshold source is unavailable. */
  broken_threshold: number | null
  /** The honest denominator: orders that actually carry a threshold. */
  threshold_orders: number | null
  /** broken / threshold_orders. Computed server-side so the KPI card and the
   *  table's totals row cannot drift apart (§69). */
  broken_threshold_pct: number | null
  /** 1 − broken_threshold_pct (Bruno 2026-08-31 R3) — the figure the KPI card
   *  now shows. A FRACTION, like every other percentage on this wire: fmtPct
   *  multiplies by 100, and an already-scaled value prints 100x wrong (§95). */
  compliance_threshold_pct: number | null
  /** Σ (threshold − carrier cost) over orders coming in UNDER threshold. */
  cost_saving: number | null
  /** How many orders contributed to cost_saving. */
  under_threshold: number | null
  otp_pct: number | null
  otd_pct: number | null
  /** Orders rate-confirmed MORE THAN ONCE as of the window end (rc_count > 1).
   *  Deliberately unmoved by `adjustment` — a scenario shifts money, not
   *  rate-conf postings. */
  recoveries: number
  /** Echo of the scenario step actually applied (0 = baseline). */
  adjustment: number
  window: { start: string; end: string }
}

export interface BookerOrderRow {
  order_id: string
  team: string | null
  customer: string | null
  posted_by: string | null
  posted_date: string | null
  contract_type: string | null
  revenue: number | null
  carrier_cost: number | null
  profit: number | null
  otp_on_time: boolean
  otd_on_time: boolean
  threshold: number | null
  /** "RC" — Rate-Conf postings on this order as of the window end. */
  rc_count: number
}

export interface BookerOrders {
  rows: BookerOrderRow[]
  /** Server-side full-universe aggregate, never a client reduce of the page (§44). */
  totals: {
    orders: number
    revenue: number | null
    carrier_cost: number | null
    profit: number | null
    margin_pct: number | null
    otp_pct: number | null
    otd_pct: number | null
    broken_threshold: number | null
    threshold_orders: number | null
    broken_threshold_pct: number | null
    compliance_threshold_pct: number | null
    cost_saving: number | null
    under_threshold: number | null
    /** Same server-side definition as the KPI card (§69). */
    recoveries: number
  }
  adjustment: number
  thresholds_available: boolean
  window: { start: string; end: string }
}

export type BookerOrdersSort =
  | "posted_desc" | "posted_asc"
  | "order_desc" | "order_asc"
  | "profit_desc" | "profit_asc"
  | "revenue_desc" | "revenue_asc"
  | "cost_desc" | "cost_asc"

export interface BookerWeek {
  week_start: string
  label: string
  orders: number
  otp_pct: number | null
  otd_pct: number | null
}

export interface BookerWeekly {
  weeks: BookerWeek[]
  window: { start: string; end: string }
}

export interface BookerNote {
  notes: string
  updated_at: string | null
}

export interface BookerFreshness {
  sources: {
    key: string
    label: string
    updated_at: string | null
    age_minutes: number | null
  }[]
  as_of: string | null
  age_minutes: number | null
  stalest: string | null
  /** Labels of feeds with NO timestamp at all — dead, not merely stale. */
  unavailable: string[]
  checked_at: string | null
}

/** One row of the Rank tab (Bruno PDF 2026-08-31, page 1). */
export interface BookerRankRow {
  booker: string
  /** Competition rank (1,2,2,4) by bookings in the last completed week.
   *  null when the booker did not book at all that week. */
  rank: number | null
  prev_rank: number | null
  /** prev_rank − rank. POSITIVE = moved UP. null = not present last week,
   *  which is not the same as "unchanged" and must not render as 0. */
  rank_delta: number | null
  bookings: number
  prev_bookings: number
  /** Still on the wire: the Orders table flags individual broken orders, a
   *  ROW fact that keeps its own wording. The Rank tab renders compliance. */
  broken_threshold: number | null
  threshold_orders: number | null
  /** A fraction — fmtPct multiplies by 100. */
  broken_threshold_pct: number | null
  /** Bruno 2026-09-03 R1 — what the Rank tab shows: 1 − broken_threshold_pct,
   *  forwarded from the backend's ONE `_threshold_stats` helper so this tab and
   *  the Scorecard KPI card cannot disagree (§69). A FRACTION. */
  compliance_threshold_pct: number | null
  /** threshold_orders − broken_threshold, the COUNT printed beside that
   *  percentage. Computed server-side off the same two counters so the count
   *  and the ratio cannot span two populations (§96) — never re-derived here. */
  compliant_threshold: number | null
  cost_saving: number | null
  under_threshold: number | null
}

export interface BookerRankWeek {
  start: string
  end: string
  label: string
}

/** ⚠ The INNER payload — apiFetch<T> already unwraps the {success, data}
 *  envelope, exactly like BookerWeekly. Declaring the envelope here again
 *  types every field one level too deep. */
export interface BookerRank {
  rows: BookerRankRow[]
  /** Picker options. Bruno 2026-09-03 R3 — the Rank tab is bookers only, so
   *  this is exactly the roster members who booked in either week. Offering a
   *  name the table cannot show would be a picker that empties its own table. */
  bookers: string[]
  roster: string[]
  /** The ranked population: the "of N" in "3 of N". Roster members only, and
   *  counted BEFORE the Posted By display filter, so selecting one name does
   *  not renumber the league (§75). */
  total_bookers: number
  week: BookerRankWeek
  prev_week: BookerRankWeek
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useBookerFilterOptions(filters: BookerFilters) {
  return useQuery({
    queryKey: [
      "booker-scorecard",
      "filters",
      filters.range,
      filters.range === "custom" ? filters.startDate ?? "" : "",
      filters.range === "custom" ? filters.endDate ?? "" : "",
    ],
    // The multi-selects are stripped: otherwise picking one customer would
    // shrink the customer list to that single option.
    queryFn: () =>
      apiFetch<BookerFilterOptions>(
        `custom/booker-performance-scorecard/filters${bookerQs({
          ...filters,
          contractTypes: [],
          customers: [],
          postedBy: [],
        })}`,
      ),
    staleTime: 10 * 60 * 1000,
    placeholderData: keepPreviousData,
    ...RETRY,
  })
}

export function useBookerSummary(filters: BookerFilters) {
  return useQuery({
    queryKey: ["booker-scorecard", "summary", ...bookerKey(filters)],
    queryFn: () =>
      apiFetch<BookerSummary>(
        `custom/booker-performance-scorecard/summary${bookerQs(filters)}`,
      ),
    placeholderData: keepPreviousData,
    ...RETRY,
  })
}

export function useBookerOrders(
  filters: BookerFilters,
  sort: BookerOrdersSort,
  page: number,
  limit = 200,
) {
  return useQuery({
    queryKey: [
      "booker-scorecard",
      "orders",
      ...bookerKey(filters),
      sort,
      page,
      limit,
    ],
    queryFn: () =>
      apiFetch<BookerOrders>(
        `custom/booker-performance-scorecard/orders${bookerQs(filters, {
          sort,
          page: String(page),
          limit: String(limit),
        })}`,
      ),
    placeholderData: keepPreviousData,
    ...RETRY,
  })
}

/**
 * 10-week trend. Takes ONLY the non-date filters — Bruno: "the chart should not
 * be affected by the Date filter". The endpoint declares no date params at all,
 * so this cannot drift back into being date-scoped by accident.
 */
export function useBookerWeekly(scope: BookerScopeFilters) {
  const q = new URLSearchParams()
  scopeParams(q, scope)
  const qs = q.toString()
  return useQuery({
    queryKey: ["booker-scorecard", "weekly", ...scopeKey(scope)],
    queryFn: () =>
      apiFetch<BookerWeekly>(
        `custom/booker-performance-scorecard/weekly${qs ? `?${qs}` : ""}`,
      ),
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
    ...RETRY,
  })
}

/** The Rank tab. Scope filters only — it takes NO date params, exactly like
 *  useBookerWeekly: the window is a fixed pair of completed weeks resolved
 *  server-side, and the tab captions it on screen.
 *
 *  ⚠ Those weeks run SATURDAY → FRIDAY (Bruno 2026-09-03 R2) on this tab ONLY.
 *  Every other window in this report is Mon-Sun. Do not "harmonise" them. */
export function useBookerRank(scope: BookerScopeFilters) {
  const q = new URLSearchParams()
  scopeParams(q, scope)
  const qs = q.toString()
  return useQuery({
    queryKey: ["booker-scorecard", "rank", ...scopeKey(scope)],
    queryFn: () =>
      apiFetch<BookerRank>(
        `custom/booker-performance-scorecard/rank${qs ? `?${qs}` : ""}`,
      ),
    staleTime: 5 * 60 * 1000,
    placeholderData: keepPreviousData,
    ...RETRY,
  })
}

export function useBookerNote() {
  return useQuery({
    queryKey: ["booker-scorecard", "note"],
    queryFn: () =>
      apiFetch<BookerNote>("custom/booker-performance-scorecard/note"),
    staleTime: 30 * 1000,
    ...RETRY,
  })
}

export function useSaveBookerNote() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (notes: string) =>
      apiFetch<BookerNote>("custom/booker-performance-scorecard/note", {
        method: "PUT",
        body: JSON.stringify({ notes }),
      }),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ["booker-scorecard", "note"] }),
    onError: mutationErrorToast("Save action plan"),
  })
}

export function useBookerFreshness() {
  return useQuery({
    queryKey: ["booker-scorecard", "freshness"],
    queryFn: () =>
      apiFetch<BookerFreshness>("custom/booker-performance-scorecard/freshness"),
    refetchInterval: 120_000,
    ...RETRY,
  })
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

export const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : v.toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      })

export const fmtUsd2 = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : v.toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })

export const fmtCount = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : v.toLocaleString("en-US")

/** Fractions on the wire (0.94), percent in the UI (94.0%). */
export const fmtPct = (v: number | null | undefined, digits = 1) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : `${(v * 100).toFixed(digits)}%`

export const fmtDateTime = (iso: string | null | undefined) => {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  return `${String(d.getMonth() + 1).padStart(2, "0")}/${String(
    d.getDate(),
  ).padStart(2, "0")}/${String(d.getFullYear()).slice(2)} ${String(
    d.getHours(),
  ).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`
}
