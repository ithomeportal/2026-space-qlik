"use client"

// Tab 8 — LOADS UNDER 5% (Bruno PDF 2026-09-21).
//
// Every (customer, lane) pair whose margin is under 5% for the selected month,
// not a top-N: the server returns the whole list (the busiest month of 2026
// produced 241 lanes) and publishes `meta.truncated` if its runaway cap ever
// bites, so this table can never quietly stop short.
//
// ⚠ Same shape as Worst 10 Lanes, deliberately NOT the same numbers — that tab
// measures the negative-margin slice of a lane, this one measures the whole
// lane. The expiration date and action plan ARE the same rows.

import { useEffect, useState } from "react"
import { Loader2, Percent, Save } from "lucide-react"
import {
  kamDefaultMonth,
  useUnder5Lanes,
  useUpsertLaneNote,
  type KamUnder5LaneRow,
} from "@/lib/kam-performance-dfw-api"
import { MonthFilter } from "./MonthFilter"
import { SubTeamFilter } from "./SubTeamFilter"
import { fmtCount, fmtPct, fmtUsd } from "./format"

export function Tab8Under5Lanes() {
  const [month, setMonth] = useState<string>(() => kamDefaultMonth())
  const [subTeams, setSubTeams] = useState<string[]>([])
  const { data, isLoading } = useUnder5Lanes(month, subTeams)
  const upsert = useUpsertLaneNote()
  const rows = data?.data ?? []
  const meta = data?.meta

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <MonthFilter value={month} onChange={setMonth} />
        <SubTeamFilter value={subTeams} onChange={setSubTeams} />
      </div>

      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="mb-1 flex items-center gap-2">
          <Percent className="h-4 w-4 text-[#B45309]" />
          <div className="text-sm font-semibold text-[#1B3A5C]">
            Lanes under {meta?.threshold_pct ?? 5}% margin
          </div>
          {!isLoading && (
            <span className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[10px] text-[#92400E]">
              {fmtCount(rows.length)} {rows.length === 1 ? "lane" : "lanes"}
            </span>
          )}
        </div>
        <p className="mb-3 text-xs text-[#6B7280]">
          Every (customer, lane) pair for DFW whose margin came in under{" "}
          {meta?.threshold_pct ?? 5}% in the selected month —{" "}
          <strong>all</strong> of them, not a top 10. Loads, Revenue and Profit
          count <strong>every</strong> load on the lane (that is what the margin
          percentage is a percentage of), so a lane that also appears under{" "}
          <em>Worst 10 Lanes</em> shows smaller numbers there, where only the
          losing loads are counted. The expiration date and action plan are the
          same for both tabs — one plan per lane.
        </p>
        {meta?.truncated && (
          <p className="mb-3 rounded-md bg-[#FEF2F2] px-2 py-1.5 text-xs text-[#991B1B]">
            Showing the first {fmtCount(rows.length)} lanes — the list was cut
            off. Narrow the month or team filter.
          </p>
        )}
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                <th className="px-2 py-1.5 text-left">#</th>
                <th className="px-2 py-1.5 text-left">Customer</th>
                <th className="px-2 py-1.5 text-left">Lane</th>
                <th className="px-2 py-1.5 text-right">Loads</th>
                <th className="px-2 py-1.5 text-right">Revenue</th>
                <th className="px-2 py-1.5 text-right">Profit</th>
                <th className="px-2 py-1.5 text-right">Margin %</th>
                <th className="px-2 py-1.5 text-left">Expiration</th>
                <th className="px-2 py-1.5 text-left">Action plan</th>
                <th className="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={10} className="py-10 text-center">
                    <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={10} className="py-10 text-center text-[#9CA3AF]">
                    No lanes under {meta?.threshold_pct ?? 5}% margin this month
                  </td>
                </tr>
              ) : (
                rows.map((r, i) => (
                  <Under5LaneRow
                    key={r.lane_key}
                    rank={i + 1}
                    row={r}
                    onSave={(patch) =>
                      upsert.mutateAsync({ lane_key: r.lane_key, ...patch })
                    }
                    savePending={upsert.isPending}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
      <div className="text-[10px] text-[#6B7280]">
        {meta?.window.start} → {meta?.window.end} · worst margin first · scope:
        TEAM-DFW · source: mcleod_gld_budget_report_v4 (billed loads)
      </div>
    </div>
  )
}

function Under5LaneRow({
  rank,
  row,
  onSave,
  savePending,
}: {
  rank: number
  row: KamUnder5LaneRow
  onSave: (patch: {
    expiration_date?: string | null
    action_plan?: string
  }) => Promise<unknown>
  savePending: boolean
}) {
  const [exp, setExp] = useState(row.expiration_date ?? "")
  const [plan, setPlan] = useState(row.action_plan)

  // Re-sync when the underlying list (and its saved notes) changes.
  useEffect(() => {
    setExp(row.expiration_date ?? "")
    setPlan(row.action_plan)
  }, [row.lane_key, row.expiration_date, row.action_plan])

  const dirty = (row.expiration_date ?? "") !== exp || plan !== row.action_plan
  const losing = row.profit < 0

  return (
    <tr className="border-b border-[#F3F4F6] align-top last:border-0">
      <td className="px-2 py-2 text-[#9CA3AF]">{rank}</td>
      <td className="max-w-[160px] truncate px-2 py-2" title={row.customer}>
        {row.customer}
      </td>
      <td className="max-w-[220px] truncate px-2 py-2" title={row.lane}>
        {row.lane}
      </td>
      <td className="px-2 py-2 text-right tabular-nums">{fmtCount(row.loads)}</td>
      <td className="px-2 py-2 text-right tabular-nums">{fmtUsd(row.revenue)}</td>
      <td
        className={`px-2 py-2 text-right tabular-nums ${
          losing ? "text-[#991B1B]" : ""
        }`}
      >
        {fmtUsd(row.profit)}
      </td>
      <td
        className={`px-2 py-2 text-right tabular-nums ${
          losing ? "text-[#991B1B]" : "text-[#B45309]"
        }`}
      >
        {fmtPct(row.margin_pct)}
      </td>
      <td className="px-2 py-2">
        <input
          type="date"
          value={exp}
          onChange={(e) => setExp(e.target.value)}
          className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1 text-xs"
        />
      </td>
      <td className="px-2 py-2">
        <textarea
          rows={2}
          value={plan}
          onChange={(e) => setPlan(e.target.value)}
          placeholder="Action plan…"
          className="w-56 rounded-md border border-[#E5E7EB] bg-[#F9FAFB] p-1.5 text-xs"
        />
      </td>
      <td className="px-2 py-2">
        <button
          onClick={() => onSave({ expiration_date: exp || null, action_plan: plan })}
          disabled={!dirty || savePending}
          className="inline-flex items-center gap-1 rounded-md bg-[#1B3A5C] px-2.5 py-1 text-xs text-white shadow-sm hover:bg-[#152e49] disabled:opacity-40"
        >
          {savePending ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Save className="h-3 w-3" />
          )}
          Save
        </button>
      </td>
    </tr>
  )
}
