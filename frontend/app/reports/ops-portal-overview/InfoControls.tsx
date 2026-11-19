"use client"

import { useState } from "react"
import { useOppFilters, type InfoGrain } from "@/lib/ops-portal-overview-api"

// Ops Portal Updates PDF (2026-11-18) R2-R4 — Monthly Performance, Monthly
// Projection and Budget Monthly Variance each lost their "Week" + "Team"
// buttons for ONE "Info" modal: the old Week matrix, an internal Team filter,
// and Day / Week / Month toggles with Week selected by default.
//
// ⚠ The Team filter here is LOCAL to the modal: it starts on the page's team
// pill and never writes back to it. On a team-locked portal (CORP T1–T4, DFW
// TM1–4) it renders the locked team as a badge — the backend pins the team on
// those routers anyway, so a crafted value could not widen the scope.

export const INFO_GRAINS: { value: InfoGrain; label: string; caption: string }[] = [
  { value: "day", label: "Day", caption: "last 12 days" },
  { value: "week", label: "Week", caption: "last 8 weeks (Mon–Sun)" },
  { value: "month", label: "Month", caption: "last 8 months" },
]

/** Grain + team state for one Info modal. Week is the default (request). */
export function useInfoState(pageTeam?: string) {
  const [grain, setGrain] = useState<InfoGrain>("week")
  const [team, setTeam] = useState<string>(pageTeam ?? "")
  return { grain, setGrain, team, setTeam }
}

/** "last 8 weeks (Mon–Sun) · TEAM2" — the modal header's subtitle. */
export function infoSubtitle(grain: InfoGrain, team: string, suffix?: string): string {
  const caption = INFO_GRAINS.find((g) => g.value === grain)?.caption ?? ""
  return [caption, team || "All teams", suffix].filter(Boolean).join(" · ")
}

const PILL = "rounded-full border px-3 py-1 text-xs transition-colors"
const PILL_ON = "border-[#1B3A5C] bg-[#1B3A5C] text-white"
const PILL_OFF = "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"

export function InfoToolbar({
  grain,
  onGrain,
  team,
  onTeam,
  lockedTeam,
}: {
  grain: InfoGrain
  onGrain: (g: InfoGrain) => void
  team: string
  onTeam: (t: string) => void
  lockedTeam?: string
}) {
  const { data } = useOppFilters()
  const teams = data?.data?.teams ?? []
  return (
    <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-[#E5E7EB] px-4 py-2">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">Period</span>
        <div className="inline-flex overflow-hidden rounded-md border border-[#BFDBFE] text-xs font-medium" role="group">
          {INFO_GRAINS.map((g) => (
            <button
              key={g.value}
              type="button"
              onClick={() => onGrain(g.value)}
              aria-pressed={grain === g.value}
              title={g.caption}
              className={`px-3 py-1 ${
                grain === g.value ? "bg-[#2563EB] text-white" : "bg-white text-[#2563EB] hover:bg-[#EFF6FF]"
              }`}
            >
              {g.label}
            </button>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">Team</span>
        {lockedTeam ? (
          <span className={`${PILL} ${PILL_ON}`} title="This portal is locked to one team">
            {lockedTeam}
          </span>
        ) : (
          <div className="flex flex-wrap gap-1">
            <button type="button" onClick={() => onTeam("")} className={`${PILL} ${team === "" ? PILL_ON : PILL_OFF}`}>
              All
            </button>
            {teams.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => onTeam(t)}
                className={`${PILL} ${team === t ? PILL_ON : PILL_OFF}`}
              >
                {t}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
