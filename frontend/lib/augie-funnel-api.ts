"use client"

import { useQuery, keepPreviousData } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: Record<string, unknown>
}

async function apiFetch<T>(path: string, signal?: AbortSignal): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
    signal,
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

/** Unwrap the envelope, failing loudly — a `success: false` body must surface
 *  as an error, never render as an empty funnel. Also keeps the hook's type
 *  exactly `T` under `keepPreviousData` (strict `next build`). */
async function apiEnvelope<T>(path: string, signal?: AbortSignal) {
  const res = await apiFetch<T>(path, signal)
  if (!res.success || res.data === undefined) {
    throw new Error(res.error || "Request failed")
  }
  return { data: res.data, meta: res.meta ?? {} }
}

async function apiData<T>(path: string, signal?: AbortSignal): Promise<T> {
  return (await apiEnvelope<T>(path, signal)).data
}

const AUGIE_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    // Never retry an auth failure, a client error, or a client abort (§43).
    if (/\b(400|401|403|404|422)\b/.test(msg) || /abort/i.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

const BASE = "custom/augie-funnel"

// ---------------------------------------------------------------------------
// Shared filter contract — mirrors `_common` in backend/app/routers/augie_funnel.py
// ---------------------------------------------------------------------------

export type AugieFunnelRange = "today" | "last7" | "last30" | "last90" | "upcoming" | "custom"
export type AugieFunnelUnit = "CORP" | "DFW"
export type AugieFunnelGrain = "day" | "week"

/** Sort tokens for /loads — EXACTLY the router's `_SORTS` keys (a backend test
 *  parses this block; keep one token per line and the blank line after it). */
export type AugieFunnelSort =
  | "pickup_desc"
  | "pickup_asc"
  | "order_asc"
  | "customer_asc"
  | "carrier_asc"
  | "team_asc"
  | "stage_asc"

export type AugieFunnelReason =
  | "canceled"
  | "international"
  | "multistop"
  | "not_covered"
  | "other"

/** Detail-table selector — the router's NODES. */
export type AugieFunnelNode =
  | "all"
  | "tracked"
  | "contacted"
  | "captured"
  | "tracked_no_info"
  | "not_tracked"
  | AugieFunnelReason

export const AUGIE_REASONS: AugieFunnelReason[] = [
  "canceled",
  "international",
  "multistop",
  "not_covered",
  "other",
]

export interface AugieFunnelFilters {
  range: AugieFunnelRange
  startDate?: string
  endDate?: string
  unit?: AugieFunnelUnit[]
  team?: string[]
  customer?: string[]
  carrier?: string[]
  q?: string
}

function augieQs(f: AugieFunnelFilters, extra: Record<string, string> = {}) {
  const p = new URLSearchParams()
  p.set("range", f.range)
  if (f.range === "custom" && f.startDate) p.set("start_date", f.startDate)
  if (f.range === "custom" && f.endDate) p.set("end_date", f.endDate)
  // Repeated keys (§45) — never comma-join: customer/carrier names carry commas.
  for (const v of f.unit ?? []) p.append("unit", v)
  for (const v of f.team ?? []) p.append("team", v)
  for (const v of f.customer ?? []) p.append("customer", v)
  for (const v of f.carrier ?? []) p.append("carrier", v)
  const q = (f.q ?? "").trim()
  if (q) p.set("q", q)
  for (const [k, v] of Object.entries(extra)) p.set(k, v)
  return `?${p.toString()}`
}

/** The query key must cover EVERY field augieQs serialises (§50). */
function augieKey(f: AugieFunnelFilters) {
  return [
    f.range,
    f.range === "custom" ? f.startDate ?? "" : "",
    f.range === "custom" ? f.endDate ?? "" : "",
    (f.unit ?? []).slice().sort().join("|"),
    (f.team ?? []).slice().sort().join("|"),
    (f.customer ?? []).slice().sort().join("|"),
    (f.carrier ?? []).slice().sort().join("|"),
    (f.q ?? "").trim(),
  ]
}

/** A custom range without both ends would 400 — hold the query until complete. */
function isComplete(f: AugieFunnelFilters) {
  return f.range !== "custom" || Boolean(f.startDate && f.endDate)
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AugieFilterOptions {
  units: AugieFunnelUnit[]
  teams: { unit: AugieFunnelUnit; team: string }[]
  customers: string[]
  carriers: string[]
  reasons: AugieFunnelReason[]
  data_floor: string
}

/** Percent fields are 0-100, or null on an empty denominator. */
export interface AugieFunnelCounts {
  pickups: number
  tracked: number
  contacted: number
  captured: number
  has_status: number
  canceled: number
  international: number
  multistop: number
  not_covered: number
  other: number
  not_tracked: number
  tracked_pct: number | null
  not_tracked_pct: number | null
  contacted_pct: number | null
  captured_pct: number | null
  has_status_pct: number | null
  reason_pct: Record<AugieFunnelReason, number | null>
}

export interface AugieFunnelSummary extends AugieFunnelCounts {
  start_date: string
  end_date: string
}

export interface AugieTrendPoint extends AugieFunnelCounts {
  bucket: string
}

export interface AugieTeamRow extends AugieFunnelCounts {
  unit: string | null
  team: string | null
}

export interface AugieLoadRow {
  order_id: string
  unit: string | null
  team: string | null
  customer: string | null
  carrier: string | null
  augie_status: string | null
  order_status: string | null
  /** Naive America/Chicago wall clock — display as-is, never convert. */
  pickup_day: string
  pickup_at: string | null
  origin: string
  destination: string
  tracked: boolean
  contacted: boolean
  captured: boolean
  reason: AugieFunnelReason | null
}

export interface AugieLoadsResult {
  rows: AugieLoadRow[]
  total: number
  truncated: boolean
}

export interface AugieFreshness {
  loads_updated: string | null
  loads_stale_minutes: number | null
  webhooks_received: string | null
  webhooks_stale_minutes: number | null
  is_stale: boolean
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useAugieFilterOptions() {
  return useQuery({
    queryKey: ["augie-funnel", "filters"],
    queryFn: ({ signal }) => apiData<AugieFilterOptions>(`${BASE}/filters`, signal),
    staleTime: 10 * 60 * 1000,
    ...AUGIE_RETRY,
  })
}

export function useAugieFreshness() {
  return useQuery({
    queryKey: ["augie-funnel", "freshness"],
    queryFn: ({ signal }) => apiData<AugieFreshness>(`${BASE}/freshness`, signal),
    staleTime: 60 * 1000,
    ...AUGIE_RETRY,
  })
}

export function useAugieSummary(f: AugieFunnelFilters) {
  return useQuery({
    queryKey: ["augie-funnel", "summary", ...augieKey(f)],
    queryFn: ({ signal }) =>
      apiData<AugieFunnelSummary>(`${BASE}/summary${augieQs(f)}`, signal),
    enabled: isComplete(f),
    placeholderData: keepPreviousData,
    ...AUGIE_RETRY,
  })
}

export function useAugieTrend(f: AugieFunnelFilters, grain: AugieFunnelGrain) {
  return useQuery({
    queryKey: ["augie-funnel", "trend", grain, ...augieKey(f)],
    queryFn: ({ signal }) =>
      apiData<AugieTrendPoint[]>(`${BASE}/trend${augieQs(f, { grain })}`, signal),
    enabled: isComplete(f),
    placeholderData: keepPreviousData,
    ...AUGIE_RETRY,
  })
}

export function useAugieByTeam(f: AugieFunnelFilters) {
  return useQuery({
    queryKey: ["augie-funnel", "by-team", ...augieKey(f)],
    queryFn: ({ signal }) => apiData<AugieTeamRow[]>(`${BASE}/by-team${augieQs(f)}`, signal),
    enabled: isComplete(f),
    placeholderData: keepPreviousData,
    ...AUGIE_RETRY,
  })
}

export function useAugieLoads(
  f: AugieFunnelFilters,
  node: AugieFunnelNode,
  sort: AugieFunnelSort,
) {
  return useQuery({
    queryKey: ["augie-funnel", "loads", node, sort, ...augieKey(f)],
    queryFn: async ({ signal }): Promise<AugieLoadsResult> => {
      const r = await apiEnvelope<AugieLoadRow[]>(
        `${BASE}/loads${augieQs(f, { node, sort })}`,
        signal,
      )
      return {
        rows: r.data,
        total: Number(r.meta.total ?? r.data.length),
        truncated: Boolean(r.meta.truncated),
      }
    },
    enabled: isComplete(f),
    placeholderData: keepPreviousData,
    ...AUGIE_RETRY,
  })
}

// ---------------------------------------------------------------------------
// Formatting helpers shared by the panels
// ---------------------------------------------------------------------------

export const DASH = "—"

export function fmtPct(v: number | null | undefined): string {
  return v === null || v === undefined ? DASH : `${v.toFixed(1)}%`
}

export function fmtInt(v: number | null | undefined): string {
  return v === null || v === undefined ? DASH : v.toLocaleString("en-US")
}

/** "2026-10-16T08:30:00" → "10/16 08:30" from the string parts only — the
 *  value is a naive CST wall clock, so no Date / timezone conversion. */
export function fmtNaiveStamp(v: string | null | undefined): string {
  if (!v) return DASH
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(v)
  if (!m) return v
  const day = `${m[2]}/${m[3]}/${m[1]}`
  return m[4] ? `${day} ${m[4]}:${m[5]}` : day
}

export const REASON_LABELS: Record<AugieFunnelReason, string> = {
  canceled: "Canceled",
  international: "Outside the US",
  multistop: "Multi-stop or split load",
  not_covered: "No carrier assigned yet",
  other: "Other settings",
}

export const REASON_HELP: Record<AugieFunnelReason, string> = {
  canceled: "The load was voided or canceled before it could be sent.",
  international:
    "Picks up or delivers outside the US — Augie only handles US-to-US loads.",
  multistop: "Has extra pickup/delivery stops, or moves in more than one leg.",
  not_covered: "No carrier or driver on the load, so there is nobody for Augie to call.",
  other:
    "Excluded by a customer/carrier setting, a blocking rule, Augie switched off, or timing.",
}

export const NODE_LABELS: Record<AugieFunnelNode, string> = {
  all: "All loads picked up",
  tracked: "Sent to Augie",
  contacted: "Carrier contacted",
  captured: "Carrier gave an update",
  tracked_no_info: "Sent, no update yet",
  not_tracked: "Not sent to Augie",
  canceled: "Not sent: Canceled",
  international: "Not sent: Outside the US",
  multistop: "Not sent: Multi-stop or split load",
  not_covered: "Not sent: No carrier assigned yet",
  other: "Not sent: Other settings",
}
