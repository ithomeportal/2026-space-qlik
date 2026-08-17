"use client"

import { Briefcase, Clock, Users } from "lucide-react"
import { fmtKpi, type EmrSummary } from "@/lib/exec-meeting-recruitment-api"

/**
 * Requests 3 + 4 — the two headline KPIs.
 *
 * "Open roles" shows the Open Vacancies figure the request names, and its
 * caption carries the position count alongside it. The two legitimately differ
 * (vacancies is a summed remainder, positions is a row count), so both are on
 * the card — a KPI must never disagree with the detail beneath it (§16).
 */
export function KpiCards({
  data,
  loading,
  scoped,
}: {
  data?: EmrSummary
  loading: boolean
  scoped: boolean
}) {
  if (loading && !data) {
    return (
      <div className="grid gap-4 md:grid-cols-2">
        {[0, 1].map((i) => (
          <div key={i} className="h-[132px] animate-pulse rounded-2xl bg-[#F3F4F6]" />
        ))}
      </div>
    )
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      {/* Active employees */}
      <div className="rounded-2xl border border-[#E5E7EB] bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between">
          <span className="text-xs font-semibold text-[#374151]">Active employees</span>
          <span className="rounded-lg bg-[#CCFBF1] p-1.5 text-[#0F766E]">
            <Users className="h-4 w-4" />
          </span>
        </div>
        <div className="mt-3 font-serif text-5xl font-semibold tabular-nums text-[#111827]">
          {fmtKpi(data?.active_employees)}
        </div>
        <div
          className="mt-2 text-[11px] text-[#6B7280]"
          title="Time-off people system, isActive = true. Excludes the ithome@ admin account and the SEEK / Oiltex / Presidency / DFW Presidency / Aviation departments — the same definition the Jobs portal uses."
        >
          {scoped ? "Within selected scope" : "Company-wide, active headcount"}
        </div>
      </div>

      {/* Open roles */}
      <div className="rounded-2xl border border-[#134E4A] bg-[#134E4A] p-5 text-white shadow-sm">
        <div className="flex items-start justify-between">
          <span className="text-xs font-semibold text-[#CCFBF1]">Open roles</span>
          <span className="rounded-lg bg-white/10 p-1.5 text-[#5EEAD4]">
            <Briefcase className="h-4 w-4" />
          </span>
        </div>
        <div className="mt-3 font-serif text-5xl font-semibold tabular-nums">
          {fmtKpi(data?.open_vacancies)}
        </div>
        <div
          className="mt-2 flex items-center gap-1.5 text-[11px] text-[#99F6E4]"
          title="Open Vacancies = the sum of (vacancies − already hired) across positions with status ACTIVE. It exceeds the number of positions when a role is hiring for more than one seat."
        >
          <Clock className="h-3 w-3" />
          {data
            ? `across ${data.open_roles} open position${data.open_roles === 1 ? "" : "s"} · ${data.avg_days_open} days open on average`
            : "—"}
        </div>
      </div>
    </div>
  )
}
