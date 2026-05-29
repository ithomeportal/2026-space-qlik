"use client"

import { useQuery } from "@tanstack/react-query"

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
  meta?: { cached?: boolean }
}

export type TileStatus =
  | "good"
  | "warn"
  | "bad"
  | "neutral"
  | "unavailable"
  | "locked"

export type TileUnit = "usd" | "pct" | "count"

export interface CockpitTile {
  key: string
  title: string
  category: string
  label: string
  unit: TileUnit
  deeplink: string
  value: number | null
  baseline: number | null
  delta_abs: number | null
  delta_pct: number | null
  status: TileStatus
  as_of: string | null
}

export interface CockpitLinkTile {
  key: string
  title: string
  category: string
  note: string | null
  deeplink: string
  status: "link"
}

export interface CockpitData {
  generated_at: string
  category_order: string[]
  tiles: CockpitTile[]
  link_tiles: CockpitLinkTile[]
}

async function apiFetch<T>(path: string): Promise<ApiResponse<T>> {
  const res = await fetch(`/api/proxy/${path}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export function useCockpitSummary() {
  return useQuery({
    queryKey: ["ceo-cockpit", "summary"],
    queryFn: () => apiFetch<CockpitData>("custom/ceo-cockpit/summary"),
    staleTime: 60 * 1000,
    refetchOnWindowFocus: false,
  })
}

// ---------------------------------------------------------------------------
// Formatting — compact, executive-friendly
// ---------------------------------------------------------------------------

export function fmtValue(value: number | null, unit: TileUnit): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—"
  if (unit === "pct") return `${value.toFixed(1)}%`
  if (unit === "count") return value.toLocaleString("en-US")
  return fmtCurrencyCompact(value)
}

export function fmtCurrencyCompact(value: number): string {
  const neg = value < 0
  const abs = Math.abs(value)
  let body: string
  if (abs >= 1_000_000) body = `$${(abs / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`
  else if (abs >= 1_000) body = `$${(abs / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}K`
  else body = `$${abs.toFixed(0)}`
  return neg ? `-${body}` : body
}

export function fmtDelta(deltaPct: number | null): string | null {
  if (deltaPct === null || deltaPct === undefined || Number.isNaN(deltaPct)) return null
  const arrow = deltaPct >= 0 ? "▲" : "▼"
  return `${arrow} ${Math.abs(deltaPct).toFixed(1)}%`
}

export function fmtAsOf(iso: string | null): string | null {
  if (!iso) return null
  // Accept "YYYY-MM-DD" or full ISO; show the date portion only.
  const datePart = iso.slice(0, 10)
  return datePart
}

export function fmtGeneratedAt(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}
