"use client"

import { useState } from "react"
import { Loader2, ArrowDown, ArrowUp, LineChart, AlertCircle } from "lucide-react"
import {
  useLossesWeeklyMovers,
  type LossesWeeklyMoverRow,
} from "@/lib/losses-lanes-api"
import { LossesErrorBanner } from "../ErrorBanner"

const USD0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})

const fmtUsd = (v: number | null | undefined) =>
  v === null || v === undefined || Number.isNaN(Number(v)) ? "—" : USD0.format(Number(v))

interface Props {
  teams: string[] | undefined
  customer: string | undefined
  onShowTrend: (lane: string) => void
}

export function WeeklyMovers({ teams, customer, onShowTrend }: Props) {
  const [topN, setTopN] = useState(10)
  const { data, isLoading, error } = useLossesWeeklyMovers(teams, customer, topN)
  const payload = data?.data

  const window = payload?.window
  const newEntries = payload?.new_entries ?? []
  const dropped = payload?.dropped ?? []
  const moved = payload?.moved ?? []

  return (
    <div className="space-y-3">
      <LossesErrorBanner errors={[error]} label="Weekly Movers" />
      <div className="flex items-center justify-between text-xs text-[#6B7280]">
        <div className="flex items-center gap-3">
          <AlertCircle className="h-4 w-4 text-[#B45309]" />
          <div>
            <div>Top-{topN} losing (customer, lane) pairs — week over week</div>
            {window && (
              <div className="text-[10px]">
                This week: {window.this_week.start} → {window.this_week.end} · Last week:{" "}
                {window.last_week.start} → {window.last_week.end}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <label>Top</label>
          <select
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value))}
            className="rounded border border-[#E5E7EB] bg-white px-2 py-1"
          >
            {[5, 10, 20, 30].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          {isLoading && <Loader2 className="h-4 w-4 animate-spin text-[#6B7280]" />}
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <MoversCard
          title="New entries (worse this week)"
          tone="red"
          rows={newEntries}
          kind="new"
          onShowTrend={onShowTrend}
        />
        <MoversCard
          title="Dropped out (better this week)"
          tone="green"
          rows={dropped}
          kind="dropped"
          onShowTrend={onShowTrend}
        />
        <MoversCard
          title="Rank-change (still in top)"
          tone="neutral"
          rows={moved}
          kind="moved"
          onShowTrend={onShowTrend}
        />
      </div>
    </div>
  )
}

interface MoversCardProps {
  title: string
  tone: "red" | "green" | "neutral"
  rows: LossesWeeklyMoverRow[]
  kind: "new" | "dropped" | "moved"
  onShowTrend: (lane: string) => void
}

function MoversCard({ title, tone, rows, kind, onShowTrend }: MoversCardProps) {
  const headerBg =
    tone === "red"
      ? "bg-[#FEE2E2] text-[#991B1B]"
      : tone === "green"
        ? "bg-[#D1FAE5] text-[#065F46]"
        : "bg-[#F3F4F6] text-[#374151]"

  return (
    <div className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className={`px-3 py-2 text-xs font-semibold uppercase tracking-wider ${headerBg}`}>
        {title} <span className="font-mono font-normal">({rows.length})</span>
      </div>
      <div className="max-h-[420px] overflow-auto">
        {rows.length === 0 ? (
          <div className="p-4 text-center text-xs text-[#6B7280]">
            No changes in this category.
          </div>
        ) : (
          <ul className="divide-y divide-[#F3F4F6]">
            {rows.map((r, i) => (
              <li key={`${r.customer ?? ""}-${r.lane ?? ""}-${i}`} className="p-2 text-xs">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-[#111827]">
                      {r.customer ?? "—"}
                    </div>
                    <div className="truncate text-[#374151]">{r.lane ?? "—"}</div>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-0.5">
                    <MoverBadge kind={kind} this_rank={r.this_rank} last_rank={r.last_rank} />
                    {r.lane && (
                      <button
                        onClick={() => onShowTrend(r.lane!)}
                        className="inline-flex items-center gap-1 rounded border border-[#E5E7EB] bg-white px-1.5 py-0.5 text-[10px] text-[#1B3A5C] hover:bg-[#F3F4F6]"
                        title="60-day lane trend"
                      >
                        <LineChart className="h-3 w-3" />
                        Trend
                      </button>
                    )}
                  </div>
                </div>
                <div className="mt-1 flex items-center justify-between text-[10px] text-[#6B7280]">
                  <span>
                    This: <span className="font-semibold text-[#B91C1C]">{fmtUsd(r.this_profit)}</span>
                    {r.this_revenue !== null && r.this_revenue !== undefined && (
                      <> · rev {fmtUsd(r.this_revenue)}</>
                    )}
                  </span>
                  <span>
                    Last: <span className="font-semibold text-[#374151]">{fmtUsd(r.last_profit)}</span>
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function MoverBadge({
  kind,
  this_rank,
  last_rank,
}: {
  kind: "new" | "dropped" | "moved"
  this_rank: number | null
  last_rank: number | null
}) {
  if (kind === "new") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded-full bg-[#FEE2E2] px-2 py-0.5 text-[10px] font-semibold text-[#991B1B]">
        NEW · #{this_rank}
      </span>
    )
  }
  if (kind === "dropped") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded-full bg-[#D1FAE5] px-2 py-0.5 text-[10px] font-semibold text-[#065F46]">
        OUT · was #{last_rank}
      </span>
    )
  }
  const delta = (last_rank ?? 0) - (this_rank ?? 0)    // positive = improved (moved up)
  const color = delta < 0
    ? "bg-[#FEE2E2] text-[#991B1B]"      // worse
    : "bg-[#D1FAE5] text-[#065F46]"      // better
  const icon = delta < 0 ? <ArrowDown className="h-2.5 w-2.5" /> : <ArrowUp className="h-2.5 w-2.5" />
  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-[10px] font-semibold ${color}`}
    >
      {icon}#{last_rank} → #{this_rank}
    </span>
  )
}
