"use client"

import { useMemo, useState } from "react"
import { Clock, Search } from "lucide-react"
import { Section } from "./Section"
import { fmtDate, type EmrOpenRoles } from "@/lib/exec-meeting-recruitment-api"

/** Age bands for the left accent rule — older roles read hotter. */
function accentFor(days: number): string {
  if (days >= 90) return "#B91C1C"
  if (days >= 60) return "#D97706"
  if (days >= 30) return "#CA8A04"
  return "#0F766E"
}

/**
 * Request 7 — "05 · OPEN CAPACITY".
 *
 * "Open" means Position.status = 'ACTIVE'. DRAFT (shown as BENCH in the Jobs
 * portal), PAUSED, CLOSED and CANCELLED are all excluded. Age is measured from
 * the position's createdAt, in CST.
 */
export function OpenCapacity({
  data,
  loading,
}: {
  data?: EmrOpenRoles
  loading: boolean
}) {
  const [term, setTerm] = useState("")

  const rows = useMemo(() => {
    const all = data?.rows ?? []
    const q = term.trim().toLowerCase()
    if (!q) return all
    return all.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.department.toLowerCase().includes(q) ||
        r.company.toLowerCase().includes(q)
    )
  }, [data, term])

  return (
    <Section
      index="05"
      eyebrow="Open capacity"
      title="Open roles"
      subtitle="Positions that are still active."
      actions={
        <label className="flex items-center gap-2 rounded-lg border border-[#E5E7EB] bg-white px-2.5 py-1.5">
          <Search className="h-3.5 w-3.5 text-[#9CA3AF]" />
          <input
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            placeholder="Search roles"
            aria-label="Search open roles"
            className="w-40 bg-transparent text-xs outline-none placeholder:text-[#9CA3AF]"
          />
        </label>
      }
    >
      <div className="flex items-center justify-between border-b border-[#E5E7EB] pb-3">
        <span className="text-xs text-[#6B7280]">
          <span className="font-serif text-lg font-semibold tabular-nums text-[#111827]">
            {data?.open_roles ?? "—"}
          </span>{" "}
          open role{data?.open_roles === 1 ? "" : "s"}
          {data ? (
            <span className="text-[#9CA3AF]"> · {data.open_vacancies} vacancies</span>
          ) : null}
        </span>
        <span className="flex items-center gap-1.5 text-[11px] text-[#6B7280]">
          <Clock className="h-3 w-3" />
          {data ? `${data.avg_days_open} days on average` : "—"}
        </span>
      </div>

      {loading && !data ? (
        <div className="mt-3 space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-14 animate-pulse rounded-lg bg-[#F3F4F6]" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="mt-6 text-center text-sm text-[#6B7280]">
          {term ? "No roles match that search." : "No open roles."}
        </p>
      ) : (
        <ul className="divide-y divide-[#F3F4F6]">
          {rows.map((r) => (
            <li key={r.id} className="flex items-center gap-3 py-3">
              <span
                className="h-9 w-1 shrink-0 rounded-full"
                style={{ backgroundColor: accentFor(r.days_open) }}
              />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-semibold text-[#111827]">{r.name}</div>
                <div className="truncate text-[11px] text-[#6B7280]">
                  {r.department} · {r.company}
                </div>
                <div className="text-[10px] text-[#9CA3AF]">
                  Open since {fmtDate(r.opened_on)}
                  {r.vacancies > 1
                    ? ` · ${r.open_vacancies} of ${r.vacancies} seats still open`
                    : ""}
                </div>
              </div>
              <div className="shrink-0 text-right">
                <div className="font-serif text-xl font-semibold tabular-nums text-[#111827]">
                  {r.days_open}d
                </div>
                <div className="text-[10px] text-[#9CA3AF]">open</div>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-2 border-t border-[#E5E7EB] pt-2 text-[10px] text-[#9CA3AF]">
        Sorted by age · counted from the date the position was created
      </div>
    </Section>
  )
}
