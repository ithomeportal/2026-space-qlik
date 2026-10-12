"use client"

import { useState } from "react"
import { Loader2 } from "lucide-react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"
import { fmtUsd } from "../../ops-margins/format"
import { DCErrorBanner } from "../ErrorBanner"
import { useDCTrendYoY, type DCYoYPoint } from "@/lib/ops-direct-compare-api"

type Mode = "revenue" | "profit" | "margin"

const MODES: ReadonlyArray<{ key: Mode; label: string }> = [
  { key: "revenue", label: "Revenue" },
  { key: "profit", label: "Profit" },
  { key: "margin", label: "Margin" },
]

const PREV_COLOR = "#94A3B8"
const CUR_COLOR = "#1B3A5C"

function pick(p: DCYoYPoint | null, mode: Mode): number | null {
  if (!p) return null
  if (mode === "margin") return p.margin_pct
  return p[mode]
}

function compactUsd(v: number): string {
  const a = Math.abs(v)
  if (a >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`
  if (a >= 1_000) return `$${(v / 1_000).toFixed(0)}k`
  return `$${v.toFixed(0)}`
}

/** Data label (Bruno PDF 2026-10-12 R1): compact, sign BEFORE the "$", and
 *  blank for a month with no value (the current year's future months). */
function dataLabel(v: unknown, mode: Mode): string {
  if (v === null || v === undefined || v === "") return ""
  const n = Number(v)
  if (!Number.isFinite(n)) return ""
  if (mode === "margin") return `${n.toFixed(1)}%`
  return n < 0 ? `-${compactUsd(-n)}` : compactUsd(n)
}

const LABEL_STYLE = { fontSize: 9 } as const

function fmtValue(v: unknown, mode: Mode): string {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—"
  return mode === "margin" ? `${Number(v).toFixed(2)}%` : fmtUsd(Number(v))
}

/**
 * Jan–Dec, previous year vs current year, with Revenue / Profit / Margin
 * buttons (Bruno PDF 2026-10-01 R4). Revenue = Σ total_charge, Profit =
 * Σ margin_amt, Margin = ΣProfit / ΣRevenue. Months the current year has not
 * reached have no current-year bar/point. Ignores both panels' filters.
 * No text strip under the chart (R5).
 *
 * Bruno PDF 2026-10-12: R1 every bar / point carries a data label; R2 the chart
 * has its OWN Team filter. That filter is LOCAL state on purpose — "must apply
 * exclusively to this chart": it never touches the URL the panels read, and the
 * panels' team pills never reach this chart. `teamOptions` is omitted on the
 * per-team clones (already one team; their router ignores `?teams=`).
 */
export function TrendYoY({
  scopeLabel,
  teamOptions,
}: {
  scopeLabel: string
  teamOptions?: readonly string[]
}) {
  const [mode, setMode] = useState<Mode>("revenue")
  // Empty = all teams. Deselecting the last team falls back to all, never to
  // an empty chart.
  const [teams, setTeams] = useState<readonly string[]>([])
  const toggleTeam = (t: string) =>
    setTeams((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  const allTeams = teams.length === 0 || (teamOptions !== undefined && teams.length === teamOptions.length)
  const { data, isLoading, error } = useDCTrendYoY(allTeams ? undefined : teams)
  const yoy = data?.data
  const prevKey = String(yoy?.prev_year ?? "Previous year")
  const curKey = String(yoy?.cur_year ?? "Current year")
  const title = yoy
    ? `Month by Month — ${yoy.prev_year} vs ${yoy.cur_year}`
    : "Month by Month — previous year vs current year"
  const rows = (yoy?.months ?? []).map((m) => ({
    label: m.label,
    [prevKey]: pick(m.prev, mode),
    [curKey]: pick(m.cur, mode),
  }))
  const chartScope = allTeams
    ? scopeLabel
    : (teamOptions ?? []).filter((t) => teams.includes(t)).join(", ")
  const label = (v: unknown) => dataLabel(v, mode)
  const yTick = (v: number) => (mode === "margin" ? `${v.toFixed(0)}%` : compactUsd(v))
  const tooltip = (
    <Tooltip
      formatter={(v) => fmtValue(v, mode)}
      contentStyle={{ fontSize: 11 }}
    />
  )

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4 shadow-sm">
      <DCErrorBanner errors={[error]} label={title} />
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-[#1B3A5C]">{title}</h3>
          <div className="text-[10px] uppercase tracking-wider text-[#6B7280]">
            {chartScope} · ignores both panels&apos; filters
          </div>
        </div>
        {teamOptions && (
          <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Chart team filter">
            <span className="mr-1 text-[10px] font-semibold uppercase tracking-wider text-[#6B7280]">
              Team
            </span>
            <button
              type="button"
              aria-pressed={allTeams}
              onClick={() => setTeams([])}
              className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
                allTeams
                  ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                  : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F9FAFB]"
              }`}
            >
              All
            </button>
            {teamOptions.map((t) => {
              const on = !allTeams && teams.includes(t)
              return (
                <button
                  key={t}
                  type="button"
                  aria-pressed={on}
                  onClick={() => toggleTeam(t)}
                  className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
                    on
                      ? "border-[#1B3A5C] bg-[#DBEAFE] text-[#1B3A5C]"
                      : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F9FAFB]"
                  }`}
                >
                  {t}
                </button>
              )
            })}
          </div>
        )}
        <div className="flex gap-1" role="group" aria-label="Metric">
          {MODES.map((m) => (
            <button
              key={m.key}
              type="button"
              aria-pressed={mode === m.key}
              onClick={() => setMode(m.key)}
              className={`rounded-md border px-3 py-1 text-xs font-medium ${
                mode === m.key
                  ? "border-[#1B3A5C] bg-[#1B3A5C] text-white"
                  : "border-[#E5E7EB] bg-white text-[#374151] hover:bg-[#F9FAFB]"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex h-80 items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-[#6B7280]" />
        </div>
      ) : rows.length === 0 ? (
        <div className="flex h-80 items-center justify-center text-xs text-[#6B7280]">
          No trend data.
        </div>
      ) : (
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            {mode === "margin" ? (
              <LineChart data={rows} margin={{ top: 20, right: 24, left: 4, bottom: 4 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                {/* Padding keeps the Jan / Dec labels off the axis line. */}
                <XAxis dataKey="label" tick={{ fontSize: 11 }} padding={{ left: 20, right: 20 }} />
                <YAxis tickFormatter={yTick} tick={{ fontSize: 11 }} width={48} />
                {tooltip}
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {/* Previous year's labels BELOW its points, current year's
                    ABOVE — the two lines run close, so same-side labels
                    would overprint. */}
                <Line type="monotone" dataKey={prevKey} stroke={PREV_COLOR} strokeWidth={2} dot={{ r: 3 }}>
                  <LabelList dataKey={prevKey} position="bottom" offset={8} formatter={label} style={{ ...LABEL_STYLE, fill: "#64748B" }} />
                </Line>
                <Line type="monotone" dataKey={curKey} stroke={CUR_COLOR} strokeWidth={2} dot={{ r: 3 }}>
                  <LabelList dataKey={curKey} position="top" offset={8} formatter={label} style={{ ...LABEL_STYLE, fill: CUR_COLOR, fontWeight: 600 }} />
                </Line>
              </LineChart>
            ) : (
              <BarChart data={rows} margin={{ top: 20, right: 16, left: 4, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" vertical={false} />
                <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                <YAxis tickFormatter={yTick} tick={{ fontSize: 11 }} width={56} />
                {tooltip}
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey={prevKey} fill={PREV_COLOR} radius={[2, 2, 0, 0]}>
                  <LabelList dataKey={prevKey} position="top" formatter={label} style={{ ...LABEL_STYLE, fill: "#64748B" }} />
                </Bar>
                <Bar dataKey={curKey} fill={CUR_COLOR} radius={[2, 2, 0, 0]}>
                  <LabelList dataKey={curKey} position="top" formatter={label} style={{ ...LABEL_STYLE, fill: CUR_COLOR, fontWeight: 600 }} />
                </Bar>
              </BarChart>
            )}
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
