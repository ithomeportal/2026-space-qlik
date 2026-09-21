"use client"

import {
  DASH,
  fmtCount,
  fmtPct,
  fmtRange,
  fmtUsdShort,
  useSpotsBreakdown,
  type SpotsBreakdownRow,
  type SpotsDim,
  type SpotsFilters,
  type SpotsSort,
} from "@/lib/production-spots-trends-api"
import { DeltaChip, EmptyBlock, ErrorBlock, Footnote, LoadingBlock, Panel, TD, TH } from "./Ui"

/** One row per dimension value.
 *
 *  Sorting is SERVER-side against a whitelist, so sort and the row cap live in
 *  the same layer — a client sort over a server LIMIT reorders only the rows
 *  that happened to be sent while the header claims otherwise (§108). An
 *  unrecognised token is a 400, never a quiet fall back to the default.
 *
 *  Totals are a server-side aggregate over the FULL universe, not a reduce of
 *  what is on screen (§44), and the ratio cells in the totals row are
 *  Σnumerator ÷ Σdenominator — never the mean of the per-row ratios.
 */

type Col = {
  key: string
  label: string
  /** the sort token, when the column is sortable */
  sort?: string
  fmt: (r: SpotsBreakdownRow) => string
  totals?: (t: SpotsBreakdownRow) => string
  title?: string
  align?: "left" | "right"
}

const COLS: Col[] = [
  {
    key: "label",
    label: "Name",
    sort: "label",
    fmt: (r) => r.label,
    align: "left",
  },
  { key: "presented", label: "Presented", sort: "presented", fmt: (r) => fmtCount(r.presented) },
  { key: "quoted", label: "Quoted", sort: "quoted", fmt: (r) => fmtCount(r.quoted) },
  {
    key: "quote_rate",
    label: "Quote %",
    sort: "quote_rate",
    fmt: (r) => fmtPct(r.quote_rate),
    title: "Quoted ÷ Presented — how much of what arrived we actually priced.",
  },
  {
    key: "skipped",
    label: "Skipped",
    sort: "skipped",
    fmt: (r) => fmtCount(r.skipped),
    title: "Presented but never priced. The reason is not available in this source.",
  },
  { key: "won", label: "Won", sort: "won", fmt: (r) => fmtCount(r.won) },
  {
    key: "win_rate",
    label: "Win %",
    sort: "win_rate",
    fmt: (r) => fmtPct(r.win_rate),
    title:
      "Won ÷ decided quotes. Suppressed below the minimum sample — one award out of one quote is not a 100% win rate.",
  },
  {
    key: "no_reply",
    label: "No reply",
    sort: "no_reply",
    fmt: (r) => fmtCount(r.no_reply),
    title: "Quotes the customer never answered — aged off after 30 days.",
  },
  {
    key: "no_reply_rate",
    label: "No reply %",
    fmt: (r) => fmtPct(r.no_reply_rate),
  },
  {
    key: "awarded_revenue",
    label: "Awarded rev.",
    sort: "awarded_revenue",
    fmt: (r) => fmtUsdShort(r.awarded_revenue),
  },
  {
    key: "awarded_margin",
    label: "Margin",
    sort: "awarded_margin",
    fmt: (r) => fmtPct(r.awarded_margin),
    title:
      "(price − accessorials − buy rate) ÷ price on won rows where both legs are known.",
  },
  {
    key: "delta_presented",
    label: "Δ Presented",
    fmt: () => "",
    title: "Change against the immediately preceding window of the same length.",
  },
]

/** Columns rendered before the first numeric one — what the Totals row spans.
 *  Derived, never typed: a column inserted later must not silently shift it. */
const LABEL_SPAN = COLS.findIndex((c) => c.align !== "left")

const DIM_LABEL: Record<SpotsDim, string> = {
  channel: "Channel",
  customer: "Customer",
  actor: "Person / bot",
  equipment: "Equipment",
  division: "Division",
}

