"use client"

import { ArrowDown, ArrowUp, ArrowUpDown, Loader2 } from "lucide-react"
import { useMemo, useState } from "react"
import {
  useAttritionPivot,
  type AttritionFilters,
  type PivotRow,
} from "@/lib/attrition-wow-api"
import { AttritionErrorBanner } from "../ErrorBanner"
import { fmtCount, fmtPct, fmtUsd } from "../format"

// Bruno round-5 (2026-05-19): renamed Top/Stable/Critical to Strong/Need
// Review/at Risk across all three views (by Team, by Customer, by Customer
// and Lane). The classification rule is unchanged — both LW & L2W ≥ ref →
// Strong, both below → at Risk, one of each → Need Review.
type StatusKind = "Strong" | "Need Review" | "at Risk" | "NA"

function computeStatus(
  lw: number | null,
  l2w: number | null,
  ref: number | null,
): StatusKind {
  if (ref === null || lw === null || l2w === null) return "NA"
  const lwBelow = lw < ref
  const l2wBelow = l2w < ref
  if (!lwBelow && !l2wBelow) return "Strong"
  if (lwBelow && l2wBelow) return "at Risk"
  return "Need Review"
}

const STATUS_ORDER: Record<StatusKind, number> = {
  "at Risk": 0,
  "Need Review": 1,
  "Strong": 2,
  "NA": 3,
}

interface Props {
  filters: AttritionFilters
  // Bruno round-3 (2026-05-07): clicking a row key in the by-customer or
  // customer_lane view applies the customer (and optionally lane) filter.
  onCustomerClick?: (customer: string) => void
  onLaneClick?: (lane: string) => void
  // "Client" under the RUAN view (page 6), "Customer" otherwise.
  entityLabel: string
  // Bruno 2026-06-30: the CEO Executive Attrition tab embeds this table with the
  // Difference column pre-sorted ascending. Defaults preserve the native
  // Attrition-WoW behaviour (Total, descending).
  defaultSortKey?: string
  defaultSortDir?: "asc" | "desc"
  // Bruno 2026-07-01 (CEO Attrition Request 1): open the Performance Trends
  // table on a specific view. Defaults to "team" (native Attrition-WoW).
  defaultDim?: Dim
}

type Metric = "loads" | "revenue" | "profit" | "margin"
type Dim = "customer" | "team" | "customer_lane"

const METRICS: { key: Metric; label: string; fmt: (v: number | null | undefined) => string }[] = [
  { key: "loads",   label: "# Loads",    fmt: fmtCount },
  { key: "revenue", label: "$ Revenue",  fmt: fmtUsd },
  { key: "profit",  label: "$ Profit",   fmt: fmtUsd },
  { key: "margin",  label: "% Margin",   fmt: fmtPct },
]

function dimLabel(key: Dim, entityLabel: string): string {
  if (key === "team") return "by Team"
  if (key === "customer") return `by ${entityLabel}`
  return `by ${entityLabel} and Lane`
}

const DIM_KEYS: Dim[] = ["team", "customer", "customer_lane"]

