"use client"

import { useEffect, useMemo, useState } from "react"
import { Loader2, Maximize2, TrendingDown, X } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  useOppActuals,
  type OppActualsCompareMeta,
  type OppActualsRow,
  type OppActualsTotals,
  type OppFilters,
} from "@/lib/ops-portal-overview-api"
import { parseLocalDate } from "@/lib/local-date"
import AttritionPivotModal from "./AttritionPivotModal"
import {
  defaultMode,
  legOf,
  ModeCell,
  ModePills,
  sortValue,
  SortableTh,
  type ActualsCompare,
  type Metric,
  type Mode,
} from "./ActualsCells"

interface Props {
  /** Drops the All / Budget / Variance-per-Cell modes and forces Production
   *  (Bruno PDF 2026-08-20, DFW R8). All three read
   *  `daily_production_budget_report`, which holds no DFW rows. */
  hideBudget?: boolean
  /** Bruno PDF 2026-10-12 (DFW) R1: "prior_month" compares against the same
   *  days of the previous month — pills All / Actuals / Variances. */
  compare?: ActualsCompare
  filters: OppFilters
  // R9: when provided, customer-name / lane cells become clickable drill links.
  onPickCustomer?: (customer: string) => void
  onPickLane?: (lane: string) => void
}

// Single source of truth for sortable column metadata.
// `accessor` returns the numeric value used for sort comparison.
type ColumnKey =
  | "customer_name"
  | "vol" | "rev" | "prof" | "margin"
  | "otp" | "otd" | "rev_x_l" | "prof_x_l"
  | "vol_x_day" | "prof_x_day"
  | "proj_eom_vol" | "proj_eom_prof"

const COLUMNS: {
  k: ColumnKey
  label: string
  align: "left" | "center" | "right"
  numeric: boolean
  accessor: (r: OppActualsRow, mode: Mode, compare: ActualsCompare) => number | string
}[] = [
  { k: "customer_name", label: "Customer Name", align: "left",   numeric: false,
    accessor: (r) => (r.customer_name || "").toUpperCase() },
  { k: "vol", label: "Volume", align: "center", numeric: true,
    accessor: (r, m, c) => sortValue(legOf(r, "vol", c), m) },
  { k: "rev", label: "Revenue", align: "center", numeric: true,
    accessor: (r, m, c) => sortValue(legOf(r, "rev", c), m) },
  { k: "prof", label: "Profit", align: "center", numeric: true,
    accessor: (r, m, c) => sortValue(legOf(r, "prof", c), m) },
  { k: "margin", label: "Margin", align: "center", numeric: true,
    accessor: (r, m, c) => sortValue(legOf(r, "margin", c), m) },
  { k: "otp",  label: "OTP %",   align: "right", numeric: true, accessor: (r) => r.otp_pct },
  { k: "otd",  label: "OTD %",   align: "right", numeric: true, accessor: (r) => r.otd_pct },
  { k: "rev_x_l",  label: "Rev. x L",  align: "right", numeric: true, accessor: (r) => r.rev_x_l },
  { k: "prof_x_l", label: "Prof. x L", align: "right", numeric: true, accessor: (r) => r.prof_x_l },
  { k: "vol_x_day",  label: "Vol. x Day",  align: "center", numeric: true, accessor: (r) => r.vol_x_day },
  { k: "prof_x_day", label: "Prof. x Day", align: "center", numeric: true, accessor: (r) => r.prof_x_day },
  { k: "proj_eom_vol",  label: "Proj. EOM Vol.",   align: "center", numeric: true, accessor: (r) => r.proj_eom_vol },
  { k: "proj_eom_prof", label: "Proj. EOM Profit", align: "center", numeric: true, accessor: (r) => r.proj_eom_prof },
]

