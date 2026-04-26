"use client"

import type { DCDivision, DCRange } from "@/lib/ops-direct-compare-api"

const ALL_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5", "TEAM-DFW"] as const
const CORP_TEAMS = ["TEAM1", "TEAM2", "TEAM3", "TEAM4", "TEAM5"] as const
const DFW_TEAMS = ["TEAM-DFW"] as const
const DFW_SUB_TEAMS = ["TM1", "TM2", "TM3", "TM4"] as const

interface Props {
  label: string                      // "Panel 1" / "Panel 2"
  yearStart: string
  yearEnd: string
  range: DCRange
  startDate: string
  endDate: string
  division: DCDivision
  teams: string[]
  subTeams: string[]
  onRange: (r: DCRange) => void
  onStartDate: (d: string) => void
  onEndDate: (d: string) => void
  onDivision: (d: DCDivision) => void
  onToggleTeam: (t: string) => void
  onToggleSubTeam: (st: string) => void
  accent: "blue" | "violet"
}

export function PanelFilters({
  label,
  yearStart,
  yearEnd,
  range,
  startDate,
  endDate,
  division,
  teams,
  subTeams,
  onRange,
  onStartDate,
  onEndDate,
  onDivision,
  onToggleTeam,
  onToggleSubTeam,
  accent,
}: Props) {
  const teamChipList: readonly string[] =
    division === "CORP" ? CORP_TEAMS : division === "DFW" ? DFW_TEAMS : ALL_TEAMS
  const accentClasses =
    accent === "blue"
      ? {
          ring: "border-[#BFDBFE]",
          tag: "bg-[#DBEAFE] text-[#1E40AF]",
          chipOn: "border-[#1B3A5C] bg-[#1B3A5C] text-white",
        }
      : {
          ring: "border-[#DDD6FE]",
          tag: "bg-[#EDE9FE] text-[#5B21B6]",
          chipOn: "border-[#5B21B6] bg-[#5B21B6] text-white",
        }

  return (
    <div className={`rounded-xl border ${accentClasses.ring} bg-white p-3 shadow-sm`}>
      <div className="mb-2 flex items-center gap-2">
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${accentClasses.tag}`}>
          {label}
        </span>
        <span className="text-xs text-[#6B7280]">
          {range === "custom"
            ? `${startDate} → ${endDate}`
            : range.replace("_", " ").toUpperCase()}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-3 text-xs">
        {/* Range presets */}
        <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB]">
          {[
            { k: "mtd" as const, label: "MTD" },
            { k: "last_month" as const, label: "Last Mo." },
            { k: "ytd" as const, label: "YTD" },
            { k: "custom" as const, label: "Custom" },
          ].map((opt) => (
            <button
              key={opt.k}
              onClick={() => onRange(opt.k)}
              className={`px-2.5 py-1 ${
                range === opt.k
                  ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                  : "text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {range === "custom" && (
          <div className="flex items-center gap-1">
            <input
              type="date"
              min={yearStart}
              max={yearEnd}
              value={startDate}
              onChange={(e) => onStartDate(e.target.value)}
              className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
            />
            <span className="text-[#6B7280]">→</span>
            <input
              type="date"
              min={yearStart}
              max={yearEnd}
              value={endDate}
              onChange={(e) => onEndDate(e.target.value)}
              className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
            />
          </div>
        )}

        {/* Division */}
        <div className="flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB]">
          {(["All", "CORP", "DFW"] as const).map((d) => (
            <button
              key={d}
              onClick={() => onDivision(d)}
              className={`px-2.5 py-1 ${
                division === d
                  ? "bg-white font-semibold text-[#1B3A5C] shadow-sm"
                  : "text-[#6B7280] hover:text-[#111827]"
              }`}
            >
              {d}
            </button>
          ))}
        </div>

        {/* Teams */}
        <div className="flex flex-wrap items-center gap-1">
          {teamChipList.map((t) => {
            const on = teams.includes(t)
            return (
              <button
                key={t}
                onClick={() => onToggleTeam(t)}
                className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
                  on
                    ? accentClasses.chipOn
                    : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                }`}
              >
                {t}
              </button>
            )
          })}
        </div>

        {/* DFW sub-teams */}
        {division === "DFW" && (
          <div className="flex items-center gap-1 border-l border-[#E5E7EB] pl-3">
            <span className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              sub
            </span>
            {DFW_SUB_TEAMS.map((st) => {
              const on = subTeams.includes(st)
              return (
                <button
                  key={st}
                  onClick={() => onToggleSubTeam(st)}
                  className={`rounded-full border px-2 py-0.5 text-[10px] ${
                    on
                      ? accentClasses.chipOn
                      : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F3F4F6]"
                  }`}
                >
                  {st}
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
