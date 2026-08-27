"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: {
    total?: number
    page?: number
    limit?: number
    grand_total_revenue?: number
    le_threshold_count?: number
    gt_threshold_count?: number
    threshold?: number
    returned?: number
    truncated?: boolean
    late_days?: number
    min_avg_days?: number
    buckets?: TopDelayedBucket[]
  }
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
// Filter contract — shared across every admin-cashflow endpoint
// ---------------------------------------------------------------------------

export type AdminCashflowRange =
  | "today"
  | "wtd"
  | "last_7d"
  | "mtd"
  | "last_month"
  | "ytd"
  | "custom"

export type CustomerFilterMode = "include" | "exclude"

export interface AdminCashflowFilters {
  range: AdminCashflowRange
  startDate?: string
  endDate?: string
  teams?: string[]
  companies?: string[]
  customer?: string
  customers?: string[]
  customerMode?: CustomerFilterMode
  contractType?: string
}

function buildQs(
  f: AdminCashflowFilters,
  extra?: Record<string, string | number>,
) {
  const q = new URLSearchParams()
  q.set("range", f.range)
  if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
  if (f.teams && f.teams.length) q.set("teams", f.teams.join(","))
  if (f.companies && f.companies.length) q.set("companies", f.companies.join(","))
  if (f.customers && f.customers.length) {
    q.set("customers", f.customers.join(","))
    q.set("customer_mode", f.customerMode ?? "include")
  } else if (f.customer) {
    q.set("customer", f.customer)
  }
  if (f.contractType) q.set("contract_type", f.contractType)
  if (extra) {
    for (const [k, v] of Object.entries(extra)) q.set(k, String(v))
  }
  const s = q.toString()
  return s ? `?${s}` : ""
}

function keyFromFilters(f: AdminCashflowFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    (f.teams ?? []).slice().sort().join(","),
    (f.companies ?? []).slice().sort().join(","),
    f.customer ?? "",
    (f.customers ?? []).slice().sort().join(","),
    f.customerMode ?? "include",
    f.contractType ?? "",
  ]
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AdminCashflowFacets {
  teams: string[]
  companies: string[]
  customers: string[]
  contract_types: string[]
  today: string
  year_floor: string
  alarm_usd: number
}

// Bruno Aging R (PDF 2026-07-20): trend Δ vs prior period under a KPI card.
// `curr`/`prev` are the current-window and prior-window values (null when the
// prior window has no qualifying loads). unit "pp" = percentage points (% cards),
// "d" = days (avg-days card). `basis` is a free-text label rendered after "vs"
// and is now RANGE-AWARE (e.g. "yesterday", "last week", "same day LM",
// "same date LY") — it shifts with the selected Range filter.
export interface KpiTrendCmp {
  curr: number | null
  prev: number | null
  basis: string
  unit: "pp" | "d"
}

export interface AdminCashflowKpis {
  pct_del_bill_le2: number
  pct_bol_bill_le1: number
  pct_carrinv_bill_le1: number
  avg_days_del_bill: number
  avg_days_bol_bill: number
  delivered_not_billed_usd: number
  ready_not_billed_usd: number
  total_unbilled_usd: number
  alarm: boolean
  alarm_threshold_usd: number
  rows_in_scope: number
  // Bruno R4 PDF 2026-05-26 — per-KPI supporting breakdown (count + revenue).
  // le_*/total_* reconcile to the headline %; Avg-Days cards reuse the same scope.
  del_le2_count: number
  del_total_count: number
  del_le2_rev: number
  del_total_rev: number
  bol_le1_count: number
  bol_total_count: number
  bol_le1_rev: number
  bol_total_rev: number
  carrinv_le1_count: number
  carrinv_total_count: number
  carrinv_le1_rev: number
  carrinv_total_rev: number
  // Bruno Aging R (PDF 2026-07-13) — trend Δ vs prior period on 3 cards.
  trend?: {
    del: KpiTrendCmp
    bol: KpiTrendCmp
    avg_days_bol: KpiTrendCmp
  }
  window: { start: string; end: string }
}

export interface AdminCashflowSparklines {
  weeks: string[]
  del_bill_le2: (number | null)[]
  bol_bill_le1: (number | null)[]
  carrinv_bill_le1: (number | null)[]
}

// Bruno Aging "+" pop-up (PDF 2026-06-22): per-KPI monthly combo chart series.
export type TimingMetricKey = "del" | "bol" | "carrinv"

