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
}

export interface Periods {
  years: number[]
  months: PeriodMonth[]
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
}

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

export function useSaveInputs(year: number, month: string) {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: (body: { revenue: number; carrier_cost: number; profit?: number }) =>
      apiFetch<unknown>(`months/${year}/${encodeURIComponent(month)}`, {
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

export function usePatchAccount() {
  const invalidate = useInvalidate()
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; amount?: number; included?: boolean }) =>
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
