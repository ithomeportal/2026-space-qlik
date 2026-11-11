"use client"

import { useQuery } from "@tanstack/react-query"
import { AlertTriangle } from "lucide-react"

/**
 * "McLeod data stopped updating" strip above every report (§143 v5, 2026-11-11).
 *
 * The McLeod → gold load stopped at 13:20 CST on 11-11 while Production, XRay,
 * Division Payment… kept rendering 13:20 numbers as if they were current. The
 * backend decides "stopped" with the hourly watchdog's evidence rule (v4 silent
 * > 2 h AND McLeod recorded stops since), cached 5 min — a quiet night is not a
 * stop. Unknown / error / loading ⇒ nothing renders: a banner must never break
 * or block a report.
 *
 * ⚠ `last_write` is a NAIVE CST ISO string — never `new Date(...)` it (§116):
 * the browser would read it in ITS zone. The parts are sliced out as text.
 */

interface GoldStatus {
  stopped: boolean
  unknown: boolean
  last_write: string | null
  silent_minutes: number | null
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
const FIVE_MIN = 5 * 60 * 1000

async function fetchGoldStatus(): Promise<GoldStatus | null> {
  const res = await fetch("/api/proxy/data-status/gold")
  if (!res.ok) return null
  const body = (await res.json()) as { success?: boolean; data?: GoldStatus }
  return body.success && body.data ? body.data : null
}

export function formatCstStamp(iso: string): string {
  const [date, time = ""] = iso.split("T")
  const [, month, day] = date.split("-").map(Number)
  const label = MONTHS[(month || 1) - 1] ?? ""
  return `${label} ${day}, ${time.slice(0, 5)} CST`
}

export function formatSilent(minutes: number): string {
  if (minutes < 120) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

export function GoldStaleBanner() {
  const { data } = useQuery({
    queryKey: ["gold-status"],
    queryFn: fetchGoldStatus,
    staleTime: FIVE_MIN,
    refetchInterval: FIVE_MIN,
    retry: false,
  })
  if (!data?.stopped || !data.last_write) return null
  const silent = data.silent_minutes == null ? "" : ` (${formatSilent(data.silent_minutes)} ago)`
  return (
    <div
      role="status"
      className="flex items-start gap-2 border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <p>
        <span className="font-semibold">McLeod data stopped updating at {formatCstStamp(data.last_write)}</span>
        {silent}. Reports built on McLeod data show that time&apos;s state until the load resumes;
        Data / BI has been notified.
      </p>
    </div>
  )
}