export interface TimingMetricSeries {
  total: number[]
  within: number[]
  over: number[]
  // Bruno Aging (PDF 2026-07-20): avg days per bucket for the "+" Table view.
  // null when a bucket has no qualifying loads.
  avg_days?: (number | null)[]
  // Bruno Aging (PDF 2026-08-27) R3: revenue per bucket for the "+" Table
  // view's Revenue column. Same universe as `total`, which is why `total`
  // doubles as that table's "Orders" column — the two describe one set of
  // orders and therefore reconcile with the KPI card behind the pop-up.
  // Optional so an older backend response still type-checks.
  revenue?: number[]
}

export type TimingGrain = "week" | "month"

export interface AdminCashflowTimingMonthly {
  // Bruno Aging R (PDF 2026-07-13): buckets are months (default) or weeks.
  // The field stays named `months` for back-compat; values are bucket-start
  // ISO dates (month-1st for month grain, ISO-Monday for week grain).
  grain?: TimingGrain
  months: string[]
  del: TimingMetricSeries
  bol: TimingMetricSeries
  carrinv: TimingMetricSeries
}

export interface DeliveredNotBilledRow {
  id: string | null
  orig_sched_early: string | null
  ship_date: string | null
  dest_actual_arrival: string | null
  customer_name: string
  team_id: string
  company_id: string
  total_charge: number
  days_since_delivery: number | null
}

export interface ReadyNotBilledRow {
  id: string | null
  orig_sched_early: string | null
  ship_date: string | null
  bol_recv_date: string | null
  status: string
  customer_name: string
  team_id: string
  company_id: string
  total_charge: number
  days_since_bol_recv: number | null
}

export interface AgingRow {
  id: string | null
  company_id: string
  team_id: string
  customer_name: string
  left_date: string | null
  bill_date: string | null
  days: number | null
  total_charge: number
}

export interface AgingBucketsData {
  buckets: { label: string; count: number }[]
  total: number
}

export interface TopDelayedCustomerRow {
  customer_name: string
  n_loads: number
  n_late: number
  late_revenue: number
  avg_days: number
}

// Bruno Aging (PDF 2026-08-24) R2 — the "Table" pop-up: the same customers,
// broken out across four DISCRETE months. `tm` is the current (partial) month,
// then one column per preceding month. The month each key stands for is not
// inferred client-side — the endpoint returns it in `meta.buckets`, so the
// header and the numbers can never disagree.
// Bruno Aging (PDF 2026-08-27) R2: the endpoint now returns EIGHT discrete
// months. The table still renders only the first four (tm/lm/l2m/l3m) — the
// rest exist so the pop-up's Late / Revenue / AVG Days line charts can span
// eight months off the same fetch.
export type TopDelayedBucketKey =
  | "tm" | "lm" | "l2m" | "l3m" | "l4m" | "l5m" | "l6m" | "l7m"

// The four the table shows, in table order. `as const` so the four-key subset
// is its own type — the table's column labels are keyed on it, and typing them
// against the full eight would demand labels for chart-only buckets.
export const TOP_DELAYED_TABLE_KEYS = ["tm", "lm", "l2m", "l3m"] as const
export type TopDelayedTableKey = (typeof TOP_DELAYED_TABLE_KEYS)[number]

export interface TopDelayedBucket {
  key: TopDelayedBucketKey
  month: string
}

// Per-bucket fields are `late_` / `rev_` / `avg_days_` / `loads_` + key, for every
// key in TopDelayedBucketKey. Spelled as a mapped type rather than 24 literal
// lines so adding a ninth month cannot leave a field behind.
type TopDelayedBucketFields = {
  [K in TopDelayedBucketKey as
    | `late_${K}`
    | `rev_${K}`
    | `avg_days_${K}`
    | `loads_${K}`]: number | null
}

