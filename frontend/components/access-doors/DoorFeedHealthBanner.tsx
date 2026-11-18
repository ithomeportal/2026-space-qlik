"use client"

import { AlertTriangle } from "lucide-react"
import { describeDoorFeed, useDoorFeedHealth } from "@/lib/door-feed-health"

/**
 * Red banner shown on every Access Log Doors report when the door data for the
 * selected (end) date is incomplete — a normally busy reader gone silent, or
 * the whole feed far below its usual volume. Silent when healthy, loading or
 * on error: it is a warning, never a gate on the report.
 */
export function DoorFeedHealthBanner({ reportKey, date }: { reportKey: string; date: string }) {
  const q = useDoorFeedHealth(reportKey, date)
  const health = q.data?.data
  if (!health || !health.degraded) return null
  const lines = describeDoorFeed(health)

  return (
    <div
      role="alert"
      className="flex gap-3 rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800"
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="space-y-1">
        <p className="font-semibold">⚠ Door data incomplete for {health.date}</p>
        {lines.map((l) => (
          <p key={l}>{l}</p>
        ))}
        <p>
          People who badged in while it was down show as absent or late. This is a door-scanner/feed
          problem, not attendance — Infrastructure should check the reader.
        </p>
      </div>
    </div>
  )
}
