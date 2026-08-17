"use client"

import { useMemo } from "react"
import { Info } from "lucide-react"
import { Section, Segmented } from "./Section"
import {
  fmtDate,
  initials,
  type EmrPeopleFlow,
  type EmrPerson,
  type PeopleRange,
} from "@/lib/exec-meeting-recruitment-api"

const RANGES: { k: PeopleRange; label: string }[] = [
  { k: "6m", label: "6 months" },
  { k: "12m", label: "12 months" },
  { k: "all", label: "All" },
]

/** Parse an ISO date at local noon so a timezone offset can never shift the day. */
function at(iso: string): number {
  return new Date(`${iso.slice(0, 10)}T12:00:00`).getTime()
}

function monthTicks(from: number, to: number): { label: string; pct: number }[] {
  const out: { label: string; pct: number }[] = []
  const span = to - from
  if (span <= 0) return out
  const cursor = new Date(from)
  cursor.setDate(1)
  cursor.setHours(12, 0, 0, 0)
  // Cap the tick count so an "All" window spanning years stays readable.
  const months: Date[] = []
  while (cursor.getTime() <= to && months.length < 400) {
    if (cursor.getTime() >= from) months.push(new Date(cursor))
    cursor.setMonth(cursor.getMonth() + 1)
  }
  const step = Math.max(1, Math.ceil(months.length / 14))
  months.forEach((m, i) => {
    if (i % step !== 0) return
    out.push({
      label: m.toLocaleDateString("en-US", { month: "short" }),
      pct: ((m.getTime() - from) / span) * 100,
    })
  })
  return out
}

/**
 * Request 6 — "03 · PEOPLE FLOW", one line per employee from hire date to
 * departure date.
 *
 * Both dates come from the same time-off row, so nothing is joined. That is
 * deliberate: there is no reliable key linking a person to a FreshService
 * offboarding ticket, and a fuzzy name match would print a wrong departure date
 * beside a named employee. The cost is that these exit markers do not tie to
 * the Offboarding KPI in §02 — the footnote says so on screen.
 *
 * An inactive employee with no recorded exit date renders as a dashed,
 * open-ended line, never as an active one.
 */
