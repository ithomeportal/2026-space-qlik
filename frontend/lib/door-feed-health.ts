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
  /** First / last record ON the date (up to the cutoff); null when none. */
  first_on_day?: string | null
  last_on_day?: string | null
  /** Newest record BEFORE the date — where a mid-day comeback's gap began. */
  prev_event?: string | null
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

/** "2026-11-18T14:19:06" -> "2:19 PM" (naive CST, sliced by hand like fmtNaiveCst). */
export function fmtNaiveCstTime(iso: string): string {
  const full = fmtNaiveCst(iso)
  const comma = full.indexOf(", ")
  return comma >= 0 ? full.slice(comma + 2) : full
}

/** Whole calendar days between two "YYYY-MM-DD…" strings (b − a), UTC-safe. */
function dayGap(a: string, b: string): number {
  const ms = Date.parse(`${b.slice(0, 10)}T00:00:00Z`) - Date.parse(`${a.slice(0, 10)}T00:00:00Z`)
  return Math.round(ms / 86_400_000)
}

const LATE_START_HOUR = 12

/**
 * A reader that sent SOME records on the date. Never "none since <last record>":
 * once a reader comes back mid-day (2ND FLOOR, 2026-11-18 14:19 after 11-16
 * 11:28) its newest record is fresh and that sentence is false. Instead state
 * the span it covered, and — when it had been silent for at least a whole day
 * before AND only started at noon or later — where the gap began.
 */
function partialReaderLine(r: DoorReaderHealth, usual: string): string {
  const head = `The ${r.reader} reader sent only ${r.today} records (${usual})`
  if (!r.first_on_day || !r.last_on_day) return `${head}.`
  const span =
    r.first_on_day === r.last_on_day
      ? `its only record was at ${fmtNaiveCstTime(r.first_on_day)} CST`
      : `they run ${fmtNaiveCstTime(r.first_on_day)} – ${fmtNaiveCstTime(r.last_on_day)} CST`
  // The gap clause only when the reader ALSO started late (noon or after): a
  // Monday whose previous record is Saturday afternoon is a weekend, not news.
  const startedLate = Number(r.first_on_day.slice(11, 13)) >= LATE_START_HOUR
  const gapBefore =
    r.prev_event && startedLate && dayGap(r.prev_event, r.first_on_day) >= 2
      ? `, and before that its last record was ${fmtNaiveCst(r.prev_event)} CST`
      : ""
  return `${head}; ${span}${gapBefore}.`
}

/** One sentence per down reader; a building-wide line when no single reader explains it. */
export function describeDoorFeed(h: DoorFeedHealth): string[] {
  const lines = h.readers
    .filter((r) => r.down)
    .map((r) => {
      const usual = `usually ~${Math.round(r.baseline)} by this time`
      if (r.today > 0) return partialReaderLine(r, usual)
      const since = r.last_event
        ? `since ${fmtNaiveCst(r.last_event)} CST`
        : "in the last 4 weeks"
      return `The ${r.reader} reader has no records ${since} (${usual}).`
    })
  if (lines.length === 0 && h.building_degraded) {
    lines.push(
      `Only ${h.total_today} door records on this date (usually ~${Math.round(h.total_baseline)} by this time) — the door feed may be down.`,
    )
  }
  return lines
}
