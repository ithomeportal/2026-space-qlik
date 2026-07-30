"use client"

// ---------------------------------------------------------------------------
// "Data as of …" — the header's pipeline-health signal.
//
// The header already shows "Last auto-refreshed", but that is when the BROWSER
// last refetched, not how old the underlying data is. Those two are easy to
// confuse, and the confusion is the dangerous kind: a stalled ETL renders
// identically to a quiet day, so a dead pipeline can sit unnoticed for days
// (exactly how a 3-day outage stayed hidden on another portal).
//
// The backend reports the STALEST source, because a dashboard is only as fresh
// as its worst feed.
// ---------------------------------------------------------------------------

import { useOppFreshness } from "@/lib/ops-portal-overview-api"

// The gold datalake refreshes every few minutes; these thresholds flag "the
// feed has clearly stopped" rather than normal lag.
const WARN_MINUTES = 90
const STALE_MINUTES = 240

function fmtAge(minutes: number): string {
  if (minutes < 1) return "just now"
  if (minutes < 60) return `${Math.round(minutes)}m ago`
  const hours = minutes / 60
  if (hours < 48) return `${Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}

// "2026-07-30T13:37:06" → "Jul 30, 13:37". Already CST — no tz maths (the gold
// datalake stores CST and the pool is pinned via _set_cst_session).
function fmtStamp(iso: string): string {
  const [datePart, timePart] = iso.split("T")
  if (!datePart || !timePart) return iso
  const [y, m, d] = datePart.split("-").map(Number)
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
  if (!y || !m || !d) return iso
  return `${months[m - 1]} ${d}, ${timePart.slice(0, 5)}`
}

export function DataFreshness() {
  const { data, isLoading, error } = useOppFreshness()
  const f = data?.data

  // Never render a reassuring-looking blank: if we cannot establish freshness,
  // say so, because "no signal" is itself the thing worth noticing.
  if (isLoading) return <div className="text-[11px] text-[#9CA3AF]">Data as of: checking…</div>
  if (error || !f?.as_of) {
    return <div className="text-[11px] text-[#9CA3AF]">Data as of: unavailable</div>
  }

  const age = f.age_minutes ?? 0
  const tone =
    age >= STALE_MINUTES ? "text-[#DC2626] font-semibold"
    : age >= WARN_MINUTES ? "text-[#B45309] font-medium"
    : "text-[#6B7280] font-medium"

  const detail = f.sources
    .map((s) => `${s.label}: ${s.updated_at ? fmtStamp(s.updated_at) : "—"}`)
    .join("\n")

  return (
    <div
      className="text-[11px] text-[#9CA3AF]"
      title={`Newest row per source (CST):\n${detail}\n\nShown value is the stalest — checked ${fmtStamp(f.checked_at)}`}
    >
      Data as of:{" "}
      <span className={tone}>
        {fmtStamp(f.as_of)} ({fmtAge(age)})
      </span>
      {age >= WARN_MINUTES && f.stalest && (
        <span className="text-[#9CA3AF]"> · {f.stalest} lagging</span>
      )}
    </div>
  )
}
