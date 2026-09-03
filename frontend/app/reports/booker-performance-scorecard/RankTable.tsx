"use client"

import { useMemo, useState } from "react"
import { ArrowDown, ArrowUp, Loader2, Minus } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useBookerRank,
  type BookerRankRow,
  type BookerScopeFilters,
} from "@/lib/booker-scorecard-api"
import { MultiSelectChips } from "@/components/MultiSelectChips"

interface Props {
  scope: BookerScopeFilters
  /** The page's Posted By selection, so the tab shares one picker with the
   *  rest of the report rather than inventing a second, divergent one. */
  postedBy: string[]
  onPostedByChange: (next: string[]) => void
}

/** Rank movement against the previous week.
 *
 * ⚠ null (a booker with no previous week) is NOT zero. A first appearance
 * renders as "new", because a flat dash beside it would claim the person held
 * their position — a position they never had.
 */
function Movement({ delta }: { delta: number | null }) {
  if (delta === null) {
    return <span className="text-[10px] font-medium text-[#6B7280]">new</span>
  }
  if (delta === 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[11px] text-[#9CA3AF]">
        <Minus className="h-3 w-3" />0
      </span>
    )
  }
  const up = delta > 0
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-[11px] font-semibold ${
        up ? "text-[#15803D]" : "text-[#B91C1C]"
      }`}
      title={`${up ? "Up" : "Down"} ${Math.abs(delta)} position${
        Math.abs(delta) === 1 ? "" : "s"
      } vs the previous week`}
    >
      {up ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />}
      {Math.abs(delta)}
    </span>
  )
}

type SortKey = "rank" | "booker" | "compliance" | "saving" | "bookings"

export function RankTable({ scope, postedBy, onPostedByChange }: Props) {
  const { data, isLoading, error } = useBookerRank(scope)
  const [sortKey, setSortKey] = useState<SortKey>("rank")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc")

  // apiFetch returns the {success, data} envelope; BookerRank is the inner
  // payload, so this unwraps exactly one level (house pattern).
  const d = data?.data
  const rows: BookerRankRow[] = useMemo(() => d?.rows ?? [], [d])
  const total = d?.total_bookers ?? 0

  const sorted = useMemo(() => {
    const dir = sortDir === "asc" ? 1 : -1
    // `null` means "no answer", and is handled by the comparator rather than
    // by a sentinel number.
    //
    // ⚠ The sentinel form this replaced (`?? POSITIVE_INFINITY`) claimed in a
    // comment to sort nulls last in BOTH directions, and did not: +Infinity
    // sorts last ascending and FIRST descending. Harmless while the column was
    // "Broken Threshold" and read ascending; with the 2026-09-03 rename the
    // column inverted and its default sort is descending, so every booker with
    // no threshold coverage would have led the table under a heading that now
    // means "most compliant" — a verdict this data cannot support (§4).
    const val = (r: BookerRankRow): number | string | null => {
      switch (sortKey) {
        case "booker":
          return r.booker
        case "compliance":
          return r.compliance_threshold_pct
        case "saving":
          return r.cost_saving
        case "bookings":
          return r.bookings
        default:
          // An unranked booker (nothing booked this week) always sorts last.
          return r.rank
      }
    }
    return rows.slice().sort((a, b) => {
      const av = val(a)
      const bv = val(b)
      if (av === null || bv === null) {
        if (av === bv) return 0
        return av === null ? 1 : -1
      }
      if (typeof av === "string" || typeof bv === "string") {
        return String(av).localeCompare(String(bv)) * dir
      }
      return ((av as number) - (bv as number)) * dir
    })
  }, [rows, sortKey, sortDir])

  const toggle = (k: SortKey) => {
    if (k === sortKey) {
      setSortDir((p) => (p === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(k)
      // Rank and name read best ascending; the measures read best descending.
      setSortDir(k === "rank" || k === "booker" ? "asc" : "desc")
    }
  }

  const Th = ({
    label,
    k,
    align = "left",
    title,
  }: {
    label: string
    k: SortKey
    align?: "left" | "right"
    title?: string
  }) => (
    <th
      onClick={() => toggle(k)}
      title={title}
      className={`cursor-pointer select-none px-3 py-2 font-semibold text-[#374151] ${
        align === "right" ? "text-right" : "text-left"
      } hover:text-[#111827]`}
    >
      {label}
      {sortKey === k && (
        <span className="ml-1 text-[10px]">{sortDir === "asc" ? "▲" : "▼"}</span>
      )}
    </th>
  )

  const noThresholds = rows.length > 0 && rows.every((r) => r.broken_threshold === null)

  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-[#E5E7EB] px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-[#111827]">Rank</h2>
          {/* ⚠ The window is stated on screen. This tab ignores the Date
              filter in the bar above it, and an unlabelled table that quietly
              disagrees with the filter above it reads as a bug. */}
          <p className="mt-0.5 text-xs text-[#6B7280]">
            {d ? (
              <>
                Bookings for{" "}
                <span className="font-medium text-[#374151]">{d.week.label}</span>{" "}
                — the last complete Sat–Fri week — with movement against{" "}
                <span className="font-medium text-[#374151]">
                  {d.prev_week.label}
                </span>
                . Bookers only. Not affected by the Date filter.
              </>
            ) : (
              "The last complete Sat–Fri week, bookers only. Not affected by the Date filter."
            )}
          </p>
        </div>
        <MultiSelectChips
          label="Booker Name"
          options={d?.bookers ?? []}
          selected={postedBy}
          onChange={onPostedByChange}
          placeholder="All bookers"
          width={240}
          disabled={isLoading}
        />
      </div>

      {noThresholds && (
        <div className="border-b border-[#FDE68A] bg-[#FFFBEB] px-4 py-2 text-xs text-[#92400E]">
          Threshold source unavailable — Compliance Threshold and Cost Saving show —
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-xs">
          <thead className="border-b border-[#E5E7EB] bg-[#F9FAFB]">
            <tr>
              <Th
                label="Rank"
                k="rank"
                title="Position by # of Bookings this week, out of every roster booker who booked, and the positions moved since last week."
              />
              <Th label="Booker Name" k="booker" />
              <Th
                label="Compliance Threshold"
                k="compliance"
                align="right"
                title="Share of this week's bookings whose Carrier Cost came in AT or UNDER the threshold typed in Loads to Cover — 1 − Broken Threshold. Orders with no threshold count in neither half."
              />
              <Th
                label="Cost Saving"
                k="saving"
                align="right"
                title="Σ (threshold − Carrier Cost) over this week's bookings that came in UNDER their threshold."
              />
              <Th label="# of Bookings" k="bookings" align="right" />
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-[#6B7280]">
                  <Loader2 className="mx-auto h-4 w-4 animate-spin" />
                </td>
              </tr>
            )}
            {!!error && !isLoading && (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-[#B91C1C]">
                  Could not load the ranking.
                </td>
              </tr>
            )}
            {!isLoading && !error && sorted.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-[#6B7280]">
                  {/* ⚠ The Posted By selection is SHARED with the Scorecard
                      tab, whose picker lists everyone who posts Rate Confs.
                      This tab shows bookers only, so a name picked over there
                      can empty this table — say which of the two it is rather
                      than reporting "no bookings" for a week that had them. */}
                  {postedBy.length > 0
                    ? `None of the selected names are bookers with bookings in ${
                        d?.week.label ?? "the selected week"
                      }.`
                    : `No bookings in ${d?.week.label ?? "the selected week"}.`}
                </td>
              </tr>
            )}
            {sorted.map((r) => (
              <tr
                key={r.booker}
                className="border-b border-[#F3F4F6] last:border-0 hover:bg-[#F9FAFB]"
              >
                <td className="whitespace-nowrap px-3 py-1.5">
                  <span className="font-semibold text-[#111827]">
                    {r.rank ?? "—"}
                  </span>
                  <span className="text-[10px] text-[#9CA3AF]"> of {total}</span>
                  <span className="ml-2">
                    <Movement delta={r.rank_delta} />
                  </span>
                </td>
                <td className="px-3 py-1.5 text-[#111827]">{r.booker}</td>
                <td className="px-3 py-1.5 text-right">
                  {/* ⚠ compliance, NOT broken: the two are 1 − each other, so
                      rendering the wrong field looks entirely plausible and
                      inverts every verdict on the tab. The sub-count is the
                      server's `compliant_threshold`, never `threshold_orders −
                      broken_threshold` re-derived here — the count and the
                      percentage must come off one population (§96). */}
                  {r.compliance_threshold_pct === null ? (
                    <span className="text-[#9CA3AF]">—</span>
                  ) : (
                    <>
                      {fmtPct(r.compliance_threshold_pct)}
                      <span className="ml-1 text-[10px] text-[#9CA3AF]">
                        ({fmtCount(r.compliant_threshold)}/
                        {fmtCount(r.threshold_orders)})
                      </span>
                    </>
                  )}
                </td>
                <td className="px-3 py-1.5 text-right">
                  {r.cost_saving === null ? (
                    <span className="text-[#9CA3AF]">—</span>
                  ) : (
                    fmtUsd(r.cost_saving)
                  )}
                </td>
                <td className="px-3 py-1.5 text-right font-medium text-[#111827]">
                  {fmtCount(r.bookings)}
                  <span className="ml-1 text-[10px] text-[#9CA3AF]">
                    (prev {fmtCount(r.prev_bookings)})
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