export function Actuals({
  filters,
  onPickCustomer,
  onPickLane,
  hideBudget = false,
  compare = "budget",
}: Props) {
  // Bruno R6 (2026-06-02): default the Actuals table to the "All" filter view.
  // ⚠ ...but "all" stacks Production/Budget/Variance in each cell, so with
  // hideBudget the only surviving mode is Production and it MUST also become
  // the default — otherwise the DFW table opens on a mode whose pill has been
  // removed and renders two empty sub-rows per cell (Bruno PDF 2026-08-20 R8).
  // Bruno PDF 2026-10-12: a previous-month comparison restores "All" on DFW.
  const [mode, setMode] = useState<Mode>(defaultMode(hideBudget, compare))
  // Bruno (PDF 2026-08-31) R7: every mode opens sorted by Profit, high → low.
  // One default covers all four pills because the `prof` accessor is already
  // mode-aware — it reads prof_budget under Budget and prof_var under Actual
  // vs Budget Variances — so switching pills re-sorts on the right column
  // without resetting a sort the user chose themselves.
  const [sortKey, setSortKey] = useState<ColumnKey>("prof")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
  // Bruno R11 (2026-06-24): expand the table into an uncapped modal.
  const [expanded, setExpanded] = useState(false)
  // Bruno (PDF 2026-08-14) R3: Attrition Performance Trends pivot, in a modal.
  const [attritionOpen, setAttritionOpen] = useState(false)

  // Esc closes the expand modal.
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [expanded])

  // Fetch with a stable backend sort; we re-sort client-side for column clicks.
  const { data, isLoading, error } = useOppActuals(filters, { sort: "revenue_desc", limit: 200 })
  const rawRows: OppActualsRow[] = useMemo(() => data?.data ?? [], [data])
  const totals = data?.meta?.totals as OppActualsTotals | undefined
  const compareWindow = compare === "prior_month"
    ? (data?.meta?.compare as OppActualsCompareMeta | undefined)
    : undefined
  // User 2026-10-12: the whole-previous-month leg exists only on an MTD window.
  // A filter change can take it away under the "full" pill — fall back to All
  // rather than render a column of zeros.
  const hasFull = Boolean(compareWindow?.full_start)
  const viewMode: Mode = mode === "full" && !hasFull ? "all" : mode

  const rows = useMemo(() => {
    const col = COLUMNS.find((c) => c.k === sortKey)
    if (!col) return rawRows
    const mult = sortDir === "asc" ? 1 : -1
    return [...rawRows].sort((a, b) => {
      const va = col.accessor(a, viewMode, compare)
      const vb = col.accessor(b, viewMode, compare)
      if (typeof va === "string" || typeof vb === "string") {
        return String(va).localeCompare(String(vb)) * mult
      }
      return ((va as number) - (vb as number)) * mult
    })
  }, [rawRows, sortKey, sortDir, viewMode, compare])

  const onSort = (k: ColumnKey) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(k)
      // First click on numeric col → desc (top-of-table = biggest); text → asc.
      const col = COLUMNS.find((c) => c.k === k)
      setSortDir(col?.numeric ? "desc" : "asc")
    }
  }

  const table = (
    <ActualsTable
      rows={rows}
      totals={totals}
      mode={viewMode}
      compare={compare}
      sortKey={sortKey}
      sortDir={sortDir}
      onSort={onSort}
      onPickCustomer={onPickCustomer}
      onPickLane={onPickLane}
    />
  )

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
        <button
          type="button"
          onClick={() => setExpanded(true)}
          title="Expand table"
          className="text-[#6B7280] hover:text-[#1B3A5C]"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
        <span className="rounded-md bg-[#1B3A5C] px-2 py-0.5 text-xs font-semibold uppercase text-white">
          Actuals
        </span>
        <ModePills mode={viewMode} setMode={setMode} hideBudget={hideBudget} compare={compare} hasFull={hasFull} />
        <CompareCaption range={compareWindow} />
        <div className="ml-auto flex items-center gap-2 text-[10px] text-[#6B7280]">
          {isLoading && <Loader2 className="h-3 w-3 animate-spin" />}
          <span>Click any column header to sort</span>
          {/* Bruno (PDF 2026-08-14) R3: the Attrition Performance Trends pivot,
              inline. Borrowed endpoint — see AttritionPivotModal. */}
          <button
            type="button"
            onClick={() => setAttritionOpen(true)}
            title="Attrition — Performance Trends"
            className="flex items-center gap-1 rounded-full border border-[#E5E7EB] bg-white px-2.5 py-1 text-[11px] font-medium text-[#374151] transition-colors hover:bg-[#F3F4F6]"
          >
            <TrendingDown className="h-3 w-3" />
            Attrition
          </button>
        </div>
      </div>

      {error ? (
        <div className="px-3 py-4 text-sm text-[#DC2626]">Failed to load Actuals</div>
      ) : (
        <div className="[contain:paint] max-h-[420px] overflow-auto">{table}</div>
      )}

      {attritionOpen && (
        <AttritionPivotModal filters={filters} onClose={() => setAttritionOpen(false)} />
      )}

      {expanded && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setExpanded(false)}
        >
          <div
            className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg bg-white shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
              <span className="rounded-md bg-[#1B3A5C] px-2 py-0.5 text-xs font-semibold uppercase text-white">
                Actuals
              </span>
              <ModePills mode={viewMode} setMode={setMode} hideBudget={hideBudget} compare={compare} hasFull={hasFull} />
              <CompareCaption range={compareWindow} />
              <button
                type="button"
                onClick={() => setExpanded(false)}
                title="Close"
                className="ml-auto text-[#6B7280] hover:text-[#1B3A5C]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="overflow-auto">{table}</div>
          </div>
        </div>
      )}
    </section>
  )
}