export interface TopDelayedMonthlyRow extends TopDelayedBucketFields {
  customer_name: string
  // ⚠ These three cover the TABLE's four months only, never all eight — they
  // decide which customers qualify and how the rows are ordered, and the
  // backend pins them deliberately. See the endpoint docstring.
  n_late_total: number
  late_revenue_total: number
  avg_days_total: number
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useAdminCashflowFacets() {
  return useQuery({
    queryKey: ["admin-cashflow", "facets"],
    queryFn: () =>
      apiFetch<AdminCashflowFacets>("custom/admin-cashflow/facets"),
    staleTime: 5 * 60 * 1000,
    ...RETRY,
  })
}

export function useAdminCashflowKpis(f: AdminCashflowFilters) {
  return useQuery({
    queryKey: ["admin-cashflow", "kpis", ...keyFromFilters(f)],
    queryFn: () =>
      apiFetch<AdminCashflowKpis>(`custom/admin-cashflow/kpis${buildQs(f)}`),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export function useAdminCashflowSparklines(f: AdminCashflowFilters) {
  // Bruno Aging R1 (2026-06-11): the trend now follows the selected date
  // range, so the key + query carry range/start/end like every other table.
  return useQuery({
    queryKey: [
      "admin-cashflow",
      "sparklines",
      f.range,
      f.range === "custom" ? f.startDate ?? "" : "",
      f.range === "custom" ? f.endDate ?? "" : "",
      (f.teams ?? []).slice().sort().join(","),
      (f.companies ?? []).slice().sort().join(","),
      f.customer ?? "",
      (f.customers ?? []).slice().sort().join(","),
      f.customerMode ?? "include",
      f.contractType ?? "",
    ],
    queryFn: () => {
      const q = new URLSearchParams()
      q.set("range", f.range)
      if (f.range === "custom" && f.startDate) q.set("start_date", f.startDate)
      if (f.range === "custom" && f.endDate) q.set("end_date", f.endDate)
      if (f.teams?.length) q.set("teams", f.teams.join(","))
      if (f.companies?.length) q.set("companies", f.companies.join(","))
      if (f.customers && f.customers.length) {
        q.set("customers", f.customers.join(","))
        q.set("customer_mode", f.customerMode ?? "include")
      } else if (f.customer) {
        q.set("customer", f.customer)
      }
      if (f.contractType) q.set("contract_type", f.contractType)
      const s = q.toString()
      return apiFetch<AdminCashflowSparklines>(
        `custom/admin-cashflow/sparklines${s ? `?${s}` : ""}`,
      )
    },
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

// Bruno Aging "+" pop-up (PDF 2026-06-22): monthly timing combo chart.
// Scope-only (teams/companies/customer/contract) — the chart deliberately
// ignores the page date range and always spans a fixed trailing 13 months,
// so it can't collapse to a single bar under an MTD range. Enabled lazily so
// nothing is fetched until a KPI "+" pop-up is opened.
export function useAdminCashflowTimingMonthly(
  f: AdminCashflowFilters,
  enabled: boolean,
  grain: TimingGrain = "month",
) {
  const scopeKey = [
    grain,
    (f.teams ?? []).slice().sort().join(","),
    (f.companies ?? []).slice().sort().join(","),
    f.customer ?? "",
    (f.customers ?? []).slice().sort().join(","),
    f.customerMode ?? "include",
    f.contractType ?? "",
  ]
  return useQuery({
    queryKey: ["admin-cashflow", "timing-monthly", ...scopeKey],
    queryFn: () => {
      const q = new URLSearchParams()
      q.set("grain", grain)
      if (f.teams?.length) q.set("teams", f.teams.join(","))
      if (f.companies?.length) q.set("companies", f.companies.join(","))
      if (f.customers && f.customers.length) {
        q.set("customers", f.customers.join(","))
        q.set("customer_mode", f.customerMode ?? "include")
      } else if (f.customer) {
        q.set("customer", f.customer)
      }
      if (f.contractType) q.set("contract_type", f.contractType)
      const s = q.toString()
      return apiFetch<AdminCashflowTimingMonthly>(
        `custom/admin-cashflow/timing-monthly${s ? `?${s}` : ""}`,
      )
    },
    staleTime: 5 * 60 * 1000,
    enabled,
    ...RETRY,
  })
}

// Bruno Aging R2 (2026-06-11): the two unbilled tables carry optional
// free-text Order / Customer column filters. Empty strings are omitted from
// the query so an untouched table behaves exactly as before.
export interface UnbilledTableOpts {
  sort: string
  page: number
  limit: number
  orderQ?: string
  customerQ?: string
}

function unbilledExtra(opts: UnbilledTableOpts) {
  const extra: Record<string, string | number> = {
    sort: opts.sort,
    page: opts.page,
    limit: opts.limit,
  }
  if (opts.orderQ && opts.orderQ.trim()) extra.order_q = opts.orderQ.trim()
  if (opts.customerQ && opts.customerQ.trim())
    extra.customer_q = opts.customerQ.trim()
  return extra
}

export function useDeliveredNotBilled(
  f: AdminCashflowFilters,
  opts: UnbilledTableOpts,
) {
  return useQuery({
    queryKey: [
      "admin-cashflow",
      "delivered-not-billed",
      ...keyFromFilters(f),
      opts.sort,
      opts.page,
      opts.limit,
      opts.orderQ ?? "",
      opts.customerQ ?? "",
    ],
    queryFn: () =>
      apiFetch<DeliveredNotBilledRow[]>(
        `custom/admin-cashflow/delivered-not-billed${buildQs(
          f,
          unbilledExtra(opts),
        )}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export function useReadyNotBilled(
  f: AdminCashflowFilters,
  opts: UnbilledTableOpts,
) {
  return useQuery({
    queryKey: [
      "admin-cashflow",
      "ready-not-billed",
      ...keyFromFilters(f),
      opts.sort,
      opts.page,
      opts.limit,
      opts.orderQ ?? "",
      opts.customerQ ?? "",
    ],
    queryFn: () =>
      apiFetch<ReadyNotBilledRow[]>(
        `custom/admin-cashflow/ready-not-billed${buildQs(
          f,
          unbilledExtra(opts),
        )}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

export type AgingTab =
  | "delivery-vs-bill"
  | "bol-vs-bill"
  | "carrinv-vs-bill"

export function useAging(
  tab: AgingTab,
  f: AdminCashflowFilters,
  opts: { sort: string; page: number; limit: number; enabled?: boolean },
) {
  return useQuery({
    queryKey: [
      "admin-cashflow",
      "aging",
      tab,
      ...keyFromFilters(f),
      opts.sort,
      opts.page,
      opts.limit,
    ],
    queryFn: () =>
      apiFetch<AgingRow[]>(
        `custom/admin-cashflow/aging/${tab}${buildQs(f, {
          sort: opts.sort,
          page: opts.page,
          limit: opts.limit,
        })}`,
      ),
    staleTime: 60 * 1000,
    enabled: opts.enabled ?? true,
    ...RETRY,
  })
}

export function useAgingBuckets(f: AdminCashflowFilters) {
  return useQuery({
    queryKey: ["admin-cashflow", "aging-buckets", ...keyFromFilters(f)],
    queryFn: () =>
      apiFetch<AgingBucketsData>(
        `custom/admin-cashflow/aging-buckets${buildQs(f)}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}

/**
 * Build a same-origin CSV-download URL for one of the 5 Bruno-requested tables.
 * The proxy passes non-JSON bodies through; the backend emits
 * `Content-Disposition: attachment` so the browser saves the file directly.
 */
export function adminCashflowCsvUrl(
  endpoint:
    | "delivered-not-billed"
    | "ready-not-billed"
    | "aging/delivery-vs-bill"
    | "aging/bol-vs-bill"
    | "aging/carrinv-vs-bill",
  f: AdminCashflowFilters,
  extra?: { sort?: string; orderQ?: string; customerQ?: string },
): string {
  const e: Record<string, string | number> = {}
  if (extra?.sort) e.sort = extra.sort
  if (extra?.orderQ && extra.orderQ.trim()) e.order_q = extra.orderQ.trim()
  if (extra?.customerQ && extra.customerQ.trim())
    e.customer_q = extra.customerQ.trim()
  const qs = buildQs(f, Object.keys(e).length ? e : undefined)
  return `/api/proxy/custom/admin-cashflow/${endpoint}.csv${qs}`
}

/**
 * The "Table" pop-up behind the delays card — lazy, and scope-only.
 *
 * The page's date range is deliberately absent from both the query string and
 * the cache key: the endpoint ignores it (four fixed months), so carrying it
 * would only refetch identical data every time someone touches a range pill.
 */
export function useTopDelayedCustomersMonthly(
  f: AdminCashflowFilters,
  enabled: boolean,
  limit = 200,
) {
  const scopeKey = [
    (f.teams ?? []).slice().sort().join(","),
    (f.companies ?? []).slice().sort().join(","),
    f.customer ?? "",
    (f.customers ?? []).slice().sort().join(","),
    f.customerMode ?? "include",
    f.contractType ?? "",
    limit,
  ]
  return useQuery({
    queryKey: ["admin-cashflow", "top-delayed-monthly", ...scopeKey],
    queryFn: () => {
      const q = new URLSearchParams()
      q.set("limit", String(limit))
      if (f.teams?.length) q.set("teams", f.teams.join(","))
      if (f.companies?.length) q.set("companies", f.companies.join(","))
      if (f.customers && f.customers.length) {
        q.set("customers", f.customers.join(","))
        q.set("customer_mode", f.customerMode ?? "include")
      } else if (f.customer) {
        q.set("customer", f.customer)
      }
      if (f.contractType) q.set("contract_type", f.contractType)
      return apiFetch<TopDelayedMonthlyRow[]>(
        `custom/admin-cashflow/top-delayed-customers/monthly?${q.toString()}`,
      )
    },
    staleTime: 5 * 60 * 1000,
    enabled,
    ...RETRY,
  })
}

export function useTopDelayedCustomers(f: AdminCashflowFilters, limit = 10) {
  return useQuery({
    queryKey: [
      "admin-cashflow",
      "top-delayed",
      ...keyFromFilters(f),
      limit,
    ],
    queryFn: () =>
      apiFetch<TopDelayedCustomerRow[]>(
        `custom/admin-cashflow/top-delayed-customers${buildQs(f, { limit })}`,
      ),
    staleTime: 60 * 1000,
    ...RETRY,
  })
}
