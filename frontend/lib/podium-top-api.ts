"use client"

import { keepPreviousData, useQuery } from "@tanstack/react-query"

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

const PODIUM_TOP_RETRY = {
  retry: (failureCount: number, error: unknown) => {
    const msg = error instanceof Error ? error.message : ""
    if (/\b401\b|\b403\b/.test(msg)) return false
    return failureCount < 2
  },
  retryDelay: (attempt: number) => Math.min(1000 * 2 ** attempt, 4000),
}

// ---------------------------------------------------------------------------
// Podium Top leaderboards (companion to Podium Set DFW) -- top 3 each
// ---------------------------------------------------------------------------

export interface PodiumWeekProfitRow {
  posted_by: string
  profit: number | null
  loads: number
}

export interface PodiumWeekMarginRow {
  posted_by: string
  margin_pct: number | null
  loads: number
  profit: number | null
  revenue: number | null
}

export interface PodiumLoadsRow {
  posted_by: string
  loads: number
}

// Bruno R4 (2026-05-12): Today rows now expose both loads + profit so each
// leaderboard renders both numbers regardless of primary sort.
export interface PodiumTodayRow {
  posted_by: string
  loads: number
  profit: number | null
}

export interface PodiumLeaderboards {
  week_top_profit: PodiumWeekProfitRow[]
  week_top_margin: PodiumWeekMarginRow[]
  week_top_loads:  PodiumLoadsRow[]
  today_top_loads: PodiumTodayRow[]
  today_top_profit: PodiumTodayRow[]
  locked_team: string | null
}

const FIFTEEN_MIN = 15 * 60 * 1000

// Bruno R1 (2026-06-09): "Bookers" (fixed roster, default) vs "All DFW".
export type BookerGroup = "bookers" | "all"

// `apiPrefix` lets the main report and the four server-locked per-team reports
// (Bruno R7: dfw-podium-top-tm1 … -tm4) share one hook. Defaults to the main
// all-DFW report. `equipment` (R8) is a server-side contains filter — pass the
// debounced value so each keystroke doesn't fire a request. `group` (R1,
// 2026-06-09) toggles the Bookers roster restriction server-side.
export function usePodiumTop(
  apiPrefix = "custom/dfw-podium-top",
  equipment = "",
  group: BookerGroup = "bookers",
) {
  const trimmed = equipment.trim()
  const params = new URLSearchParams()
  if (trimmed) params.set("equipment", trimmed)
  params.set("group", group)
  const qs = `?${params.toString()}`
  return useQuery({
    queryKey: [apiPrefix, "podiums", trimmed, group],
    queryFn: () => apiFetch<PodiumLeaderboards>(`${apiPrefix}/podiums${qs}`),
    refetchInterval: FIFTEEN_MIN,
    refetchIntervalInBackground: false,
    staleTime: 5 * 60 * 1000,
    // Keep showing the previous leaderboards while a new filter loads (§43).
    placeholderData: keepPreviousData,
    ...PODIUM_TOP_RETRY,
  })
}