function ActualsTable({
  rows,
  totals,
  mode,
  compare,
  sortKey,
  sortDir,
  onSort,
  onPickCustomer,
}: {
  rows: OppActualsRow[]
  totals: OppActualsTotals | undefined
  mode: Mode
  compare: ActualsCompare
  sortKey: ColumnKey
  sortDir: "asc" | "desc"
  onSort: (k: ColumnKey) => void
  onPickCustomer?: (customer: string) => void
  onPickLane?: (lane: string) => void
}) {
  return (
    <table className="w-full text-xs">
      <thead className="sticky top-0 z-10 bg-[#F9FAFB] text-[10px] uppercase text-[#6B7280]">
        <tr className="border-b border-[#E5E7EB]">
          {COLUMNS.map((c) => (
            <SortableTh
              key={c.k}
              align={c.align}
              active={sortKey === c.k}
              dir={sortDir}
              onClick={() => onSort(c.k)}
            >
              {c.label}
            </SortableTh>
          ))}
        </tr>
        {totals && (
          <tr className="border-b border-[#E5E7EB] bg-[#EFF6FF] font-semibold text-[#1B3A5C]">
            <td className="px-2 py-1.5">TOTAL</td>
            {METRIC_CELLS.map(([m, kind]) => (
              <ModeCell key={m} mode={mode} kind={kind} leg={legOf(totals, m, compare)} />
            ))}
            <td className="px-2 py-1.5 text-right tabular-nums">{fmtPct(totals.otp_pct)}</td>
            <td className="px-2 py-1.5 text-right tabular-nums">{fmtPct(totals.otd_pct)}</td>
            <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(totals.rev_x_l)}</td>
            <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(totals.prof_x_l)}</td>
            {/* Bruno (PDF 2026-07-23) R4: TOTAL sums for the 4 projection columns. */}
            <td className="px-2 py-1.5 text-center tabular-nums">{fmtCount(totals.vol_x_day)}</td>
            <td className={`px-2 py-1.5 text-center tabular-nums ${totals.prof_x_day < 0 ? "text-[#DC2626]" : ""}`}>
              {fmtUsd(totals.prof_x_day)}
            </td>
            <td className="px-2 py-1.5 text-center tabular-nums">{fmtCount(totals.proj_eom_vol)}</td>
            <td className={`px-2 py-1.5 text-center tabular-nums ${totals.proj_eom_prof < 0 ? "text-[#DC2626]" : ""}`}>
              {fmtUsd(totals.proj_eom_prof)}
            </td>
          </tr>
        )}
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-[#9CA3AF]">
              No customers in scope
            </td>
          </tr>
        ) : rows.map((r) => (
          <tr key={r.customer_name} className="border-b border-[#F3F4F6] hover:bg-[#FAFBFC]">
            <td className="px-2 py-1.5 font-semibold text-[#1B3A5C]">
              {onPickCustomer ? (
                <button
                  type="button"
                  onClick={() => onPickCustomer(r.customer_name)}
                  className="text-left text-[#2563EB] hover:underline"
                >
                  {r.customer_name}
                </button>
              ) : (
                r.customer_name
              )}
            </td>
            {METRIC_CELLS.map(([m, kind]) => (
              <ModeCell key={m} mode={mode} kind={kind} leg={legOf(r, m, compare)} />
            ))}
            <td className="px-2 py-1.5 text-right tabular-nums">{fmtPct(r.otp_pct)}</td>
            <td className="px-2 py-1.5 text-right tabular-nums">{fmtPct(r.otd_pct)}</td>
            <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(r.rev_x_l)}</td>
            <td className={`px-2 py-1.5 text-right tabular-nums ${r.prof_x_l < 0 ? "text-[#DC2626]" : ""}`}>
              {fmtUsd(r.prof_x_l)}
            </td>
            <td className="px-2 py-1.5 text-center tabular-nums">{fmtCount(r.vol_x_day)}</td>
            <td className={`px-2 py-1.5 text-center tabular-nums ${r.prof_x_day < 0 ? "text-[#DC2626]" : ""}`}>
              {fmtUsd(r.prof_x_day)}
            </td>
            <td className="px-2 py-1.5 text-center tabular-nums">{fmtCount(r.proj_eom_vol)}</td>
            <td className={`px-2 py-1.5 text-center tabular-nums ${r.proj_eom_prof < 0 ? "text-[#DC2626]" : ""}`}>
              {fmtUsd(r.proj_eom_prof)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// The four Volume / Revenue / Profit / Margin cells, in column order.
const METRIC_CELLS: readonly [Metric, "count" | "usd" | "pct"][] = [
  ["vol", "count"],
  ["rev", "usd"],
  ["prof", "usd"],
  ["margin", "pct"],
]

/** "vs Sep 1 – Sep 12 · full: Sep 1 – Sep 30": which days each previous-month
 *  leg covered. Built with parseLocalDate — `new Date("2026-09-01")` is UTC
 *  midnight and would label the window one day early in CST (§116). */
function CompareCaption({ range }: { range?: OppActualsCompareMeta }) {
  if (!range) return null
  const fmt = (iso: string) =>
    parseLocalDate(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
  return (
    <span
      className="text-[10px] text-[#6B7280]"
      title="Previous month, same days. Variance = current − previous; % = current ÷ previous."
    >
      vs {fmt(range.start)} – {fmt(range.end)}
      {range.full_start && range.full_end && (
        <span title="Previous month, whole. 2nd line in All = current − whole previous month (negative = still missing by month-end).">
          {" · full month "}{fmt(range.full_start)} – {fmt(range.full_end)}
        </span>
      )}
    </span>
  )
}
