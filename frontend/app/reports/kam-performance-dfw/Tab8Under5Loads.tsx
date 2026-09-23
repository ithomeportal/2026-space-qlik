"use client"

// Tab 8 — LOADS UNDER 5% (Bruno PDFs 2026-09-21 → 2026-09-23).
//
// R2: one row per LOAD (not per lane) and a YTD / MTD / WTD filter. Every DFW
// load whose OWN margin is under 5% — 4,998 of them YTD on 2026-09-23 — so the
// server pages and sorts; the summary line is `meta.totals`, the whole
// filtered set, never the visible page.
//
// ⚠ The expiration date and action plan are still per LANE (the Worst 10 Lanes
// rows): every load on a lane shows that lane's plan, and saving it on one
// load updates its siblings and the Worst 10 Lanes row.

import { useEffect, useState } from "react"
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Percent,
  Save,
} from "lucide-react"
import {
  useUnder5Loads,
  useUpsertLaneNote,
  type KamUnder5LoadRow,
  type KamUnder5Sort,
  type SortDir,
} from "@/lib/kam-performance-dfw-api"
import { DateRangeControl, useKamDateRange } from "./DateRangeControl"
import { SubTeamFilter } from "./SubTeamFilter"
import { fmtCount, fmtDate, fmtPct, fmtUsd } from "./format"

const PAGE_SIZE = 50

// Text columns open A→Z; numbers open worst-first (ascending: the most negative
// margin / profit, the smallest revenue) except dates, which open newest-first.
const FIRST_DIR: Record<KamUnder5Sort, SortDir> = {
  order_id: "asc",
  departure: "desc",
  customer: "asc",
  lane: "asc",
  team: "asc",
  revenue: "desc",
  profit: "asc",
  margin_pct: "asc",
}

const COLUMNS: { k: KamUnder5Sort; label: string; right?: boolean }[] = [
  { k: "order_id", label: "Order" },
  { k: "departure", label: "Departure" },
  { k: "customer", label: "Customer" },
  { k: "lane", label: "Lane" },
  { k: "team", label: "Team" },
  { k: "revenue", label: "Revenue", right: true },
  { k: "profit", label: "Profit", right: true },
  { k: "margin_pct", label: "Margin %", right: true },
]
const COL_SPAN = COLUMNS.length + 3 // + Expiration, Action plan, Save

