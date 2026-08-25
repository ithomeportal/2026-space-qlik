"use client"

import { useEffect, useMemo } from "react"
import { Loader2, X } from "lucide-react"
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import {
  fmtPct,
  fmtUsd,
  useOppTeamProjectionHistory,
  type OppFilters,
  type OppProjectionMonthRow,
  type OppProjectionPoint,
} from "@/lib/ops-portal-overview-api"

// Request 2026-08-25: *"show that section as the stock markets … which was (or
// is) the high for the current month, the lowest, and in % the variation. We
// need to start tracking this variation by month as well, to have clear the
// error-rate."*
//
// Two halves, because they answer two different questions:
//   1. the current month's PATH — where the number has been and where the
//      high/low sit on it;
//   2. a monthly OHLC ladder with the realised profit and the error, which is
//      the only thing that says how much the projection can be trusted.

interface Props {
  filters: OppFilters
  onClose: () => void
}

/** "08/20" — the axis and the high/low chips share one date format. */
function dayLabel(iso: string): string {
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}`
}

/** "Aug 26" for a month row. */
function monthLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00`)
  return d.toLocaleString("en-US", { month: "short", year: "2-digit" })
}

/** Error magnitude banding — the same thresholds the footer explains. */
function errCls(pct: number | null): string {
  if (pct === null) return "bg-[#F3F4F6] text-[#6B7280]"
  const a = Math.abs(pct)
  if (a <= 5) return "bg-[#DCFCE7] text-[#166534]"
  if (a <= 10) return "bg-[#FEF9C3] text-[#854D0E]"
  return "bg-[#FEE2E2] text-[#991B1B]"
}

