"use client"

import { useQuery } from "@tanstack/react-query"

/**
 * Per-reader door-data health for every Access Log Doors report (2026-11-18).
 * Backed by `backend/app/routers/access_doors_feed_health.py`, mounted on the HR
 * router and on every scope-locked clone behind that report's own gate.
 *
 * Why: on 2026-11-16 the 2ND FLOOR reader stopped reaching the datalake while
 * 3F Door kept syncing, so the newest record stayed current and nothing looked
 * wrong — the reports simply showed most of the building as absent.
 */

export interface DoorReaderHealth {
  reader: string
  today: number
  baseline: number
  last_event: string | null // naive CST ISO, e.g. "2026-11-16T11:28:06"
  down: boolean
}

export interface DoorFeedHealth {
  date: string
  cutoff: string | null
  degraded: boolean
  building_degraded: boolean
  down: string[]
  total_today: number
  total_baseline: number
  readers: DoorReaderHealth[]
}

interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: string
}

async function fetchHealth(reportKey: string, date: string): Promise<ApiResponse<DoorFeedHealth>> {
  const q = new URLSearchParams({ date })
  const res = await fetch(`/api/proxy/custom/${reportKey}/door-feed-health?${q.toString()}`, {
    headers: { "Content-Type": "application/json" },
  })
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export function useDoorFeedHealth(reportKey: string, date: string) {
  return useQuery({
    queryKey: [reportKey, "door-feed-health", date],
    queryFn: () => fetchHealth(reportKey, date),
    enabled: Boolean(date),
    staleTime: 5 * 60 * 1000,
    // A health probe must never block or nag: one retry, never on auth.
    retry: (failureCount: number, error: unknown) => {
      const msg = error instanceof Error ? error.message : ""
      if (/\b401\b|\b403\b/.test(msg)) return false
      return failureCount < 1
    },
  })
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

/**
 * "2026-11-16T11:28:06" -> "Nov 16, 11:28 AM". Sliced by hand: the value is a
 * naive CST wall-clock time, and the Date constructor would read it as UTC and shift
 * it 5-6 hours.
 */
export function fmtNaiveCst(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso)
  if (!m) return iso
  const hour = Number(m[4])
  const h12 = hour % 12 === 0 ? 12 : hour % 12
  const ampm = hour < 12 ? "AM" : "PM"
  return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${h12}:${m[5]} ${ampm}`
}

/** One sentence per down reader; a building-wide line when no single reader explains it. */
export function describeDoorFeed(h: DoorFeedHealth): string[] {
  const lines = h.readers
    .filter((r) => r.down)
    .map((r) => {
      const usual = `usually ~${Math.round(r.baseline)} by this time`
      const since = r.last_event
        ? `since ${fmtNaiveCst(r.last_event)} CST`
        : "in the last 4 weeks"
      return r.today === 0
        ? `The ${r.reader} reader has no records ${since} (${usual}).`
        : `The ${r.reader} reader sent only ${r.today} records (${usual}); none ${since}.`
    })
  if (lines.length === 0 && h.building_degraded) {
    lines.push(
      `Only ${h.total_today} door records on this date (usually ~${Math.round(h.total_baseline)} by this time) — the door feed may be down.`,
    )
  }
  return lines
}