export function PivotsTab({
  filters,
  onCustomerClick,
  onLaneClick,
  entityLabel,
  defaultSortKey,
  defaultSortDir,
  defaultDim,
}: Props) {
  const [metric, setMetric] = useState<Metric>("loads")
  const [dim, setDim] = useState<Dim>(defaultDim ?? "team")
  const [weeks] = useState<number>(12)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-[#E5E7EB] bg-white px-4 py-3 text-xs shadow-sm">
        <div className="flex items-center gap-1">
          <span className="font-semibold uppercase tracking-wider text-[#6B7280]">
            Metric
          </span>
          <div className="ml-1 flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB]">
            {METRICS.map((m) => (
              <button
                key={m.key}
                onClick={() => setMetric(m.key)}
                className={`px-3 py-1.5 ${
                  metric === m.key
                    ? "rounded-md bg-white font-semibold text-[#1B3A5C] shadow-sm"
                    : "text-[#6B7280] hover:text-[#111827]"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <span className="font-semibold uppercase tracking-wider text-[#6B7280]">
            View
          </span>
          <div className="ml-1 flex rounded-lg border border-[#E5E7EB] bg-[#F9FAFB]">
            {DIM_KEYS.map((k) => (
              <button
                key={k}
                onClick={() => setDim(k)}
                className={`px-3 py-1.5 ${
                  dim === k
                    ? "rounded-md bg-white font-semibold text-[#1B3A5C] shadow-sm"
                    : "text-[#6B7280] hover:text-[#111827]"
                }`}
              >
                {dimLabel(k, entityLabel)}
              </button>
            ))}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-3 text-[11px] text-[#374151]">
          {/* Bruno R8 (2026-06-03): exact legend wording. */}
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-sm bg-[#DCFCE7]" />
            <span>Cell &gt;= Row 8W Avg</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-sm bg-[#FEE2E2]" />
            <span>Cell &lt; Row 8W Avg</span>
          </span>
          <span className="text-[#9CA3AF]">· current week excluded</span>
        </div>
      </div>

      <PivotPanel
        filters={filters}
        dim={dim}
        metric={metric}
        weeks={weeks}
        onCustomerClick={onCustomerClick}
        onLaneClick={onLaneClick}
        entityLabel={entityLabel}
        defaultSortKey={defaultSortKey}
        defaultSortDir={defaultSortDir}
      />
    </div>
  )
}

// Separator the backend emits between customer/client and lane for the
// customer_lane dim ("<entity> · <lane>").
const DIM_SEP = " · "

function splitDimKey(value: string): { cust: string; lane: string } {
  const idx = value.indexOf(DIM_SEP)
  if (idx < 0) return { cust: value, lane: "" }
  return { cust: value.slice(0, idx), lane: value.slice(idx + DIM_SEP.length) }
}

function PivotPanel({
  filters,
  dim,
  metric,
  weeks,
  onCustomerClick,
  onLaneClick,
  entityLabel,
  defaultSortKey,
  defaultSortDir,
}: {
  filters: AttritionFilters
  dim: Dim
  metric: Metric
  weeks: number
  onCustomerClick?: (customer: string) => void
  onLaneClick?: (lane: string) => void
  entityLabel: string
  defaultSortKey?: string
  defaultSortDir?: "asc" | "desc"
}) {
  const isLane = dim === "customer_lane"
  const { data: res, isLoading, error } = useAttritionPivot(
    filters,
    dim,
    metric,
    weeks,
  )
  const rows = res?.data ?? []
  const fmt = METRICS.find((m) => m.key === metric)!.fmt

  // Bruno round-4 (2026-05-12): every column sortable. Sort state is column
  // key = "status" | "dim_key" | "ref" | `wk_${idx}` and a direction.
  type SortDir = "asc" | "desc"
  const [sortKey, setSortKey] = useState<string>(defaultSortKey ?? "total")
  const [sortDir, setSortDir] = useState<SortDir>(defaultSortDir ?? "desc")
  const toggleSort = (k: string) => {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    else {
      setSortKey(k)
      setSortDir("desc")
    }
  }

  // Build wide pivot: weeks (cols, latest first) × dim_keys (rows)
  const { weeksList, pivot, totals } = useMemo(() => {
    const weekSet = new Set<string>()
    const byKey = new Map<
      string,
      {
        // Bruno Attrition R (2026-07-13): the Team value for this dim_key (all
        // its long-form rows share it — read off the first seen).
        team: string | null
        values: Map<string, number | null>
        // Bruno round-5 (2026-05-19): track raw rev/prof per cell when the
        // current metric is "margin" so the Totals row can compute the
        // weighted-avg margin (sum profit / sum revenue) per column.
        revenue: Map<string, number>
        profit: Map<string, number>
      }
    >()
    for (const r of rows as PivotRow[]) {
      weekSet.add(r.week_start)
      let bucket = byKey.get(r.dim_key)
      if (!bucket) {
        bucket = {
          team: r.team ?? null,
          values: new Map(),
          revenue: new Map(),
          profit: new Map(),
        }
        byKey.set(r.dim_key, bucket)
      }
      bucket.values.set(r.week_start, r.value)
      if (metric === "margin") {
        bucket.revenue.set(r.week_start, r.revenue ?? 0)
        bucket.profit.set(r.week_start, r.profit ?? 0)
      }
    }
    const weeksList = Array.from(weekSet).sort().reverse() // latest first
    const pivotEntries = Array.from(byKey.entries()).map(([k, b]) => {
      const values = weeksList.map((w) => b.values.get(w) ?? null)
      const revenue = weeksList.map((w) => b.revenue.get(w) ?? 0)
      const profit = weeksList.map((w) => b.profit.get(w) ?? 0)
      // 8-week ref (Bruno Attrition R, PDF 2026-07-13): mean of the 8 completed
      // weeks BEFORE last week — indices 1..8 = weeks −2..−9 (weeksList is
      // latest-first, so index 0 is last week which is excluded). A missing /
      // "—" week counts as 0 (fixed divisor), NOT dropped. This makes the
      // Totals "8-week avg" reconcile exactly with the chart's "8W Avg" line
      // (backend _l8w_window, weeks −2..−9, 0-filled) and matches the Overview
      // cards / reactive tables / cell shading, which all exclude last week.
      const ref = (() => {
        const slice = values.slice(1, 9)
        if (slice.length === 0) return null
        return slice.reduce<number>((a, b) => a + (b ?? 0), 0) / slice.length
      })()
      const total = values.reduce<number>((a, b) => a + (b ?? 0), 0)
      const status = computeStatus(values[0] ?? null, values[1] ?? null, ref)
      // Bruno (2026-06-08): "Difference" column = latest week − 8-week avg.
      // (The PDF wording says "subtract latest from avg" but the mock proves
      // latest − avg: TM1 avg 139, Jun-1 118 → −21.) Null when either side is
      // missing.
      const latest = values[0]
      const diff =
        latest === null || latest === undefined || ref === null
          ? null
          : latest - ref
      // Bruno Attrition R (PDF 2026-07-15): "Difference LW – L2W" = latest week
      // − AVG L2W, where AVG L2W is the mean of the 2 completed weeks BEFORE
      // last week — indices 1..2 (weeks −2..−3, 0-filled, fixed divisor 2),
      // mirroring the L8W column exactly with a 2-week window. Placed to the
      // right of "Difference LW – L8W" across all views and metrics.
      const l2wRef = (() => {
        const slice = values.slice(1, 3)
        if (slice.length === 0) return null
        return slice.reduce<number>((a, b) => a + (b ?? 0), 0) / slice.length
      })()
      const diff2w =
        latest === null || latest === undefined || l2wRef === null
          ? null
          : latest - l2wRef
      // Bruno (2026-05-25 page 5): expose customer/client + lane separately so
      // the customer_lane view can render — and sort — two columns.
      const { cust, lane } = splitDimKey(k)
      return { dim_key: k, team: b.team, cust, lane, values, revenue, profit, ref, l2wRef, diff, diff2w, total, status }
    })
    const strCompare = (av: string, bv: string) => {
      const a = av.toLowerCase()
      const b = bv.toLowerCase()
      if (a < b) return sortDir === "asc" ? -1 : 1
      if (a > b) return sortDir === "asc" ? 1 : -1
      return 0
    }
    pivotEntries.sort((a, b) => {
      if (sortKey === "status") {
        const av = STATUS_ORDER[a.status]
        const bv = STATUS_ORDER[b.status]
        return sortDir === "asc" ? av - bv : bv - av
      }
      if (sortKey === "dim_key") return strCompare(a.dim_key, b.dim_key)
      if (sortKey === "team") return strCompare(a.team ?? "", b.team ?? "")
      if (sortKey === "cust") return strCompare(a.cust, b.cust)
      if (sortKey === "lane") return strCompare(a.lane, b.lane)
      if (sortKey === "ref") {
        const av = a.ref
        const bv = b.ref
        if (av === null) return 1
        if (bv === null) return -1
        return sortDir === "asc" ? av - bv : bv - av
      }
      if (sortKey === "diff") {
        const av = a.diff
        const bv = b.diff
        if (av === null) return 1
        if (bv === null) return -1
        return sortDir === "asc" ? av - bv : bv - av
      }
      if (sortKey === "diff2w") {
        const av = a.diff2w
        const bv = b.diff2w
        if (av === null) return 1
        if (bv === null) return -1
        return sortDir === "asc" ? av - bv : bv - av
      }
      if (sortKey.startsWith("wk_")) {
        const idx = Number(sortKey.slice(3))
        const av = a.values[idx]
        const bv = b.values[idx]
        if (av === null || av === undefined) return 1
        if (bv === null || bv === undefined) return -1
        return sortDir === "asc" ? av - bv : bv - av
      }
      // default: total desc (preserves prior behavior)
      return (b.total ?? 0) - (a.total ?? 0)
    })

    // Bruno round-5 (2026-05-19): Totals row across every column. For
    // loads/revenue/profit it's a straight column sum; for margin it's the
    // weighted avg (Σ profit / Σ revenue). The 8-week avg total mirrors the
    // per-row formula — mean of the 8 most-recent non-null per-week totals
    // (or the weighted avg of the 8 most-recent weeks for margin).
    const perWeek: (number | null)[] = weeksList.map((_, i) => {
      if (metric === "margin") {
        let rev = 0
        let prof = 0
        for (const row of pivotEntries) {
          rev += row.revenue[i] ?? 0
          prof += row.profit[i] ?? 0
        }
        return rev > 0 ? prof / rev : null
      }
      let any = false
      let s = 0
      for (const row of pivotEntries) {
        const v = row.values[i]
        if (v !== null && v !== undefined) {
          any = true
          s += v
        }
      }
      return any ? s : null
    })
    // Bruno R8 (2026-06-03): for additive metrics the Totals reference is the
    // SUM of the 8-week avg column (Σ per-row refs) — the totals 8-week-avg
    // cell displays it and the weekly totals shade green when >= it. Margin
    // isn't additive, so it keeps the weighted-avg basis (Σ profit / Σ rev
    // over the 8 most recent weeks).
    const totalRef: number | null = (() => {
      if (pivotEntries.length === 0) return null
      if (metric === "margin") {
        // Bruno Attrition R (2026-07-13): weighted-avg margin over the SAME 8
        // weeks the chart uses — indices 1..8 (weeks −2..−9, last week
        // excluded), summing every week (0-filled, no zero-revenue skip) so it
        // matches the chart's "8W Avg" (Σprofit / Σrevenue over _l8w_window).
        let rev = 0
        let prof = 0
        for (let i = 1; i < weeksList.length && i <= 8; i += 1) {
          for (const row of pivotEntries) {
            rev += row.revenue[i] ?? 0
            prof += row.profit[i] ?? 0
          }
        }
        return rev > 0 ? prof / rev : null
      }
      const refs = pivotEntries
        .map((row) => row.ref)
        .filter((v): v is number => v !== null)
      if (refs.length === 0) return null
      return refs.reduce((a, b) => a + b, 0)
    })()

    // Bruno (2026-06-08): Totals "Difference" = latest week total − 8-week-avg
    // total. The Totals Difference cell shades green when >= 0, red below.
    const totalLatest = perWeek[0]
    const totalDiff: number | null =
      totalLatest === null || totalLatest === undefined || totalRef === null
        ? null
        : totalLatest - totalRef

    // Bruno Attrition R (PDF 2026-07-15): Totals "Difference LW – L2W" — same
    // basis as the L8W totals but over the 2 weeks before last week. Additive
    // metrics sum the per-row L2W refs; margin is the weighted avg (Σ profit /
    // Σ revenue) over indices 1..2.
    const totalRef2w: number | null = (() => {
      if (pivotEntries.length === 0) return null
      if (metric === "margin") {
        let rev = 0
        let prof = 0
        for (let i = 1; i < weeksList.length && i <= 2; i += 1) {
          for (const row of pivotEntries) {
            rev += row.revenue[i] ?? 0
            prof += row.profit[i] ?? 0
          }
        }
        return rev > 0 ? prof / rev : null
      }
      const refs = pivotEntries
        .map((row) => row.l2wRef)
        .filter((v): v is number => v !== null)
      if (refs.length === 0) return null
      return refs.reduce((a, b) => a + b, 0)
    })()
    const totalDiff2w: number | null =
      totalLatest === null || totalLatest === undefined || totalRef2w === null
        ? null
        : totalLatest - totalRef2w

    return {
      weeksList,
      pivot: pivotEntries,
      totals: { perWeek, ref: totalRef, ref2w: totalRef2w, diff: totalDiff, diff2w: totalDiff2w },
    }
  }, [rows, sortKey, sortDir, metric])

  if (isLoading && pivot.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
      </div>
    )
  }

  const headerLabel = dim === "team" ? "Team" : entityLabel
  // Bruno Attrition R (2026-07-13): a Team column sits after Status in the
  // "by Customer" and "by Customer and Lane" views (not the "by Team" view,
  // where the dim_key already IS the team). It's sticky at left-[100px]; the
  // entity column then shifts right to left-[180px].
  const showTeam = dim !== "team"
  const entityLeft = showTeam ? "left-[180px]" : "left-[100px]"
  // Leading non-week columns: Status + (Team) + (Lane adds an extra entity/lane
  // split) + dim column(s) + 8-week avg. Used for the empty-state colSpan.
  const leadingCols = (isLane ? 4 : 3) + (showTeam ? 1 : 0)

  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm">
      <AttritionErrorBanner errors={[error]} label="Pivot" />
      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead className="bg-[#F9FAFB] text-[10px] uppercase tracking-wider text-[#6B7280]">
            <tr>
              <SortTh
                k="status"
                sortKey={sortKey}
                sortDir={sortDir}
                onToggle={toggleSort}
                align="left"
                className="sticky left-0 z-10 bg-[#F9FAFB]"
              >
                Status
              </SortTh>
              {showTeam && (
                <SortTh
                  k="team"
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onToggle={toggleSort}
                  align="left"
                  className="sticky left-[100px] z-10 bg-[#F9FAFB]"
                >
                  Team
                </SortTh>
              )}
              {isLane ? (
                <>
                  <SortTh
                    k="cust"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onToggle={toggleSort}
                    align="left"
                    className={`sticky ${entityLeft} z-10 bg-[#F9FAFB]`}
                  >
                    {entityLabel}
                  </SortTh>
                  <SortTh
                    k="lane"
                    sortKey={sortKey}
                    sortDir={sortDir}
                    onToggle={toggleSort}
                    align="left"
                    className="bg-[#F9FAFB]"
                  >
                    Lane
                  </SortTh>
                </>
              ) : (
                <SortTh
                  k="dim_key"
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onToggle={toggleSort}
                  align="left"
                  className={`sticky ${entityLeft} z-10 bg-[#F9FAFB]`}
                >
                  {headerLabel}
                </SortTh>
              )}
              <SortTh
                k="ref"
                sortKey={sortKey}
                sortDir={sortDir}
                onToggle={toggleSort}
                className="bg-[#F9FAFB] text-[#1B3A5C]"
              >
                8-week avg
              </SortTh>
              {/* Bruno (2026-06-08): Difference = latest week − 8-week avg.
                  Bruno Attrition R (2026-07-13): relabelled "Difference LW – L8W". */}
              <SortTh
                k="diff"
                sortKey={sortKey}
                sortDir={sortDir}
                onToggle={toggleSort}
                className="bg-[#F9FAFB] text-[#1B3A5C]"
              >
                Difference LW – L8W
              </SortTh>
              {/* Bruno Attrition R (PDF 2026-07-15): Difference LW – L2W = latest
                  week − AVG of the 2 weeks before last week. Sits immediately
                  right of Difference LW – L8W. */}
              <SortTh
                k="diff2w"
                sortKey={sortKey}
                sortDir={sortDir}
                onToggle={toggleSort}
                className="bg-[#F9FAFB] text-[#1B3A5C]"
              >
                Difference LW – L2W
              </SortTh>
              {weeksList.map((w, i) => (
                <SortTh
                  key={w}
                  k={`wk_${i}`}
                  sortKey={sortKey}
                  sortDir={sortDir}
                  onToggle={toggleSort}
                >
                  {fmtMonDay(w)}
                </SortTh>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F3F4F6]">
            {pivot.map((row) => (
              <tr key={row.dim_key} className="hover:bg-[#FAFAFA]">
                <td className="sticky left-0 z-10 bg-white px-3 py-1.5">
                  <StatusBadge status={row.status} />
                </td>
                {showTeam && (
                  <td className="sticky left-[100px] z-10 bg-white px-3 py-1.5 text-[#374151]">
                    {row.team ?? "—"}
                  </td>
                )}
                {isLane ? (
                  <>
                    <td
                      className={`sticky ${entityLeft} z-10 max-w-[240px] truncate bg-white px-3 py-1.5 text-[#111827]`}
                      title={row.cust}
                    >
                      {onCustomerClick ? (
                        <button
                          type="button"
                          onClick={() => onCustomerClick(row.cust)}
                          className="text-left text-[#1D4ED8] hover:underline"
                        >
                          {row.cust}
                        </button>
                      ) : (
                        <span>{row.cust}</span>
                      )}
                    </td>
                    <td
                      className="max-w-[240px] truncate bg-white px-3 py-1.5 font-mono text-[#374151]"
                      title={row.lane}
                    >
                      {onLaneClick && row.lane ? (
                        <button
                          type="button"
                          onClick={() => onLaneClick(row.lane)}
                          className="text-left text-[#1D4ED8] hover:underline"
                        >
                          {row.lane}
                        </button>
                      ) : (
                        <span>{row.lane || "—"}</span>
                      )}
                    </td>
                  </>
                ) : (
                  <td
                    className={`sticky ${entityLeft} z-10 max-w-[320px] truncate bg-white px-3 py-1.5 text-[#111827]`}
                    title={row.dim_key}
                  >
                    <DimKeyCell
                      dim={dim}
                      value={row.dim_key}
                      onCustomerClick={onCustomerClick}
                      onLaneClick={onLaneClick}
                    />
                  </td>
                )}
                <td className="bg-white px-3 py-1.5 text-right font-mono font-semibold text-[#1B3A5C]">
                  {row.ref === null ? "—" : fmt(row.ref)}
                </td>
                {/* Bruno (2026-06-08): per-row Difference is uncolored; only the
                    Totals Difference cell is shaded (see mock). */}
                <td className="bg-white px-3 py-1.5 text-right font-mono text-[#374151]">
                  {row.diff === null ? "—" : fmt(row.diff)}
                </td>
                {/* Bruno Attrition R (PDF 2026-07-15): per-row Difference LW – L2W,
                    uncolored like the L8W difference. */}
                <td className="bg-white px-3 py-1.5 text-right font-mono text-[#374151]">
                  {row.diff2w === null ? "—" : fmt(row.diff2w)}
                </td>
                {row.values.map((v, i) => (
                  <td
                    key={i}
                    className={`px-3 py-1.5 text-right font-mono ${cellShade(v, row.ref)}`}
                  >
                    {v === null ? "—" : fmt(v)}
                  </td>
                ))}
              </tr>
            ))}
            {pivot.length === 0 && (
              <tr>
                <td colSpan={weeksList.length + leadingCols + 2} className="py-8 text-center text-xs text-[#9CA3AF]">
                  No data in scope.
                </td>
              </tr>
            )}
            {/* Bruno round-5 (2026-05-19): Totals row across every column.
                Loads/revenue/profit sum naturally; margin is weighted (Σ profit
                / Σ revenue) so the row reflects the same math as the Overview
                KPI table. */}
            {pivot.length > 0 && (
              <tr className="border-t-2 border-[#1B3A5C] bg-[#F9FAFB] font-semibold">
                <td className="sticky left-0 z-10 bg-[#F9FAFB] px-3 py-2 text-[10px] uppercase tracking-wider text-[#1B3A5C]">
                  Totals
                </td>
                {showTeam && (
                  <td className="sticky left-[100px] z-10 bg-[#F9FAFB] px-3 py-2" />
                )}
                <td className={`sticky ${entityLeft} z-10 bg-[#F9FAFB] px-3 py-2 text-[#1B3A5C]`}>
                  {metric === "margin" ? "Weighted avg" : "All rows"}
                </td>
                {isLane && <td className="bg-[#F9FAFB] px-3 py-2" />}
                <td className="bg-[#F9FAFB] px-3 py-2 text-right font-mono text-[#1B3A5C]">
                  {totals.ref === null ? "—" : fmt(totals.ref)}
                </td>
                {/* Bruno (2026-06-08): Totals Difference shades green when
                    >= 0, red below (cellShade against a 0 reference). */}
                <td
                  className={`bg-[#F9FAFB] px-3 py-2 text-right font-mono ${cellShade(totals.diff, 0)}`}
                >
                  {totals.diff === null ? "—" : fmt(totals.diff)}
                </td>
                {/* Bruno Attrition R (PDF 2026-07-15): Totals Difference LW – L2W,
                    shaded green when >= 0, red below (like the L8W totals diff). */}
                <td
                  className={`bg-[#F9FAFB] px-3 py-2 text-right font-mono ${cellShade(totals.diff2w, 0)}`}
                >
                  {totals.diff2w === null ? "—" : fmt(totals.diff2w)}
                </td>
                {totals.perWeek.map((v, i) => (
                  <td
                    key={i}
                    className={`bg-[#F9FAFB] px-3 py-2 text-right font-mono ${cellShade(v, totals.ref)}`}
                  >
                    {v === null ? "—" : fmt(v)}
                  </td>
                ))}
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function SortTh({
  k,
  sortKey,
  sortDir,
  onToggle,
  align = "right",
  className = "",
  children,
}: {
  k: string
  sortKey: string
  sortDir: "asc" | "desc"
  onToggle: (k: string) => void
  align?: "left" | "right"
  className?: string
  children: React.ReactNode
}) {
  const active = sortKey === k
  const Icon = !active ? ArrowUpDown : sortDir === "asc" ? ArrowUp : ArrowDown
  return (
    <th
      className={`px-3 py-2 ${align === "left" ? "text-left" : "text-right"} ${className}`}
    >
      <button
        onClick={() => onToggle(k)}
        className={`inline-flex items-center gap-1 hover:underline ${active ? "font-bold" : ""}`}
      >
        {align === "right" ? (
          <>
            <Icon className={`h-3 w-3 ${active ? "opacity-100" : "opacity-40"}`} />
            <span>{children}</span>
          </>
        ) : (
          <>
            <span>{children}</span>
            <Icon className={`h-3 w-3 ${active ? "opacity-100" : "opacity-40"}`} />
          </>
        )}
      </button>
    </th>
  )
}

function StatusBadge({ status }: { status: StatusKind }) {
  if (status === "NA") return <span className="text-[#9CA3AF]">—</span>
  const cls =
    status === "Strong"
      ? "bg-[#DCFCE7] text-[#15803D]"
      : status === "Need Review"
        ? "bg-[#FEF3C7] text-[#92400E]"
        : "bg-[#FEE2E2] text-[#991B1B]"
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${cls}`}>
      {status}
    </span>
  )
}

function DimKeyCell({
  dim,
  value,
  onCustomerClick,
  onLaneClick,
}: {
  dim: Dim
  value: string
  onCustomerClick?: (customer: string) => void
  onLaneClick?: (lane: string) => void
}) {
  if (dim === "team" || !onCustomerClick) {
    return <span>{value}</span>
  }
  if (dim === "customer") {
    return (
      <button
        type="button"
        onClick={() => onCustomerClick(value)}
        className="text-left text-[#1D4ED8] hover:underline"
      >
        {value}
      </button>
    )
  }
  // customer_lane — split on the " · " separator the backend emits.
  const sep = " · "
  const idx = value.indexOf(sep)
  if (idx < 0) {
    return <span>{value}</span>
  }
  const cust = value.slice(0, idx)
  const lane = value.slice(idx + sep.length)
  return (
    <span className="inline-flex items-center gap-1">
      <button
        type="button"
        onClick={() => onCustomerClick(cust)}
        className="text-[#1D4ED8] hover:underline"
      >
        {cust}
      </button>
      <span className="text-[#9CA3AF]">·</span>
      {onLaneClick ? (
        <button
          type="button"
          onClick={() => onLaneClick(lane)}
          className="font-mono text-[#1D4ED8] hover:underline"
        >
          {lane}
        </button>
      ) : (
        <span className="font-mono text-[#374151]">{lane}</span>
      )}
    </span>
  )
}

function cellShade(v: number | null, ref: number | null): string {
  if (v === null || ref === null) return "text-[#9CA3AF]"
  // Bruno R8 (2026-06-03): a cell EQUAL to its reference is green too —
  // green when >= the row 8w avg (or the totals ref), red strictly below.
  if (v >= ref) return "bg-[#DCFCE7] text-[#15803D]"
  return "bg-[#FEE2E2] text-[#DC2626]"
}

function fmtMonDay(iso: string): string {
  try {
    const d = new Date(iso + "T00:00:00")
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
  } catch {
    return iso
  }
}

