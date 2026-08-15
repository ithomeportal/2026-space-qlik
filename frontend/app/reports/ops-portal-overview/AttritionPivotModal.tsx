"use client"

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-08-14) R3 — a button on the right of the "Actuals" header
// opens the Performance Trends pivot from /reports/attrition-wow?tab=pivots,
// without leaving the Ops Portal.
//
// This is a BORROWED endpoint (§52), not a copy of the query:
//   * the backend gate on /custom/attrition-wow/pivot is multi-key, so an
//     ops-portal viewer who has no attrition-wow role still gets data. A 403
//     here would render as an empty table, not an error — hence the widened
//     gate rather than a role grant.
//   * the scope param is PINNED. Ops Portal's universe is CORP_TEAMS
//     (TEAM1..TEAM5) — never TEAM-DFW — so with no team selected we pin all
//     five rather than letting Attrition fall back to its own "all teams"
//     default, which would silently add DFW volume to a CORP panel.
// ---------------------------------------------------------------------------

import { useEffect, useMemo } from "react"
import { X } from "lucide-react"
import type { OppFilters } from "@/lib/ops-portal-overview-api"
import type { AttritionFilters } from "@/lib/attrition-wow-api"
import { PivotsTab } from "../attrition-wow/tabs/PivotsTab"

/** Ops Portal's own team universe — mirrors CORP_TEAMS in
 *  backend/app/routers/ops_portal_overview.py. */
const CORP_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"]

export default function AttritionPivotModal({
  filters,
  onClose,
}: {
  filters: OppFilters
  onClose: () => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  // Only the dimensions both reports actually share are carried across.
  // Ops Portal's date range is deliberately NOT mapped: Attrition has no date
  // filter at all — every figure is anchored to the last completed Mon-Sun
  // week — so pretending the range applied would be a lie on screen.
  const attritionFilters: AttritionFilters = useMemo(
    () => ({
      teams: filters.team ? [filters.team] : CORP_TEAMS,
      customer: filters.customer || undefined,
    }),
    [filters.team, filters.customer],
  )

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
          <span className="rounded-md bg-[#1B3A5C] px-2 py-0.5 text-xs font-semibold uppercase text-white">
            Attrition
          </span>
          <span className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            Performance Trends · last completed week vs 8-week average
            {filters.team ? ` · ${filters.team}` : " · all CORP teams"}
            {filters.customer ? ` · ${filters.customer}` : ""}
          </span>
          <div className="ml-auto flex items-center gap-3 text-[10px] text-[#6B7280]">
            {/* Ops Portal's date range does not apply here — say so rather
                than let the reader assume the two panels share a window. */}
            <span>Date range not applied</span>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="text-[#6B7280] hover:text-[#111827]"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="overflow-auto px-3 py-3">
          <PivotsTab
            filters={attritionFilters}
            entityLabel="Customer"
            // Same defaults as the attrition report's own Pivots tab.
            defaultSortKey="diff"
            defaultSortDir="asc"
          />
        </div>
      </div>
    </div>
  )
}
