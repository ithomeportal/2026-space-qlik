"use client"

import { useEffect, useState } from "react"
import { Loader2, Save, Truck } from "lucide-react"
import {
  useCarrierSales,
  useUpsertCarrierComment,
  type KamCarrierSalesRow,
} from "@/lib/kam-performance-dfw-api"
import { DateRangeControl, useKamDateRange } from "./DateRangeControl"
import { SubTeamFilter } from "./SubTeamFilter"
import { fmtCount, fmtUsd } from "./format"

export function Tab7CarrierSales() {
  const { value, setValue, bounds } = useKamDateRange("mtd")
  const [subTeams, setSubTeams] = useState<string[]>([])
  const { data, isLoading } = useCarrierSales(bounds, subTeams)
  const upsert = useUpsertCarrierComment()
  const rows = data?.data ?? []

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <DateRangeControl value={value} onChange={setValue} />
        <SubTeamFilter value={subTeams} onChange={setSubTeams} />
      </div>

      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="mb-1 flex items-center gap-2">
          <Truck className="h-4 w-4 text-[#1B3A5C]" />
          <div className="text-sm font-semibold text-[#1B3A5C]">Carrier Sales</div>
        </div>
        <p className="mb-3 text-xs text-[#6B7280]">
          Per-lane carrier intel for DFW — the 3 most-recently-used carriers and
          average carrier cost (override pay). Jot comments per lane.
        </p>
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                <th className="px-2 py-1.5 text-left">Lane</th>
                <th className="px-2 py-1.5 text-left">Carrier (latest 3)</th>
                <th className="px-2 py-1.5 text-right">Cost (avg)</th>
                <th className="px-2 py-1.5 text-right">Moves</th>
                <th className="px-2 py-1.5 text-left">Comments</th>
                <th className="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center">
                    <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-10 text-center text-[#9CA3AF]">
                    No carrier moves in this window
                  </td>
                </tr>
              ) : (
                rows.map((r) => (
                  <CarrierRow
                    key={r.lane_key}
                    row={r}
                    onSave={(comments) =>
                      upsert.mutateAsync({ lane_key: r.lane_key, comments })
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
        mcleod_gld_dispatchers ⨝ budget_report_v4
      </div>
    </div>
  )
}

function CarrierRow({
  row,
  onSave,
  savePending,
}: {
  row: KamCarrierSalesRow
  onSave: (comments: string) => Promise<unknown>
  savePending: boolean
}) {
  const [comments, setComments] = useState(row.comments)

  useEffect(() => {
    setComments(row.comments)
  }, [row.lane_key, row.comments])

  const dirty = comments !== row.comments

  return (
    <tr className="border-b border-[#F3F4F6] align-top last:border-0">
      <td className="max-w-[220px] truncate px-2 py-2" title={row.lane}>
        {row.lane}
      </td>
      <td className="max-w-[260px] px-2 py-2" title={row.carriers}>
        {row.carriers}
      </td>
      <td className="px-2 py-2 text-right tabular-nums">{fmtUsd(row.avg_cost)}</td>
      <td className="px-2 py-2 text-right tabular-nums text-[#6B7280]">
        {fmtCount(row.movements)}
      </td>
      <td className="px-2 py-2">
        <textarea
          rows={2}
          value={comments}
          onChange={(e) => setComments(e.target.value)}
          placeholder="Comments…"
          className="w-56 rounded-md border border-[#E5E7EB] bg-[#F9FAFB] p-1.5 text-xs"
        />
      </td>
      <td className="px-2 py-2">
        <button
          onClick={() => onSave(comments)}
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
