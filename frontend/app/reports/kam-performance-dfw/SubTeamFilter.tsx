"use client"

// DFW sub-team pill row (TM1..TM4) shared by the Service, Top 10 lanes,
// Worst Lanes and Carrier Sales tabs (Bruno KAM update — Team filter).
// Empty selection means "all sub-teams".

export const KAM_SUB_TEAMS = ["TM1", "TM2", "TM3", "TM4"] as const

export function SubTeamFilter({
  value,
  onChange,
}: {
  value: string[]
  onChange: (next: string[]) => void
}) {
  const toggle = (t: string) =>
    onChange(value.includes(t) ? value.filter((x) => x !== t) : [...value, t])

  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-wider text-[#6B7280]">
        Team
      </span>
      <div className="inline-flex overflow-hidden rounded-md border border-[#E5E7EB]">
        {KAM_SUB_TEAMS.map((t) => (
          <button
            key={t}
            onClick={() => toggle(t)}
            className={`px-3 py-1.5 text-xs ${
              value.includes(t)
                ? "bg-[#1B3A5C] text-white"
                : "bg-white text-[#374151] hover:bg-[#F9FAFB]"
            }`}
          >
            {t}
          </button>
        ))}
      </div>
      {value.length > 0 && (
        <button
          onClick={() => onChange([])}
          className="text-[10px] text-[#6B7280] underline hover:text-[#111827]"
        >
          Clear teams
        </button>
      )}
    </div>
  )
}