export function ProjectionTrendModal({ filters, onClose }: Props) {
  const cf = {
    team: filters.team,
    customer: filters.customer,
    loadType: filters.loadType,
    lanes: filters.lanes,
    excludeLanes: filters.excludeLanes,
    carriers: filters.carriers,
    excludeCarriers: filters.excludeCarriers,
  }
  const { data, isLoading, error } = useOppTeamProjectionHistory(cf, true)
  const d = data?.data
  const cur = d?.current_month ?? null
  const months: OppProjectionMonthRow[] = d?.months ?? []

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  const points: OppProjectionPoint[] = useMemo(() => cur?.points ?? [], [cur])

  // Recharts needs a numeric domain that actually contains the high AND the
  // low; the auto domain clips a flat series to a hairline. Pad 6% either way.
  const domain = useMemo<[number, number]>(() => {
    if (!points.length) return [0, 1]
    const vals = points.map((p) => p.proj_profit)
    const lo = Math.min(...vals)
    const hi = Math.max(...vals)
    const pad = Math.max((hi - lo) * 0.06, Math.abs(hi) * 0.02, 1)
    return [lo - pad, hi + pad]
  }, [points])

  const chartData = useMemo(
    () => points.map((p) => ({ ...p, label: dayLabel(p.as_of_date) })),
    [points],
  )

  const untracked = d && !d.tracked
  const liveOnlyDays = cur ? cur.days - cur.backfilled_days : 0

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6"
      onMouseDown={onClose}
    >
      <div
        className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#E5E7EB] bg-[#F0F9FF] px-4 py-3">
          <div className="flex items-center gap-2">
            <span aria-hidden>🎯</span>
            <div className="text-sm font-semibold text-[#1B3A5C]">Projected Profit — Trend</div>
            <span className="text-xs text-[#6B7280]">
              · current month path · monthly high / low / error
            </span>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 text-[#6B7280] hover:bg-white hover:text-[#111827]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {isLoading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
            </div>
          )}
          {!!error && !isLoading && (
            <div className="rounded-lg border border-[#FCA5A5] bg-[#FEE2E2] px-3 py-2 text-xs text-[#991B1B]">
              Projection history query failed: {(error as Error).message}
            </div>
          )}

          {!isLoading && !error && untracked && (
            <div className="rounded-lg border border-[#FDE68A] bg-[#FEF9C3] px-3 py-2 text-xs text-[#854D0E]">
              {d?.untracked_reason === "filtered"
                ? "History is tracked for the unfiltered team scope only. Clear the customer / lane / carrier / contract-type filters to see the month's high and low."
                : "No history is tracked for this team selection. Pick a single team, or clear the team filter."}
            </div>
          )}

          {!isLoading && !error && !untracked && (
            <>
              {/* ---- Current-month ticker ------------------------------- */}
              <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Stat label="Now" value={fmtUsd(d?.live_proj_profit ?? 0)} strong />
                <Stat
                  label={`High${cur?.high_date ? ` · ${dayLabel(cur.high_date)}` : ""}`}
                  value={cur?.high === null || cur?.high === undefined ? "—" : fmtUsd(cur.high)}
                  tone="up"
                />
                <Stat
                  label={`Low${cur?.low_date ? ` · ${dayLabel(cur.low_date)}` : ""}`}
                  value={cur?.low === null || cur?.low === undefined ? "—" : fmtUsd(cur.low)}
                  tone="down"
                />
                <Stat
                  label="Range"
                  value={cur?.range_pct === null || cur?.range_pct === undefined ? "—" : fmtPct(cur.range_pct)}
                />
              </div>

              {points.length > 1 ? (
                <div className="mb-4 h-64 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
                      <CartesianGrid stroke="#F3F4F6" vertical={false} />
                      <XAxis
                        dataKey="label"
                        tick={{ fontSize: 10, fill: "#6B7280" }}
                        interval="preserveStartEnd"
                        minTickGap={16}
                      />
                      <YAxis
                        domain={domain}
                        tick={{ fontSize: 10, fill: "#6B7280" }}
                        width={70}
                        tickFormatter={(v: number) => fmtUsd(v)}
                      />
                      <Tooltip
                        formatter={(v) => [fmtUsd(Number(v)), "Proj. Profit"]}
                        labelFormatter={(l) => `As of ${l}`}
                        contentStyle={{ fontSize: 12 }}
                      />
                      <Line
                        type="monotone"
                        dataKey="proj_profit"
                        stroke="#1B3A5C"
                        strokeWidth={2}
                        dot={false}
                        isAnimationActive={false}
                      />
                      {/* High/low markers. ⚠ ReferenceDot needs x to match the
                          XAxis dataKey VALUE, not the date — the axis is
                          categorical on `label`. */}
                      {cur?.high_date && cur.high !== null && (
                        <ReferenceDot
                          x={dayLabel(cur.high_date)}
                          y={cur.high}
                          r={4}
                          fill="#16A34A"
                          stroke="#FFFFFF"
                          strokeWidth={2}
                        />
                      )}
                      {cur?.low_date && cur.low !== null && (
                        <ReferenceDot
                          x={dayLabel(cur.low_date)}
                          y={cur.low}
                          r={4}
                          fill="#DC2626"
                          stroke="#FFFFFF"
                          strokeWidth={2}
                        />
                      )}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="mb-4 rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] px-3 py-6 text-center text-xs text-[#6B7280]">
                  Not enough days recorded this month yet to draw a path.
                </div>
              )}

              {cur && cur.settled_range_pct !== null && (
                <div className="mb-4 rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2 text-[11px] text-[#6B7280]">
                  Days 1–{(cur.settled_from_business_day ?? 5) - 1} of a month are almost pure
                  extrapolation — the month-to-date leg is still near zero — so they dominate the
                  raw range. From business day {cur.settled_from_business_day} onward the range is{" "}
                  <span className="font-semibold text-[#111827]">
                    {fmtPct(cur.settled_range_pct)}
                  </span>
                  {cur.settled_high !== null && cur.settled_low !== null && (
                    <>
                      {" "}
                      ({fmtUsd(cur.settled_low)} – {fmtUsd(cur.settled_high)})
                    </>
                  )}
                  .
                </div>
              )}

              {/* ---- Monthly OHLC + error ------------------------------- */}
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#1B3A5C]">
                Monthly high / low vs what actually landed
              </div>
              {months.length === 0 ? (
                <div className="rounded-lg border border-[#E5E7EB] bg-[#F9FAFB] px-3 py-4 text-center text-xs text-[#6B7280]">
                  No closed months recorded yet.
                </div>
              ) : (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-[#E5E7EB] text-[#6B7280]">
                      <th className="px-2 py-2 text-left text-[10px] font-semibold uppercase tracking-wider">
                        Month
                      </th>
                      <th className="px-2 py-2 text-right font-semibold">Open</th>
                      <th className="px-2 py-2 text-right font-semibold">High</th>
                      <th className="px-2 py-2 text-right font-semibold">Low</th>
                      <th className="px-2 py-2 text-right font-semibold">Close</th>
                      <th className="px-2 py-2 text-right font-semibold">Range</th>
                      <th className="px-2 py-2 text-right font-semibold text-[#1B3A5C]">Actual</th>
                      <th className="px-2 py-2 text-right font-semibold text-[#1B3A5C]">Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...months].reverse().map((m) => (
                      <tr key={m.month_start} className="border-b border-[#F3F4F6]">
                        <td className="px-2 py-1.5 font-medium text-[#374151]">
                          {monthLabel(m.month_start)}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-[#6B7280]">
                          {m.open === null ? "—" : fmtUsd(m.open)}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-[#166534]">
                          {fmtUsd(m.high)}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-[#991B1B]">
                          {fmtUsd(m.low)}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-[#374151]">
                          {m.close === null ? "—" : fmtUsd(m.close)}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-[#6B7280]">
                          {m.range_pct === null ? "—" : fmtPct(m.range_pct)}
                        </td>
                        <td className="px-2 py-1.5 text-right font-semibold tabular-nums text-[#1B3A5C]">
                          {m.actual_profit === null ? "—" : fmtUsd(m.actual_profit)}
                        </td>
                        <td className="px-2 py-1.5 text-right tabular-nums">
                          <span className={`rounded px-1.5 py-0.5 font-semibold ${errCls(m.error_pct)}`}>
                            {m.error_pct === null ? "—" : fmtPct(m.error_pct)}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              <div className="mt-3 text-[10px] leading-relaxed text-[#9CA3AF]">
                <span className="font-semibold">Error</span> = the month&apos;s LAST projection vs
                the profit that actually landed, signed so a standing bias is visible. Green ≤5%,
                amber ≤10%, red above.{" "}
                {cur && cur.backfilled_days > 0 && (
                  <>
                    {liveOnlyDays} of this month&apos;s {cur.days} points were observed live; the
                    rest were replayed from <code>budget_report_v4</code> and are approximate — a
                    load posted late appears in a replay that could not have seen it.
                  </>
                )}{" "}
                Snapshots are taken at 02:45 CST (each day&apos;s opening value); today&apos;s point
                is the live figure shown on the panel.
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({
  label,
  value,
  tone,
  strong,
}: {
  label: string
  value: string
  tone?: "up" | "down"
  strong?: boolean
}) {
  const color =
    tone === "up" ? "text-[#166534]" : tone === "down" ? "text-[#991B1B]" : "text-[#1B3A5C]"
  return (
    <div className="rounded-lg border border-[#E5E7EB] bg-white px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">{label}</div>
      <div className={`tabular-nums ${strong ? "text-base font-bold" : "text-sm font-semibold"} ${color}`}>
        {value}
      </div>
    </div>
  )
}
