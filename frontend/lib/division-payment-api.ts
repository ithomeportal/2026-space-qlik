"use client"

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"

import { mutationErrorToast, mutationSuccessToast } from "@/lib/mutation-error"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
}

const BASE = "custom/division-payment"

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`/api/proxy/${BASE}/${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  const body: ApiResponse<T> = await res.json()
  if (!body.success) throw new Error(body.error ?? "Request failed")
  return body.data as T
}

// Never retry an auth failure or a client abort (§43).
const RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg) || /abort/i.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Contract
//
// ⚠ Every money figure below is computed by the BACKEND (`compute_summary` in
// routers/division_payment.py). Nothing in this file — or in any component that
// consumes it — may re-derive one. The vendor prototype re-derived the net
// payment on both its Dashboard and its Calculator page and the two disagreed by
// $1,575 on May 2026; that is the §16 failure this contract exists to prevent.
// ---------------------------------------------------------------------------

export interface PeriodMonth {
  year: number
  month: string
  month_label: string
  approved: boolean
  has_recalc: boolean
  /** A manual override sits over at least one datalake figure (Bruno PDF
   *  2026-10-05) — the month dropdown marks it with " ✎". */
  overridden: boolean
}

export interface Periods {
  years: number[]
  months: PeriodMonth[]
  /** The month to open on — chosen by the BACKEND: the PREVIOUS CST month,
   *  the one being paid. `null` only when that month does not exist. */
  default: { year: number; month: string } | null
}

export interface GLAccount {
  id: string
  code: string
  category: string
  category_label: string
  description: string
  amount: number
  included: boolean
  is_custom: boolean
}

export interface GLCategory {
  category: string
  label: string
  color: string
  amount: number
  row_count: number
  included_count: number
  all_included: boolean
}

export interface RecalcAdjustment {
  recalc_key: string
  month_label: string
  status: "applied" | "pending"
  recalc_date: string | null
  previously_recalculated: boolean
  revenue_delta: number
  cost_delta: number
  profit_delta: number
  corporate_delta: number
  ao_delta: number
}

export interface Summary {
  year: number
  month: string
  month_label: string
  inputs: { revenue: number; carrier_cost: number; profit: number }
  revenue: number
  carrier_cost: number
  profit: number
  margin_pct: number
  meets_target: boolean
  target_margin_pct: number
  ten_pct_of_revenue: number
  target_fee: number
  actual_fee: number
  difference: number
  gl_deductions: number
  penalty_fee: number
  corporate_gain: number
  net_payment: number
  corporate_gain_total: number
  net_payment_adjusted: number
  recalc_ao_adjustment: number
  recalc_corporate_adjustment: number
  recalcs: RecalcAdjustment[]
  previous: { month_label: string; net_payment: number } | null
  delta_vs_previous: number | null
  delta_pct_vs_previous: number | null
  gl_accounts: GLAccount[]
  gl_categories: GLCategory[]
  gl_included_count: number
  gl_row_count: number
  approved: boolean
  approved_at: string | null
  approved_by: string | null
  /** What v4 (TEAM-DFW, by origin_actual_departure) says for this month —
   *  shown beside an override so the typist can see what they replaced. */
  datalake: DatalakeFigures
  /** Per-field manual overrides; `null` = that field follows the datalake.
   *  `inputs.*` already holds the EFFECTIVE value (override ?? datalake). */
  overrides: Overrides
  overridden: boolean
}

export interface DatalakeFigures {
  revenue: number
  carrier_cost: number
  profit: number
  order_count: number
  /** False when the datalake could not be read — the card then shows the
   *  last saved values with a warning rather than zeros. */
  available: boolean
}

export interface Overrides {
  revenue: number | null
  carrier_cost: number | null
  profit: number | null
  updated_at: string | null
  updated_by: string | null
}

/** Only the keys SENT are written: `null` resets a field to the datalake, an
 *  absent key is left alone server-side (`model_fields_set`). Sending all three
 *  from a stale cache would overwrite another user's just-saved override. */
export type OverrideBody = Partial<Pick<Overrides, "revenue" | "carrier_cost" | "profit">>

export interface Archive {
  year: number
  month: string
  month_label: string
  revenue: number
  carrier_cost: number
  profit: number
  margin_pct: number
  gl_deductions: number
  penalty_fee: number
  corporate_gain: number
  net_payment: number
  snapshot_date: string | null
  approved_by: string | null
}

export interface AuditLoad {
  load_number: string
  client: string
  change_type: string
  change_description: string
  original_revenue: number
  updated_revenue: number
  original_carrier_cost: number
  updated_carrier_cost: number
  revenue_delta: number
  cost_delta: number
}

export interface RecalcSide {
  revenue: number
  carrier_cost: number
  profit: number
  margin_pct: number
  gl_deductions: number
  penalty_fee: number
  corporate_gain: number
  net_payment: number
}

export interface Recalc {
  recalc_key: string
  year: number
  month: string
  month_label: string
  applied_to_month: string
  applied_to_month_label: string
  recalc_date: string | null
  status: "applied" | "pending"
  previously_recalculated: boolean
  prior_recalc_net_payment: number | null
  snapshot: RecalcSide
  tms_update: RecalcSide
  diff: {
    revenue: number
    carrier_cost: number
    profit: number
    margin_pct: number
    corporate_gain: number
    net_payment: number
  }
  corporate_share: number
  ao_share: number
  note: string
  loads: AuditLoad[]
}

// --- Cutoffs (Bruno PDF 2026-10-05) ----------------------------------------
// A month closes on the 10th of the following month; its v4 orders are frozen
// as the cutoff snapshot and every later change is listed against it. These
// replace the vendor's fake `/recalcs` records on the Recalculations tab.
export type CutoffStatus = "open" | "before_tracking" | "snapshot_pending" | "tracked"

export interface CutoffFigures {
  revenue: number
  carrier_cost: number
  profit: number
  order_count: number
}

export interface CutoffMonth {
  year: number
  month: string
  month_label: string
  /** Date-only "YYYY-MM-DD" — format with `parseLocalDate`, never `new Date()` (§116). */
  period_start: string
  cutoff_date: string
  status: CutoffStatus
  live: CutoffFigures
  snapshot: (CutoffFigures & { captured_at: string }) | null
  delta: { revenue: number; carrier_cost: number; profit: number } | null
  ao_share: number | null
  corporate_share: number | null
  changed_count: number | null
  note: string
}

export interface Cutoffs {
  tracking_start: { year: number; month: string }
  months: CutoffMonth[]
}

export interface OrderMoney {
  total_charge: number
  total_carrier_pay: number
  margin_amt: number
}

export interface CutoffOrderChange {
  order_id: string
  company_id: string
  customer_name: string
  change_type: "modified" | "added" | "removed"
  before: OrderMoney | null
  after: OrderMoney | null
  delta: OrderMoney
}

export interface CutoffOrders {
  year: number
  month: string
  captured_at: string
  changes: CutoffOrderChange[]
  totals: OrderMoney
}

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------
export function usePeriods() {
  return useQuery({
    queryKey: ["dpc", "periods"],
    queryFn: () => apiFetch<Periods>("periods"),
    staleTime: 60_000,
    ...RETRY,
  })
}

export function useSummary(year: number | null, month: string | null) {
  return useQuery({
    // The key covers every field the URL serialises (§50) — otherwise switching
    // month would serve the previous month's cached money figures.
    queryKey: ["dpc", "summary", year, month],
    queryFn: () =>
      apiFetch<Summary>(`summary?year=${year}&month=${encodeURIComponent(month!)}`),
    enabled: year !== null && month !== null,
    placeholderData: keepPreviousData,
    ...RETRY,
  })
}

export function useArchives() {
  return useQuery({
    queryKey: ["dpc", "archives"],
    queryFn: () => apiFetch<Archive[]>("archives"),
    ...RETRY,
  })
}

export function useRecalcs() {
  return useQuery({
    queryKey: ["dpc", "recalcs"],
    queryFn: () => apiFetch<Recalc[]>("recalcs"),
    ...RETRY,
  })
}

export function useCutoffs() {
  return useQuery({
    queryKey: ["dpc", "cutoffs"],
    queryFn: () => apiFetch<Cutoffs>("cutoffs"),
    ...RETRY,
  })
}

/** Lazy — only fetched once a tracked month is expanded (a 404 means the month
 *  is not tracked, so it is never requested for any other status). */
export function useCutoffOrders(year: number, month: string, enabled: boolean) {
  return useQuery({
    queryKey: ["dpc", "cutoff-orders", year, month],
    queryFn: () =>
      apiFetch<CutoffOrders>(`cutoffs/${year}/${encodeURIComponent(month)}/orders`),
    enabled,
    ...RETRY,
  })
}

// ---------------------------------------------------------------------------
// Mutations — every one carries an onError toast (§46), or a rejected save
// looks identical to a successful one.
// ---------------------------------------------------------------------------
function useInvalidate() {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ["dpc"] })
  }
}

/** PUT all three overrides at once — `null` clears a field back to the
 *  datalake value. Replaces the removed `PUT months/{y}/{m}` inputs save. */
export function useSaveOverrides(year: number, month: string) {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (body: OverrideBody) =>
      apiFetch<unknown>(`months/${year}/${encodeURIComponent(month)}/overrides`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      invalidate()
      mutationSuccessToast("Saved")()
    },
    onError: mutationErrorToast("Save"),
  })
}

export interface GLPatchBody {
  id: string
  amount?: number
  included?: boolean
  code?: string
  description?: string
  category?: string
}

export function usePatchAccount() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, ...body }: GLPatchBody) =>
      apiFetch<unknown>(`gl/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: invalidate,
    onError: mutationErrorToast("Update expense"),
  })
}

