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

export type PodiumRange = "today" | "wtd" | "mtd"

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
  kpis: PodiumKpis
  rows: PodiumRow[]
}

// 15-min live refresh requested by product. staleTime < refetchInterval so the
// focus refetch triggers immediately on tab return.
const FIFTEEN_MIN = 15 * 60 * 1000

export function usePodiumOverview(range: PodiumRange) {
  return useQuery({
    queryKey: ["podium-dfw", "overview", range],
    queryFn: () => apiFetch<PodiumOverview>(`custom/podium-dfw/overview?range=${range}`),
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