export function Tab8Under5Loads() {
  const { value: range, setValue: setRangeRaw } = useKamDateRange("mtd")
  const [subTeams, setSubTeamsRaw] = useState<string[]>([])
  const [sort, setSort] = useState<KamUnder5Sort>("margin_pct")
  const [dir, setDir] = useState<SortDir>("asc")
  const [page, setPage] = useState(1)

  // Any change to WHAT is listed starts back at page 1.
  const setRange = (v: typeof range) => {
    setRangeRaw(v)
    setPage(1)
  }
  const setSubTeams = (v: string[]) => {
    setSubTeamsRaw(v)
    setPage(1)
  }
  const onSort = (k: KamUnder5Sort) => {
    if (k === sort) setDir(dir === "asc" ? "desc" : "asc")
    else {
      setSort(k)
      setDir(FIRST_DIR[k])
    }
    setPage(1)
  }

  const { data, isLoading, isFetching } = useUnder5Loads({
    range: range.range,
    start: range.start,
    end: range.end,
    subTeams,
    sort,
    dir,
    page,
    pageSize: PAGE_SIZE,
  })
  const upsert = useUpsertLaneNote()
  const rows = data?.data ?? []
  const meta = data?.meta
  const total = meta?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const threshold = meta?.threshold_pct ?? 5
  const first = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1
  const last = Math.min(page * PAGE_SIZE, total)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <DateRangeControl value={range} onChange={setRange} />
        <SubTeamFilter value={subTeams} onChange={setSubTeams} />
      </div>

      <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <Percent className="h-4 w-4 text-[#B45309]" />
          <div className="text-sm font-semibold text-[#1B3A5C]">
            Loads under {threshold}% margin
          </div>
          {meta && (
            <span className="rounded-full bg-[#FEF3C7] px-2 py-0.5 text-[10px] text-[#92400E]">
              {fmtCount(total)} {total === 1 ? "load" : "loads"} ·{" "}
              {fmtUsd(meta.totals.revenue)} revenue ·{" "}
              <span className={meta.totals.profit < 0 ? "text-[#991B1B]" : ""}>
                {fmtUsd(meta.totals.profit)} profit
              </span>
            </span>
          )}
          {isFetching && !isLoading && (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-[#6B7280]" />
          )}
        </div>
        <p className="mb-3 text-xs text-[#6B7280]">
          Every DFW load whose own margin came in under {threshold}% in the
          selected window — one row per load, billed loads only. A load at +3%
          is listed too, so this is a wider set than <em>Worst 10 Lanes</em>,
          which counts losing loads only. The expiration date and action plan
          are <strong>per lane</strong>: every load on a lane shows the same
          plan, and saving it here also updates that lane on{" "}
          <em>Worst 10 Lanes</em>.
        </p>
        <div className="overflow-auto">
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-[#6B7280]">
              <tr className="border-b border-[#E5E7EB]">
                {COLUMNS.map((c) => (
                  <th
                    key={c.k}
                    className={`px-2 py-1.5 ${c.right ? "text-right" : "text-left"}`}
                  >
                    <button
                      onClick={() => onSort(c.k)}
                      className={`inline-flex items-center gap-0.5 uppercase hover:text-[#1B3A5C] ${
                        sort === c.k ? "text-[#1B3A5C]" : ""
                      }`}
                    >
                      {c.label}
                      {sort === c.k &&
                        (dir === "asc" ? (
                          <ArrowUp className="h-3 w-3" />
                        ) : (
                          <ArrowDown className="h-3 w-3" />
                        ))}
                    </button>
                  </th>
                ))}
                <th className="px-2 py-1.5 text-left">Expiration</th>
                <th className="px-2 py-1.5 text-left">Action plan (lane)</th>
                <th className="px-2 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={COL_SPAN} className="py-10 text-center">
                    <Loader2 className="mx-auto h-4 w-4 animate-spin text-[#6B7280]" />
                  </td>
                </tr>
              ) : rows.length === 0 ? (
                <tr>
                  <td colSpan={COL_SPAN} className="py-10 text-center text-[#9CA3AF]">
                    No loads under {threshold}% margin in this window
                  </td>
                </tr>
              ) : (
                rows.map((r) => (
                  <Under5LoadRow
                    key={r.order_id}
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
        {total > PAGE_SIZE && (
          <div className="mt-3 flex items-center justify-end gap-2 text-xs text-[#6B7280]">
            <span>
              {fmtCount(first)}–{fmtCount(last)} of {fmtCount(total)}
            </span>
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page <= 1}
              className="rounded-md border border-[#E5E7EB] p-1 hover:bg-[#F9FAFB] disabled:opacity-40"
              aria-label="Previous page"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <span>
              Page {page} / {pages}
            </span>
            <button
              onClick={() => setPage(Math.min(pages, page + 1))}
              disabled={page >= pages}
              className="rounded-md border border-[#E5E7EB] p-1 hover:bg-[#F9FAFB] disabled:opacity-40"
              aria-label="Next page"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>
      <div className="text-[10px] text-[#6B7280]">
        {meta?.window.start} → {meta?.window.end} · scope: TEAM-DFW · source:
        mcleod_gld_budget_report_v4 (billed loads, by actual departure)
      </div>
    </div>
  )
}

function Under5LoadRow({
  row,
  onSave,
  savePending,
}: {
  row: KamUnder5LoadRow
  onSave: (patch: {
    expiration_date?: string | null
    action_plan?: string
  }) => Promise<unknown>
  savePending: boolean
}) {
  const [exp, setExp] = useState(row.expiration_date ?? "")
  const [plan, setPlan] = useState(row.action_plan)

  // Re-sync when the lane's saved note changes (including from a sibling load).
  useEffect(() => {
    setExp(row.expiration_date ?? "")
    setPlan(row.action_plan)
  }, [row.lane_key, row.expiration_date, row.action_plan])

  const dirty = (row.expiration_date ?? "") !== exp || plan !== row.action_plan
  const losing = row.profit < 0

  return (
    <tr className="border-b border-[#F3F4F6] align-top last:border-0">
      <td className="px-2 py-2 tabular-nums">{row.order_id}</td>
      <td className="whitespace-nowrap px-2 py-2">{fmtDate(row.departure)}</td>
      <td className="max-w-[160px] truncate px-2 py-2" title={row.customer}>
        {row.customer}
      </td>
      <td className="max-w-[220px] truncate px-2 py-2" title={row.lane}>
        {row.lane}
      </td>
      <td className="px-2 py-2">{row.team ?? "—"}</td>
      <td className="px-2 py-2 text-right tabular-nums">{fmtUsd(row.revenue)}</td>
      <td
        className={`px-2 py-2 text-right tabular-nums ${losing ? "text-[#991B1B]" : ""}`}
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
