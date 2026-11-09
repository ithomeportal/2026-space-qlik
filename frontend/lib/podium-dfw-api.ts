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

const PODIUM_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

export type PodiumRange = "today" | "wtd" | "mtd" | "custom"

// Which date the range filters (PDF 2026-11-09 R1). Same population either way:
// DFW loads with a Rate-Conf posting, never Void — only the date moves.
export type PodiumBasis = "rate_conf" | "departure"

// v4 status codes the Status filter offers (R2). Void is excluded for every
// user (Bruno 2026-07-07), so it is never an option. Backend allowlists these.
export type PodiumStatus = "D" | "P" | "A"

export const STATUS_LABELS: Record<PodiumStatus, string> = {
  D: "Delivered",
  P: "In Progress",
  A: "Available",
}

export const STATUS_OPTIONS: PodiumStatus[] = ["D", "P", "A"]

export function statusLabel(code: string | null): string {
  if (!code) return "—"
  return STATUS_LABELS[code as PodiumStatus] ?? code
}

export interface PodiumKpis {
  loads: number
  profit: number
  revenue: number
  margin_pct: number | null
}

export interface PodiumRow {
  team: string | null
  order_id: string | null
  posted_by: string | null
  posted_date: string | null
  /** v4 origin_actual_departure; null until the load departs (the 1900 sentinel). */
  departed: string | null
  status: string | null
  customer: string | null
  origin: string | null
  destination: string | null
  carrier: string | null
  profit: number | null
  revenue: number | null
  margin_pct: number | null
  contract_type: string | null
  equipment_type: string | null
  company_id: string | null
}

export interface PodiumOverview {
  range: PodiumRange
  basis: PodiumBasis
  status: PodiumStatus[]
  kpis: PodiumKpis
  rows: PodiumRow[]
}

// 15-min live refresh requested by product. staleTime < refetchInterval so the
// focus refetch triggers immediately on tab return.
const FIFTEEN_MIN = 15 * 60 * 1000

export function buildOverviewQs(
  range: PodiumRange,
  start: string | undefined,
  end: string | undefined,
  basis: PodiumBasis,
  statuses: readonly PodiumStatus[],
): string {
  const isCustom = range === "custom" && !!start && !!end
  const qs = new URLSearchParams()
  qs.set("range", isCustom ? "custom" : range)
  if (isCustom) {
    qs.set("start", start!)
    qs.set("end", end!)
  }
  if (basis !== "rate_conf") qs.set("basis", basis)
  // Repeated params, never comma-joined (§45 — the proxy forwards with append).
  for (const s of statuses) qs.append("status", s)
  return qs.toString()
}

export function usePodiumOverview(
  range: PodiumRange,
  start?: string,
  end?: string,
  basis: PodiumBasis = "rate_conf",
  statuses: readonly PodiumStatus[] = [],
) {
  const isCustom = range === "custom" && !!start && !!end
  // Canonical order so [D,P] and [P,D] share one cache entry; the key covers
  // every input of the query string (queryKey must cover qs()).
  const sortedStatuses = STATUS_OPTIONS.filter((s) => statuses.includes(s))
  const qs = buildOverviewQs(range, start, end, basis, sortedStatuses)
  return useQuery({
    queryKey: ["podium-dfw", "overview", qs],
    queryFn: () => apiFetch<PodiumOverview>(`custom/podium-dfw/overview?${qs}`),
    // Don't fire a half-built custom request (one date picked, other empty).
    enabled: range !== "custom" || isCustom,
    refetchInterval: FIFTEEN_MIN,
    refetchIntervalInBackground: false,
    staleTime: 5 * 60 * 1000,
    ...PODIUM_RETRY,
  })
}

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

export function fmtCurrency(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  const sign = v < 0 ? "-" : ""
  const n = Math.abs(v)
  return `${sign}$${n.toLocaleString("en-US", {
    maximumFractionDigits: 0,
  })}`
}

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  return v.toLocaleString("en-US")
}

export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—"
  return `${(v * 100).toFixed(1)}%`
}

export function fmtDateTime(iso: string | null): string {
  if (!iso) return "—"
  // DB stores CST already; Qlik displays full timestamp → match.
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const mm = String(d.getMonth() + 1).padStart(2, "0")
  const dd = String(d.getDate()).padStart(2, "0")
  const yy = String(d.getFullYear()).slice(-2)
  const hh = String(d.getHours()).padStart(2, "0")
  const mi = String(d.getMinutes()).padStart(2, "0")
  return `${mm}/${dd}/${yy} ${hh}:${mi}`
}