export function useAddExpense(year: number, month: string) {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (body: {
      code: string
      category: string
      description: string
      amount: number
    }) =>
      apiFetch<unknown>(`months/${year}/${encodeURIComponent(month)}/gl`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      invalidate()
      mutationSuccessToast("Expense added")()
    },
    onError: mutationErrorToast("Add expense"),
  })
}

export function useDeleteExpense() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (id: string) => apiFetch<unknown>(`gl/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      invalidate()
      mutationSuccessToast("Expense removed")()
    },
    onError: mutationErrorToast("Remove expense"),
  })
}

export function useToggleCategory(year: number, month: string) {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (body: { category: string; included: boolean }) =>
      apiFetch<unknown>(`months/${year}/${encodeURIComponent(month)}/gl/category`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: invalidate,
    onError: mutationErrorToast("Toggle category"),
  })
}

export function useApproveMonth(year: number, month: string) {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: () =>
      apiFetch<unknown>(`months/${year}/${encodeURIComponent(month)}/approve`, {
        method: "POST",
      }),
    onSuccess: () => {
      invalidate()
      mutationSuccessToast("Month approved & archived")()
    },
    onError: mutationErrorToast("Approve month"),
  })
}

export function useSaveRecalcNote() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ key, note }: { key: string; note: string }) =>
      apiFetch<unknown>(`recalcs/${encodeURIComponent(key)}/note`, {
        method: "PUT",
        body: JSON.stringify({ note }),
      }),
    onSuccess: () => {
      invalidate()
      mutationSuccessToast("Note saved")()
    },
    onError: mutationErrorToast("Save note"),
  })
}

export function useSaveCutoffNote() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ year, month, note }: { year: number; month: string; note: string }) =>
      apiFetch<unknown>(`cutoffs/${year}/${encodeURIComponent(month)}/note`, {
        method: "PUT",
        body: JSON.stringify({ note }),
      }),
    onSuccess: () => {
      invalidate()
      mutationSuccessToast("Note saved")()
    },
    onError: mutationErrorToast("Save note"),
  })
}

// ---------------------------------------------------------------------------
// Formatting — one implementation, imported everywhere. The prototype had three
// slightly different ones and they disagreed on negative zero.
// ---------------------------------------------------------------------------
const CURRENCY = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

export function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return CURRENCY.format(Object.is(value, -0) ? 0 : value)
}

export function formatPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  return `${value.toFixed(digits)}%`
}

/** Signed money for a delta — "+$1.00" / "−$1.00" (true minus sign) / "$0.00".
 *  Formatting only: the value itself always comes from the backend. */
export function formatSignedCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  const sign = value > 0 ? "+" : value < 0 ? "−" : ""
  return `${sign}${formatCurrency(Math.abs(value))}`
}