function Th({
  col,
  sort,
  onSort,
}: {
  col: Col
  sort: SpotsSort
  onSort: (s: SpotsSort) => void
}) {
  const [activeKey, activeDir] = (() => {
    const i = sort.lastIndexOf("_")
    return [sort.slice(0, i), sort.slice(i + 1)]
  })()
  const active = col.sort === activeKey
  const arrow = active ? (activeDir === "asc" ? "▲" : "▼") : "↕"
  const align = col.align === "left" ? "text-left" : "text-right"

  if (!col.sort) {
    return (
      <th className={`${TH} ${align} text-[#374151]`} title={col.title}>
        {col.label}
      </th>
    )
  }
  const next = (
    active && activeDir === "desc" ? `${col.sort}_asc` : `${col.sort}_desc`
  ) as SpotsSort
  return (
    <th className={`${TH} ${align}`} title={col.title}>
      <button
        type="button"
        onClick={() => onSort(next)}
        className={`flex w-full items-center gap-1 ${
          col.align === "left" ? "justify-start" : "justify-end"
        } hover:text-[#111827] ${active ? "text-[#1B3A5C]" : "text-[#374151]"}`}
      >
        <span>{col.label}</span>
        <span className="text-[9px] leading-none text-[#9CA3AF]">{arrow}</span>
      </button>
    </th>
  )
}

export function BreakdownTable({
  filters,
  dim,
  sort,
  onSort,
  note,
}: {
  filters: SpotsFilters
  dim: SpotsDim
  sort: SpotsSort
  onSort: (s: SpotsSort) => void
  note?: React.ReactNode
}) {
  const { data, isLoading, error } = useSpotsBreakdown(filters, dim, sort)
  const d = data?.data

  if (error) return <ErrorBlock what={`the ${DIM_LABEL[dim]} table`} error={error} />

  return (
    <Panel
      title={`By ${DIM_LABEL[dim].toLowerCase()}`}
      subtitle={
        d ? `${d.rows.length} rows · Δ vs ${fmtRange(d.previous_window)}` : undefined
      }
    >
      {isLoading && !d ? (
        <LoadingBlock h={220} />
      ) : !d || d.rows.length === 0 ? (
        <EmptyBlock h={220} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-0 text-xs">
            <thead className="sticky top-0 z-10 bg-[#F3F4F6] text-[#374151]">
              <tr>
                {COLS.map((c) => (
                  <Th key={c.key} col={c} sort={sort} onSort={onSort} />
                ))}
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r, i) => (
                <tr key={r.label} className={i % 2 ? "bg-[#FAFAFA]" : "bg-white"}>
                  {COLS.map((c) =>
                    c.key === "delta_presented" ? (
                      <td key={c.key} className={TD}>
                        <DeltaChip delta={r.delta_presented} />
                      </td>
                    ) : (
                      <td
                        key={c.key}
                        className={
                          c.align === "left"
                            ? "whitespace-nowrap px-2 py-1 text-left"
                            : TD
                        }
                      >
                        {c.fmt(r)}
                      </td>
                    )
                  )}
                </tr>
              ))}
            </tbody>
            <tfoot className="sticky bottom-0">
              <tr className="bg-[#EEF2FF] font-semibold text-[#1B3A5C]">
                <td className="px-2 py-1 text-left" colSpan={LABEL_SPAN}>
                  Total
                </td>
                {COLS.slice(LABEL_SPAN).map((c) => (
                  <td key={c.key} className={TD}>
                    {c.key === "delta_presented"
                      ? DASH
                      : c.fmt(d.totals as SpotsBreakdownRow)}
                  </td>
                ))}
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      <Footnote>
        Totals are aggregated over the whole window on the server, not summed from
        the rows on screen, and every percentage in the Total row is recomputed from
        its own components rather than averaged. Win % is left blank below{" "}
        {d?.min_decided_for_rate ?? 10} decided quotes, and blanks sort last in both
        directions.
        {note ? <> {note}</> : null}
      </Footnote>
    </Panel>
  )
}