export function PeopleFlow({
  data,
  loading,
  range,
  onRange,
  startDate,
  endDate,
  onStartDate,
  onEndDate,
}: {
  data?: EmrPeopleFlow
  loading: boolean
  range: PeopleRange
  onRange: (next: PeopleRange) => void
  startDate: string
  endDate: string
  onStartDate: (v: string) => void
  onEndDate: (v: string) => void
}) {
  const from = data ? at(data.window.from) : 0
  const to = data ? at(data.window.to) : 0
  const ticks = useMemo(() => monthTicks(from, to), [from, to])
  const rows = data?.rows ?? []

  return (
    <Section
      index="03"
      eyebrow="People flow"
      title="Recent Hires Timeline"
      subtitle={
        loading && !data
          ? "Loading…"
          : `${rows.length} hire${rows.length === 1 ? "" : "s"} in the selected window`
      }
      actions={
        <>
          <Segmented options={RANGES} value={range === "custom" ? "all" : range} onChange={onRange} />
          <div className="flex items-end gap-1.5 text-xs">
            <label className="flex flex-col gap-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-[#9CA3AF]">
                From
              </span>
              <input
                type="date"
                value={startDate}
                onChange={(e) => onStartDate(e.target.value)}
                className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
              />
            </label>
            <span className="pb-1.5 text-[#6B7280]">→</span>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-[#9CA3AF]">
                To
              </span>
              <input
                type="date"
                value={endDate}
                onChange={(e) => onEndDate(e.target.value)}
                className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1"
              />
            </label>
          </div>
        </>
      }
    >
      <Legend />

      {loading && !data ? (
        <div className="mt-4 space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-12 animate-pulse rounded-lg bg-[#F3F4F6]" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <p className="mt-6 text-center text-sm text-[#6B7280]">
          No hires in the selected window.
        </p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <div className="min-w-[820px]">
            {/* Month scale */}
            <div className="flex border-b border-[#E5E7EB] pb-1.5">
              <div className="w-[240px] shrink-0 text-[10px] font-semibold uppercase tracking-wider text-[#9CA3AF]">
                Person
              </div>
              <div className="relative h-4 flex-1">
                {ticks.map((t, i) => (
                  <span
                    key={`${t.label}-${i}`}
                    className="absolute -translate-x-1/2 text-[10px] text-[#9CA3AF]"
                    style={{ left: `${t.pct}%` }}
                  >
                    {t.label}
                  </span>
                ))}
              </div>
            </div>

            {rows.map((p) => (
              <PersonRow key={p.id} person={p} from={from} to={to} ticks={ticks} />
            ))}
          </div>
        </div>
      )}

      <p className="mt-4 flex items-start gap-1.5 text-[11px] leading-relaxed text-[#6B7280]">
        <Info className="mt-0.5 h-3 w-3 shrink-0 text-[#9CA3AF]" />
        <span>
          Hire and exit dates both come from the time-off record, so no two systems are
          matched by name here. These exit markers are therefore <em>not</em> the same
          figure as the Offboarding KPI above, which counts FreshService tickets.
        </span>
      </p>
    </Section>
  )
}

function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-4 text-[11px] text-[#6B7280]">
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-[#0F766E]" /> Onboarding
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-2 w-2 rounded-full bg-[#B91C1C]" /> Offboarding
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-0.5 w-5 bg-[#1B3A5C]" /> Active employee
      </span>
      <span className="flex items-center gap-1.5">
        <span className="h-0.5 w-5 border-t border-dashed border-[#9CA3AF]" /> Departed ·
        exit date not recorded
      </span>
    </div>
  )
}

function PersonRow({
  person,
  from,
  to,
  ticks,
}: {
  person: EmrPerson
  from: number
  to: number
  ticks: { label: string; pct: number }[]
}) {
  const span = to - from
  const pct = (t: number) => ((Math.min(Math.max(t, from), to) - from) / span) * 100

  const hire = at(person.hire_date)
  const left = pct(hire)

  // An unknown exit date must never be drawn as an active line running to today.
  const unknownExit = person.status === "departed_exit_unknown"
  const endTs =
    person.status === "departed" && person.exit_date ? at(person.exit_date) : to
  const right = pct(endTs)
  const width = Math.max(0, right - left)

  const title = [
    person.name,
    person.job_title ?? undefined,
    `Hired ${fmtDate(person.hire_date)}`,
    person.status === "active"
      ? "Active"
      : person.status === "departed"
        ? `Departed ${fmtDate(person.exit_date)}`
        : "Departed — exit date not recorded in the time-off system",
  ]
    .filter(Boolean)
    .join(" · ")

  return (
    <div className="flex items-center border-b border-[#F3F4F6] py-2.5" title={title}>
      <div className="flex w-[240px] shrink-0 items-center gap-2.5 pr-3">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#CCFBF1] text-[10px] font-semibold text-[#0F766E]">
          {initials(person.name)}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-xs font-semibold text-[#111827]">
            {person.name}
          </span>
          <span className="block truncate text-[11px] text-[#9CA3AF]">
            {person.job_title ?? person.department}
          </span>
        </span>
      </div>

      <div className="relative h-8 flex-1">
        {/* Gridlines aligned to the month scale */}
        {ticks.map((t, i) => (
          <span
            key={`g-${i}`}
            className="absolute top-0 h-full w-px bg-[#F3F4F6]"
            style={{ left: `${t.pct}%` }}
          />
        ))}

        <span
          className={`absolute top-1/2 h-0.5 -translate-y-1/2 ${
            unknownExit
              ? "border-t border-dashed border-[#9CA3AF]"
              : "rounded-full bg-[#1B3A5C]"
          }`}
          style={{ left: `${left}%`, width: `${width}%` }}
        />

        {/* Hire marker */}
        <span
          className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#0F766E] bg-white"
          style={{ left: `${left}%` }}
        />

        {/* Exit marker — only when the date is actually recorded */}
        {person.status === "departed" && person.exit_date ? (
          <span
            className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#B91C1C] bg-white"
            style={{ left: `${right}%` }}
          />
        ) : null}
      </div>
    </div>
  )
}
