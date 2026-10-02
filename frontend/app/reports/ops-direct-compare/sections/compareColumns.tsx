"use client"

import { fmtCount, fmtUsd, marginColor } from "../../ops-margins/format"
import type { DCCompareRow, DCSide } from "@/lib/ops-direct-compare-api"

// ---------------------------------------------------------------------------
// The 15 metric columns shared by Details by Customer, Details by Lane and the
// Customer → Lane pivot (Bruno PDF 2026-10-01 R6-R8). Order is Bruno's:
// for each metric — Panel 1, Panel 2, Diff. Panel 1 columns are light gray,
// Panel 2 light blue, Diff columns a distinct amber tint with signed colour.
// Every `id` is a backend sort key (`SORT_COLUMNS` in ops_direct_compare.py).
// ---------------------------------------------------------------------------

export type CompareGroup = "p1" | "p2" | "diff"
type Metric = "loads" | "revenue" | "profit" | "margin" | "avg_p"

export interface CompareColumn {
  id: string
  label: string
  group: CompareGroup
  metric: Metric
}

const METRICS: ReadonlyArray<{ key: Metric; label: string; diffLabel: string }> = [
  { key: "loads", label: "Loads", diffLabel: "Diff Loads" },
  { key: "revenue", label: "Revenue", diffLabel: "Diff Rev" },
  { key: "profit", label: "Profit", diffLabel: "Diff Profit" },
  { key: "margin", label: "% Margin", diffLabel: "Diff Margins" },
  { key: "avg_p", label: "AVG $P / #L", diffLabel: "Diff AVG $P / #L" },
]

export function compareColumns(p1Period: string, p2Period: string): CompareColumn[] {
  return METRICS.flatMap((m) => [
    { id: `p1_${m.key}`, label: `${m.label} ${p1Period}`, group: "p1" as const, metric: m.key },
    { id: `p2_${m.key}`, label: `${m.label} ${p2Period}`, group: "p2" as const, metric: m.key },
    { id: `diff_${m.key}`, label: m.diffLabel, group: "diff" as const, metric: m.key },
  ])
}

export const GROUP_CELL: Record<CompareGroup, string> = {
  p1: "bg-[#F3F4F6]",
  p2: "bg-[#E0F2FE]",
  diff: "bg-[#FFFBEB] font-semibold",
}

const GROUP_HEAD: Record<CompareGroup, string> = {
  p1: "bg-[#E5E7EB] text-[#374151]",
  p2: "bg-[#BAE6FD] text-[#075985]",
  diff: "bg-[#FEF3C7] text-[#92400E]",
}

function value(side: DCSide, metric: Metric): number | null {
  switch (metric) {
    case "loads":
      return side.loads
    case "revenue":
      return side.revenue
    case "profit":
      return side.profit
    case "margin":
      return side.margin_pct
    case "avg_p":
      return side.avg_p_per_l
  }
}

function fmtPlain(v: number | null, metric: Metric): string {
  if (metric === "loads") return fmtCount(v)
  if (metric === "margin") return v === null ? "—" : `${v.toFixed(2)}%`
  return fmtUsd(v)
}

function fmtSigned(v: number | null, metric: Metric): string {
  if (v === null || Number.isNaN(v)) return "—"
  const sign = v > 0 ? "+" : v < 0 ? "−" : ""
  const abs = Math.abs(v)
  // A margin difference is in percentage POINTS, not percent.
  if (metric === "margin") return `${sign}${abs.toFixed(2)} pp`
  return `${sign}${metric === "loads" ? fmtCount(abs) : fmtUsd(abs)}`
}

function diffTone(v: number | null): string {
  if (v === null || v === 0 || Number.isNaN(v)) return "text-[#6B7280]"
  return v > 0 ? "text-[#16A34A]" : "text-[#DC2626]"
}

/** The 15 metric <td>s for one compare row (or the Totals row). */
export function CompareCells({
  row,
  columns,
  cellClass = "px-2 py-1.5",
}: {
  row: DCCompareRow
  columns: CompareColumn[]
  cellClass?: string
}) {
  return (
    <>
      {columns.map((c) => {
        const v = value(row[c.group], c.metric)
        const tone =
          c.group === "diff"
            ? diffTone(v)
            : c.metric === "margin"
              ? marginColor(v)
              : "text-[#374151]"
        return (
          <td
            key={c.id}
            className={`${cellClass} whitespace-nowrap text-right tabular-nums ${GROUP_CELL[c.group]} ${tone}`}
          >
            {c.group === "diff" ? fmtSigned(v, c.metric) : fmtPlain(v, c.metric)}
          </td>
        )
      })}
    </>
  )
}

/** Toggle: first click sorts DESC, the next ASC. */
export function nextSort(current: string, id: string): string {
  return current === `${id}_desc` ? `${id}_asc` : `${id}_desc`
}

export function sortArrow(current: string, id: string): string {
  return current === `${id}_desc` ? " ↓" : current === `${id}_asc` ? " ↑" : ""
}

export function ariaSort(
  current: string,
  id: string,
): "ascending" | "descending" | "none" {
  return current === `${id}_desc` ? "descending" : current === `${id}_asc` ? "ascending" : "none"
}

/** Swatch key for the three column tints. The KPI cards above use blue for
 *  Panel 1 and violet for Panel 2; Bruno's table spec makes Panel 2 light blue,
 *  so every compare table states its own colour key. */
export function CompareLegend() {
  const item = (cls: string, text: string) => (
    <span className="inline-flex items-center gap-1">
      <span className={`inline-block h-3 w-3 rounded-sm border border-[#9CA3AF] ${cls}`} />
      {text}
    </span>
  )
  return (
    <div className="flex flex-wrap items-center gap-3 text-[10px] text-[#6B7280]">
      {item(GROUP_HEAD.p1, "Panel 1")}
      {item(GROUP_HEAD.p2, "Panel 2")}
      {item(GROUP_HEAD.diff, "Diff = Panel 1 − Panel 2")}
    </div>
  )
}

/** Sortable, group-tinted metric headers (a real <button> per column). */
export function CompareHeaderCells({
  columns,
  sort,
  onSort,
}: {
  columns: CompareColumn[]
  sort: string
  onSort: (next: string) => void
}) {
  return (
    <>
      {columns.map((c) => (
        <th
          key={c.id}
          aria-sort={ariaSort(sort, c.id)}
          className={`whitespace-nowrap px-2 py-2 text-right ${GROUP_HEAD[c.group]}`}
        >
          <button
            type="button"
            onClick={() => onSort(nextSort(sort, c.id))}
            className="uppercase tracking-wider hover:underline"
          >
            {c.label}
            {sortArrow(sort, c.id)}
          </button>
        </th>
      ))}
    </>
  )
}
