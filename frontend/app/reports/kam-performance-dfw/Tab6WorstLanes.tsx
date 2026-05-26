"use client"

import { useEffect, useState } from "react"
import { AlertTriangle, Loader2, Save } from "lucide-react"
import {
  useUpsertWorstLaneNote,
  useWorstLanes,
  type KamWorstLaneRow,
} from "@/lib/kam-performance-dfw-api"
import { DateRangeControl, useKamDateRange } from "./DateRangeControl"
import { fmtCount, fmtPct, fmtUsd } from "./format"

export function Tab6WorstLanes() {
  const { value, setValue, bounds } = useKamDateRange("ytd")
  const { data, isLoading } = useWorstLanes(bounds)
  const upsert = useUpsertWorstLaneNote()
  const rows = data?.data ?? []

  return (
    <div className="space-y-4">
      <DateRangeControl value={value} onChange={setValue} />

      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="mb-1 flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-[#991B1B]" />
          <div className="text-sm font-semibold text-[#1B3A5C]">Worst Lanes</div>
        </div>
        <p className="mb-3 text-xs text-[#6B7280]">
          Worst losing (customer, lane) pairs for DFW — same source as the
          daily Losses email (negative-margin loads only). Set an expiration
          date and action plan per lane; they persist as the list reshuffles.
        </p>
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
                    No losing lanes in this window
                  </td>
                </tr>
              ) : (
                rows.map((r, i) => (
                  <WorstLaneRow
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
        {bounds.start} → {bounds.end} · scope: TEAM-DFW · source:
        Losses Lanes (mcleod_gld_budget_report_v4)
      </div>
    </div>
  )
}

function WorstLaneRow({
  rank,
  row,
  onSave,
  savePending,
}: {
  rank: number
  row: KamWorstLaneRow
  onSave: (patch: { expiration_date?: string | null; action_plan?: string }) => Promise<unknown>
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
      <td className="px-2 py-2 text-right tabular-nums text-[#991B1B]">
        {fmtUsd(row.profit)}
      </td>
      <td className="px-2 py-2 text-right tabular-nums">{fmtPct(row.margin_pct)}</td>
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
