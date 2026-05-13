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

export interface PodiumByTeamEntry {
  team: string
  today_top_loads: PodiumTodayRow[]
  today_top_profit: PodiumTodayRow[]
}

export interface PodiumLeaderboards {
  week_top_profit: PodiumWeekProfitRow[]
  week_top_margin: PodiumWeekMarginRow[]
  week_top_loads:  PodiumLoadsRow[]
  today_top_loads: PodiumTodayRow[]
  today_top_profit: PodiumTodayRow[]
  by_team: PodiumByTeamEntry[]
}

const FIFTEEN_MIN = 15 * 60 * 1000

export function usePodiumTop() {
  return useQuery({
    queryKey: ["dfw-podium-top", "podiums"],
    queryFn: () => apiFetch<PodiumLeaderboards>(`custom/dfw-podium-top/podiums`),
    refetchInterval: FIFTEEN_MIN,
    refetchIntervalInBackground: false,
    staleTime: 5 * 60 * 1000,
    ...PODIUM_TOP_RETRY,
  })
}
