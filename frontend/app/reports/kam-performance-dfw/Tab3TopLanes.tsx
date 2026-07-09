"use client"

import { useEffect, useState } from "react"
import { Loader2, Save, TrendingUp } from "lucide-react"
import {
  useDfwLaneKpi,
  useDfwTop10Lanes,
  useTopLanesNote,
  useUpsertTopLanesNote,
  useXrayDfwFilters,
} from "@/lib/kam-performance-dfw-api"
import { DateRangeControl, useKamDateRange } from "./DateRangeControl"
import { SubTeamFilter } from "./SubTeamFilter"
import { fmtCount, fmtPct, fmtUsd } from "./format"

export function Tab3TopLanes() {
  const { value, setValue, bounds } = useKamDateRange("wtd")
  const [customer, setCustomer] = useState("")
  const [subTeams, setSubTeams] = useState<string[]>([])

  const { data: filters } = useXrayDfwFilters()
  const { data: kpiRes, isLoading: loadingKpi } = useDfwLaneKpi(bounds, customer, subTeams)
  const { data: lanesRes, isLoading: loadingLanes } = useDfwTop10Lanes(bounds, customer, subTeams)
  const k = kpiRes?.data
  const lanes = lanesRes?.data ?? []
  const customers = filters?.data?.customers ?? []

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <DateRangeControl value={value} onChange={setValue} />
        <select
          value={customer}
          onChange={(e) => setCustomer(e.target.value)}
          className="rounded-md border border-[#E5E7EB] bg-white px-2 py-1.5 text-xs"
        >
          <option value="">All customers</option>
          {customers.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <SubTeamFilter value={subTeams} onChange={setSubTeams} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <KpiBox label="Loads" value={loadingKpi ? "…" : fmtCount(k?.loads)} />
        <KpiBox label="Revenue" value={loadingKpi ? "…" : fmtUsd(k?.revenue)} />
        <KpiBox label="Profit" value={loadingKpi ? "…" : fmtUsd(k?.profit)} />
        <KpiBox label="Margin %" value={loadingKpi ? "…" : fmtPct(k?.margin_pct)} />
      </div>
      <div className="text-[10px] text-[#6B7280]">
        {bounds.start} → {bounds.end} · scope: TEAM-DFW · GM C/O CTSI excluded ·
        source: xray-dfw-mng
      </div>

      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="mb-2 flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-[#1B3A5C]" />
          <div className="text-sm font-semibold text-[#1B3A5C]">
            Top 10 lanes by profit
          </div>
        </div>
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                <th className="px-2 py-1.5 text-left">#</th>
                <th className="px-2 py-1.5 text-left">Lane</th>
                <th className="px-2 py-1.5 text-right">Loads</th>
                <th className="px-2 py-1.5 text-right">Profit</th>
                <th className="px-2 py-1.5 text-right">Margin %</th>
              </tr>
            </thead>
            <tbody>
              {loadingLanes ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center">
                    <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                  </td>
                </tr>
              ) : lanes.length === 0 ? (
                <tr>
                  <td colSpan={5} className="py-8 text-center text-[#9CA3AF]">
                    No lanes in this window
                  </td>
                </tr>
              ) : (
                lanes.map((r, i) => (
                  <tr
                    key={r.lane}
                    className="border-b border-[#F3F4F6] last:border-0"
                  >
                    <td className="px-2 py-1.5 text-[#9CA3AF]">{i + 1}</td>
                    <td className="px-2 py-1.5">{r.lane}</td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {fmtCount(r.loads)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {fmtUsd(r.profit)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums">
                      {fmtPct(r.margin_pct)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <NoteCard />
    </div>
  )
}

function KpiBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-3 shadow-sm">
      <div className="text-[11px] uppercase tracking-wider text-[#6B7280]">
        {label}
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-[#1B3A5C]">
        {value}
      </div>
    </div>
  )
}

function NoteCard() {
  const { data, isLoading } = useTopLanesNote()
  const upsert = useUpsertTopLanesNote()
  const [draft, setDraft] = useState("")
  const [dirty, setDirty] = useState(false)
  const [savedAt, setSavedAt] = useState<string | null>(null)

  useEffect(() => {
    if (data?.data && !dirty) {
      setDraft(data.data.notes ?? "")
      setSavedAt(data.data.updated_at ?? null)
    }
  }, [data, dirty])

  const onSave = async () => {
    try {
      const res = await upsert.mutateAsync(draft)
      setSavedAt(res.data?.updated_at ?? null)
      setDirty(false)
    } catch {
      /* error surfaced via mutation state */
    }
  }

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-semibold text-[#1B3A5C]">
          What I will do to get more of these loads
        </div>
        <div className="flex items-center gap-2 text-[10px] text-[#6B7280]">
          {savedAt && !dirty && <span>Saved {new Date(savedAt).toLocaleString()}</span>}
          {dirty && <span className="text-[#92400E]">Unsaved changes</span>}
          <button
            onClick={onSave}
            disabled={!dirty || upsert.isPending}
            className="inline-flex items-center gap-1 rounded-md bg-[#1B3A5C] px-3 py-1 text-xs text-white shadow-sm hover:bg-[#152e49] disabled:opacity-50"
          >
            {upsert.isPending ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Save className="h-3 w-3" />
            )}
            Save
          </button>
        </div>
      </div>
      <textarea
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value)
          setDirty(true)
        }}
        disabled={isLoading}
        rows={5}
        placeholder="Concrete actions, lane owners to call, pricing levers, capacity asks…"
        className="w-full rounded-md border border-[#E5E7EB] bg-[#F9FAFB] p-2 text-xs"
      />
    </div>
  )
}
