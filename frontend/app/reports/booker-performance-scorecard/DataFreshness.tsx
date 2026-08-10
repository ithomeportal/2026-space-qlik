"use client"

import { useBookerFreshness } from "@/lib/booker-scorecard-api"

const WARN_MINUTES = 90
const STALE_MINUTES = 240

/**
 * "Data as of …" chip showing the STALEST feed behind this report (§54).
 *
 * A failed call renders "unavailable", never a blank — an empty slot reads as
 * "everything is fine", which is exactly how a dead pipeline stays invisible.
 */

/**
 * ⚠ The server sends NAIVE CST strings (no offset, no `Z`), so
 * `new Date("2026-08-10T11:09:00")` would be parsed as *browser-local* and read
 * hours off for anyone outside America/Chicago. Format the wall-clock parts
 * directly and label them CST instead of round-tripping through a Date.
 */
function fmtCst(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso)
  if (!m) return iso
  const [, , mo, d, hh, mm] = m
  const h = Number(hh)
  const ampm = h >= 12 ? "PM" : "AM"
  const h12 = h % 12 === 0 ? 12 : h % 12
  return `${Number(mo)}/${Number(d)} ${h12}:${mm} ${ampm} CST`
}

const fmtAge = (mins: number) =>
  mins < 60
    ? `${Math.round(mins)} min ago`
    : `${(mins / 60).toFixed(1)} h ago`

export function DataFreshness() {
  const { data, error } = useBookerFreshness()
  const f = data?.data

  if (error || !f) {
    return (
      <span className="text-[10px] text-[#9CA3AF]">Data as of: unavailable</span>
    )
  }

  // A feed with no timestamp at all is DEAD, and outranks any "merely old" one.
  // The backend puts those in `unavailable`; surfacing them in red is the whole
  // point of the panel.
  const dead = f.unavailable ?? []
  if (dead.length > 0) {
    return (
      <span
        className="text-[10px] font-semibold text-[#991B1B]"
        title={f.sources
          .map((s) => `${s.label}: ${s.updated_at ?? "unavailable"}`)
          .join("\n")}
      >
        ⚠ {dead.join(", ")} feed{dead.length > 1 ? "s" : ""} unavailable
      </span>
    )
  }

  if (!f.as_of) {
    return (
      <span className="text-[10px] text-[#9CA3AF]">Data as of: unavailable</span>
    )
  }

  const age = f.age_minutes ?? 0
  const tone =
    age >= STALE_MINUTES
      ? "text-[#991B1B]"
      : age >= WARN_MINUTES
        ? "text-[#B45309]"
        : "text-[#6B7280]"

  const tooltip = f.sources
    .map(
      (s) =>
        `${s.label}: ${
          s.updated_at
            ? `${fmtCst(s.updated_at)} (${fmtAge(s.age_minutes ?? 0)})`
            : "unavailable"
        }`,
    )
    .join("\n")

  return (
    <span className={`text-[10px] ${tone}`} title={tooltip}>
      Data as of: {fmtCst(f.as_of)}
      {f.stalest ? ` · ${f.stalest}` : ""}
    </span>
  )
}
