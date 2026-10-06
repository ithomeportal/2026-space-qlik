"use client"

import type { BookerRankWeek, RankPeriod, RankWindow } from "@/lib/booker-scorecard-api"

/** The Rank tab's Date control (Bruno PDF 2026-10-06 R1).
 *
 * ⚠ Its OWN state, never the Scorecard tab's `range`: that one is calendar
 * days on a Mon-Sun week, this one is the booking week turning at Friday
 * 5:01 PM CST. Sharing one URL param would carry a window across tabs that
 * means something different on the other side.
 *
 * Presets are resolved by the BACKEND from the CST clock — the browser only
 * names the preset, so a viewer in another timezone still gets Chicago Friday.
 */
export const RANK_PERIODS: { k: RankPeriod; label: string; title: string }[] = [
  { k: "week", label: "Booking Week", title: "Previous Friday 5:01 PM → coming Friday 5:00 PM (CST)" },
  { k: "last", label: "Last Booking Week", title: "The booking week before the current one" },
  { k: "mtd", label: "Month to Date", title: "1st of the month 00:00 → now (CST)" },
  { k: "custom", label: "Custom", title: "Pick a start and end, to the minute (CST)" },
]

const PERIOD_KEYS = new Set<string>(RANK_PERIODS.map((p) => p.k))
const MINUTE_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/
const YEAR_MIN = "2026-01-01T00:00"
const YEAR_MAX = "2026-12-31T23:59"

/** URL → window. An unknown period or a malformed Custom pair falls back to the
 *  default booking week rather than sending the backend a request it 400s. */
export function parseRankWindow(
  rawPeriod: string | null,
  rawStart: string | null,
  rawEnd: string | null,
): RankWindow {
  const period = rawPeriod && PERIOD_KEYS.has(rawPeriod) ? (rawPeriod as RankPeriod) : "week"
  if (period !== "custom") return { period }
  if (!rawStart || !rawEnd || !MINUTE_RE.test(rawStart) || !MINUTE_RE.test(rawEnd)) {
    return { period: "week" }
  }
  return { period, start: rawStart, end: rawEnd }
}

interface Props {
  win: RankWindow
  /** The window the server resolved for the current selection — used to
   *  prefill Custom, so switching to it starts from what is on screen. */
  resolved?: BookerRankWeek
  onChange: (patch: Record<string, string | null>) => void
}

export function RankDateFilter({ win, resolved, onChange }: Props) {
  const pick = (k: RankPeriod) => {
    if (k === "custom") {
      onChange({
        rr: "custom",
        rs: win.start ?? resolved?.start ?? YEAR_MIN,
        re: win.end ?? resolved?.end ?? YEAR_MAX,
      })
      return
    }
    // The default is encoded as the ABSENCE of the param (house pattern).
    onChange({ rr: k === "week" ? null : k, rs: null, re: null })
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="text-xs font-semibold uppercase tracking-wider text-[#6B7280]">
        Date
      </label>
      <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] text-xs">
        {RANK_PERIODS.map((opt) => (
          <button
            key={opt.k}
            onClick={() => pick(opt.k)}
            title={opt.title}
            className={`px-3 py-1.5 ${
              win.period === opt.k
                ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                : "text-[#6B7280] hover:text-[#111827]"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
      {win.period === "custom" && (
        <div className="flex items-center gap-1 text-xs">
          <input
            type="datetime-local"
            min={YEAR_MIN}
            max={YEAR_MAX}
            value={win.start ?? ""}
            onChange={(e) => e.target.value && onChange({ rs: e.target.value.slice(0, 16) })}
            className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
          />
          <span className="text-[#6B7280]">→</span>
          <input
            type="datetime-local"
            min={YEAR_MIN}
            max={YEAR_MAX}
            value={win.end ?? ""}
            onChange={(e) => e.target.value && onChange({ re: e.target.value.slice(0, 16) })}
            className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
          />
          <span className="text-[10px] text-[#9CA3AF]">CST, end inclusive</span>
        </div>
      )}
    </div>
  )
}
