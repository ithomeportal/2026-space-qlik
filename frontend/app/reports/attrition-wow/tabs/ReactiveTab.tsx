"use client"

import { Loader2 } from "lucide-react"
import { useMemo, useState } from "react"
import {
  useAttritionLaneSummary,
  useAttritionReactive,
  type AttritionFilters,
  type LaneSummaryRow,
  type ReactiveRow,
} from "@/lib/attrition-wow-api"
import { SortableTh, useSortable } from "../../ceo-executive/sortable"
import { AttritionErrorBanner } from "../ErrorBanner"
import {
  fmtCount,
  fmtPct,
  fmtSignedPct,
  fmtTimestamp,
  fmtUsd,
  varianceBandClass,
} from "../format"

interface Props {
  filters: AttritionFilters
  // Bruno round-3 (2026-05-07): clicking a customer cell applies the filter
  // bar's Customer dropdown — props bubble up to page.tsx so the URL stays
  // the source of truth for filter state.
  onCustomerClick?: (customer: string) => void
  // "Client" under the RUAN view (page 6), "Customer" otherwise.
  entityLabel: string
}

type Bucket = ReactiveRow["bucket"]

// Bruno (2026-05-25 pages 3-4): the Spot buckets render a lane-grained,
// Spot-only table (Customer, Lane, Loads, Rev, Profit, Margin, Last Load,
// Days Since) sourced from /lane-summary instead of the variance schema.
const SPOT_BUCKETS: ReadonlySet<Bucket> = new Set<Bucket>([
  "spot_recent",
  "spot_stale",
  "gt_1y",
])
const SPOT_CONTRACT = "SPOT"

const BUCKET_LABELS: Record<Bucket, { title: string; subtitle: string; days: string }> = {
  lw: {
    title: "Summary — Last Week (1–7 days)",
    subtitle: "Active in the last completed Mon-Sun week",
    days: "1–7",
  },
  l2_4w: {
    // Bruno round-5 (2026-05-19): elevated to the primary attrition headline.
    title: "CUSTOMER ATTRITION 2-4 weeks (8-28 days)",
    subtitle: "Last loaded 8–28 days ago",
    days: "8–28",
  },
  l5_9w: {
    title: "Summary — 5 to 9 Weeks (29–63 days)",
    subtitle: "Last loaded 29–63 days ago",
    days: "29–63",
  },
  spot_recent: {
    title: "Summary — Recent Spot (64–248 days)",
    subtitle: "Last loaded 64–248 days ago (spot or contract)",
    days: "64–248",
  },
  spot_stale: {
    title: "Summary — Stale Spot (249–365 days)",
    subtitle: "Last loaded 249–365 days ago",
    days: "249–365",
  },
  gt_1y: {
    title: "Summary — More than 1 Year",
    subtitle: "Last loaded > 365 days ago",
    days: "365+",
  },
  no_load: {
    title: "Summary — No Loads in Range",
    subtitle: "No loads in the last 9 weeks",
    days: "—",
  },
}

// Bruno's order (2026-04-27): show "2 to 4 Weeks" before "Last Week"
// so the medium-attrition bucket is the entry point.
const BUCKET_ORDER: Bucket[] = [
  "l2_4w",
  "lw",
  "l5_9w",
  "spot_recent",
  "spot_stale",
  "gt_1y",
]

export function ReactiveTab({ filters, onCustomerClick, entityLabel }: Props) {
  const { data: res, isLoading, error } = useAttritionReactive(filters)
  const rows = res?.data ?? []

  // Spot buckets come from /lane-summary (lane-grained, Spot only).
  const { data: laneRes, error: laneError } = useAttritionLaneSummary(filters)
  const laneRows = useMemo(
    () =>
      (laneRes?.data ?? []).filter(
        (r) => r.contract_type === SPOT_CONTRACT && SPOT_BUCKETS.has(r.bucket),
      ),
    [laneRes],
  )

  // Counts per bucket so empty sections collapse cleanly. Variance buckets
  // count customers (from /reactive-summary); Spot buckets count customer×lane
  // rows (from /lane-summary).
  const counts = useMemo(() => {
    const c: Record<Bucket, number> = {
      lw: 0,
      l2_4w: 0,
      l5_9w: 0,
      spot_recent: 0,
      spot_stale: 0,
      gt_1y: 0,
      no_load: 0,
    }
    for (const r of rows) if (!SPOT_BUCKETS.has(r.bucket)) c[r.bucket] += 1
    for (const r of laneRows) c[r.bucket] += 1
    return c
  }, [rows, laneRows])

  const [openBuckets, setOpenBuckets] = useState<Set<Bucket>>(
    () => new Set<Bucket>(["l2_4w", "lw"]),
  )
  const toggle = (b: Bucket) => {
    const next = new Set(openBuckets)
    if (next.has(b)) next.delete(b)
    else next.add(b)
    setOpenBuckets(next)
  }

  if (isLoading && rows.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <AttritionErrorBanner
        errors={[error, laneError]}
        label="Reactive Customers"
      />

      {BUCKET_ORDER.map((b) => {
        const meta = BUCKET_LABELS[b]
        const isSpot = SPOT_BUCKETS.has(b)
        const total = counts[b]
        const open = openBuckets.has(b)
        const countNoun = isSpot ? "Lanes" : `${entityLabel}s`
        return (
          <div
            key={b}
            className="rounded-xl border border-[#E5E7EB] bg-white shadow-sm"
          >
            <button
              onClick={() => toggle(b)}
              className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-[#F9FAFB]"
            >
              <div>
                <div className="text-sm font-semibold text-[#1B3A5C]">
                  {meta.title}
                  {isSpot && (
                    <span className="ml-2 rounded-full bg-[#EDE9FE] px-2 py-0.5 text-[10px] font-normal text-[#6D28D9]">
                      contract = Spot
                    </span>
                  )}
                </div>
                <div className="mt-0.5 text-[11px] text-[#6B7280]">
                  {meta.subtitle} · {countNoun}: {total}
                </div>
              </div>
              <div className="text-xs text-[#6B7280]">
                {open ? "▾" : "▸"}
              </div>
            </button>
            {open && total > 0 && isSpot && (
              <SpotTable
                data={laneRows.filter((r) => r.bucket === b)}
                entityLabel={entityLabel}
                onCustomerClick={onCustomerClick}
              />
            )}
            {open && total > 0 && !isSpot && (
              <ReactiveTable
                bucket={b}
                data={rows.filter((r) => r.bucket === b)}
                entityLabel={entityLabel}
                onCustomerClick={onCustomerClick}
              />
            )}
            {open && total === 0 && (
              <div className="px-4 py-6 text-center text-xs text-[#9CA3AF]">
                No {isSpot ? "lanes" : entityLabel.toLowerCase() + "s"} in this
                bucket.
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// SpotTable — lane-grained Spot-only table for the Recent/Stale/>1yr buckets
// (Bruno 2026-05-25 pages 3-4). Every column sortable.
// ---------------------------------------------------------------------------

function SpotTable({
  data,
  entityLabel,
  onCustomerClick,
}: {
  data: LaneSummaryRow[]
  entityLabel: string
  onCustomerClick?: (customer: string) => void
}) {
  const { sorted, sortKey, sortDir, toggle } = useSortable<LaneSummaryRow>(
    data,
    "total_revenue",
    "desc",
  )
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[920px] text-[11px]">
        <thead className="bg-[#F0FDFA] text-[10px] uppercase tracking-wider text-[#0F766E]">
          <tr>
            <SortableTh<LaneSummaryRow> columnKey="customer" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">{entityLabel}</SortableTh>
            <SortableTh<LaneSummaryRow> columnKey="lane" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left">Lane</SortableTh>
            <SortableTh<LaneSummaryRow> columnKey="total_loads" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Loads</SortableTh>
            <SortableTh<LaneSummaryRow> columnKey="total_revenue" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Revenue</SortableTh>
            <SortableTh<LaneSummaryRow> columnKey="total_profit" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Profit</SortableTh>
            <SortableTh<LaneSummaryRow> columnKey="total_margin" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Margin</SortableTh>
            <SortableTh<LaneSummaryRow> columnKey="last_load_date" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Last Load Date</SortableTh>
            <SortableTh<LaneSummaryRow> columnKey="days_since_last_load" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Days Since</SortableTh>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#F3F4F6]">
          {sorted.map((r, i) => (
            <tr key={`${r.customer}-${r.lane}-${i}`} className="hover:bg-[#FAFAFA]">
              <td className="px-3 py-1.5 max-w-[220px] truncate" title={r.customer ?? ""}>
                {r.customer && onCustomerClick ? (
                  <button
                    type="button"
                    onClick={() => onCustomerClick(r.customer!)}
                    className="text-left text-[#1D4ED8] hover:underline"
                  >
                    {r.customer}
                  </button>
                ) : (
                  <span className="text-[#111827]">{r.customer || "—"}</span>
                )}
              </td>
              <td className="px-3 py-1.5 max-w-[260px] truncate font-mono text-[#374151]" title={r.lane ?? ""}>
                {r.lane || "—"}
              </td>
              <td className="px-3 py-1.5 text-right font-mono">{fmtCount(r.total_loads)}</td>
              <td className="px-3 py-1.5 text-right font-mono">{fmtUsd(r.total_revenue)}</td>
              <td className={`px-3 py-1.5 text-right font-mono ${r.total_profit < 0 ? "text-[#DC2626]" : ""}`}>
                {fmtUsd(r.total_profit)}
              </td>
              <td className={`px-3 py-1.5 text-right font-mono ${(r.total_margin ?? 0) < 0 ? "text-[#DC2626]" : ""}`}>
                {fmtPct(r.total_margin)}
              </td>
              <td className="px-3 py-1.5 text-right font-mono text-[#374151]">
                {fmtTimestamp(r.last_load_date)}
              </td>
              <td className="px-3 py-1.5 text-right font-mono text-[#374151]">
                {r.days_since_last_load ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ReactiveTable({
  bucket,
  data,
  entityLabel,
  onCustomerClick,
}: {
  bucket: Bucket
  data: ReactiveRow[]
  entityLabel: string
  onCustomerClick?: (customer: string) => void
}) {
  // Pick the comparison window per bucket. Mirrors Bruno's PDF.
  const variant: "lw" | "l2_4w" | "l5_9w" =
    bucket === "lw" ? "lw" : bucket === "l2_4w" ? "l2_4w" : "l5_9w"

  // Header label for the variant column block
  const variantLabel = {
    lw: { abs: "LW", load: "Loads (LW)", rev: "Rev (LW)", prof: "Profit (LW)", margin: "Margin (LW)" },
    l2_4w: {
      abs: "L2-4W avg",
      load: "Avg Loads (2-4W)",
      rev: "Avg Rev (2-4W)",
      prof: "Avg Profit (2-4W)",
      margin: "Margin (2-4W)",
    },
    l5_9w: {
      abs: "L5-9W avg",
      load: "Avg Loads (5-9W)",
      rev: "Avg Rev (5-9W)",
      prof: "Avg Profit (5-9W)",
      margin: "Margin (5-9W)",
    },
  }[variant]

  // Bruno round-4 (2026-05-12): every column sortable. Default sort kept as
  // most-attrited first (% loads var ascending — biggest drop on top).
  const variantKeys: {
    load: keyof ReactiveRow
    rev: keyof ReactiveRow
    profit: keyof ReactiveRow
    margin: keyof ReactiveRow
    pct_loads: keyof ReactiveRow
    pct_rev: keyof ReactiveRow
    pct_profit: keyof ReactiveRow
  } =
    variant === "lw"
      ? {
          load: "lw_loads",
          rev: "lw_revenue",
          profit: "lw_profit",
          margin: "lw_margin",
          pct_loads: "pct_var_loads_lw_vs_l8w",
          pct_rev: "pct_var_rev_lw_vs_l8w",
          pct_profit: "pct_var_profit_lw_vs_l8w",
        }
      : variant === "l2_4w"
        ? {
            load: "avg_loads_l2_4w",
            rev: "avg_rev_l2_4w",
            profit: "avg_profit_l2_4w",
            margin: "avg_margin_l2_4w",
            pct_loads: "pct_var_loads_l2_4_vs_l8w",
            pct_rev: "pct_var_rev_l2_4_vs_l8w",
            pct_profit: "pct_var_profit_l2_4_vs_l8w",
          }
        : {
            load: "avg_loads_l5_9w",
            rev: "avg_rev_l5_9w",
            profit: "avg_profit_l5_9w",
            margin: "avg_margin_l5_9w",
            pct_loads: "pct_var_loads_l5_9_vs_l8w",
            pct_rev: "pct_var_rev_l5_9_vs_l8w",
            pct_profit: "pct_var_profit_l5_9_vs_l8w",
          }

  const { sorted, sortKey, sortDir, toggle } = useSortable<ReactiveRow>(
    data,
    variantKeys.pct_loads,
    "asc",
  )

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1280px] text-[11px]">
        <thead className="bg-[#F0FDFA] text-[10px] uppercase tracking-wider text-[#0F766E]">
          <tr>
            <SortableTh<ReactiveRow> columnKey="team" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left" className="sticky left-0 bg-[#F0FDFA]">Team</SortableTh>
            <SortableTh<ReactiveRow> columnKey="customer" sortKey={sortKey} sortDir={sortDir} onToggle={toggle} align="left" className="sticky left-[80px] bg-[#F0FDFA]">{entityLabel}</SortableTh>
            <SortableTh<ReactiveRow> columnKey="avg_loads_l8w" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Avg Loads (L8W)</SortableTh>
            <SortableTh<ReactiveRow> columnKey={variantKeys.load} sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>{variantLabel.load}</SortableTh>
            <SortableTh<ReactiveRow> columnKey={variantKeys.pct_loads} sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>% Loads Var</SortableTh>
            <SortableTh<ReactiveRow> columnKey="avg_rev_l8w" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Avg Rev (L8W)</SortableTh>
            <SortableTh<ReactiveRow> columnKey={variantKeys.rev} sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>{variantLabel.rev}</SortableTh>
            <SortableTh<ReactiveRow> columnKey={variantKeys.pct_rev} sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>% Rev Var</SortableTh>
            <SortableTh<ReactiveRow> columnKey="avg_profit_l8w" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Avg Profit (L8W)</SortableTh>
            <SortableTh<ReactiveRow> columnKey={variantKeys.profit} sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>{variantLabel.prof}</SortableTh>
            <SortableTh<ReactiveRow> columnKey={variantKeys.pct_profit} sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>% Profit Var</SortableTh>
            <SortableTh<ReactiveRow> columnKey="avg_margin_l8w" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Margin (L8W)</SortableTh>
            <SortableTh<ReactiveRow> columnKey={variantKeys.margin} sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>{variantLabel.margin}</SortableTh>
            <SortableTh<ReactiveRow> columnKey="last_load_date" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Last Load Date</SortableTh>
            <SortableTh<ReactiveRow> columnKey="days_since_last_load" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Days Since</SortableTh>
            <SortableTh<ReactiveRow> columnKey="reactive_lw_returning" sortKey={sortKey} sortDir={sortDir} onToggle={toggle}>Reactive&nbsp;LW?</SortableTh>
          </tr>
        </thead>
        <tbody className="divide-y divide-[#F3F4F6]">
          {sorted.map((r, i) => {
            const v = pickVariant(r, variant)
            const lossSign = (n: number | null) =>
              n === null ? "" : n < 0 ? "text-[#DC2626]" : ""
            return (
              <tr key={`${r.team}-${r.customer}-${i}`} className="hover:bg-[#FAFAFA]">
                <td className="sticky left-0 bg-white px-3 py-1.5 font-mono text-[#374151]">
                  {r.team || "—"}
                </td>
                <td
                  className="sticky left-[80px] bg-white px-3 py-1.5 truncate max-w-[240px]"
                  title={r.customer ?? ""}
                >
                  {r.customer && onCustomerClick ? (
                    <button
                      type="button"
                      onClick={() => onCustomerClick(r.customer!)}
                      className="text-left text-[#1D4ED8] hover:underline"
                    >
                      {r.customer}
                    </button>
                  ) : (
                    <span className="text-[#111827]">{r.customer || "—"}</span>
                  )}
                </td>
                {/* Bruno round-5 (2026-05-19): reverted round-3's 1-decimal
                    AVG LOADS — Bruno wants integers across every bucket so
                    the columns read as plain counts. */}
                <td className="px-3 py-1.5 text-right font-mono">
                  {fmtCount(r.avg_loads_l8w)}
                </td>
                <td className="px-3 py-1.5 text-right font-mono">
                  {fmtCount(variant === "lw" ? r.lw_loads : v.loads)}
                </td>
                <PctCell v={v.pct_loads} />
                <td className="px-3 py-1.5 text-right font-mono">
                  {fmtUsd(r.avg_rev_l8w)}
                </td>
                <td className="px-3 py-1.5 text-right font-mono">
                  {variant === "lw" ? fmtUsd(r.lw_revenue) : fmtUsd(v.rev)}
                </td>
                <PctCell v={v.pct_rev} />
                <td className={`px-3 py-1.5 text-right font-mono ${lossSign(r.avg_profit_l8w)}`}>
                  {fmtUsd(r.avg_profit_l8w)}
                </td>
                <td className={`px-3 py-1.5 text-right font-mono ${lossSign(variant === "lw" ? r.lw_profit : v.profit)}`}>
                  {variant === "lw" ? fmtUsd(r.lw_profit) : fmtUsd(v.profit)}
                </td>
                <PctCell v={v.pct_profit} />
                <td className="px-3 py-1.5 text-right font-mono">
                  {fmtPct(r.avg_margin_l8w)}
                </td>
                <td className="px-3 py-1.5 text-right font-mono">
                  {variant === "lw"
                    ? fmtPct(r.lw_margin)
                    : variant === "l2_4w"
                      ? fmtPct(r.avg_margin_l2_4w)
                      : fmtPct(r.avg_margin_l5_9w)}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-[#374151]">
                  {fmtTimestamp(r.last_load_date)}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-[#374151]">
                  {r.days_since_last_load ?? "—"}
                </td>
                <td className="px-3 py-1.5 text-right">
                  <ReactiveLwBadge row={r} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function pickVariant(r: ReactiveRow, variant: "lw" | "l2_4w" | "l5_9w") {
  if (variant === "lw") {
    return {
      loads: r.lw_loads,
      rev: r.lw_revenue,
      profit: r.lw_profit,
      pct_loads: r.pct_var_loads_lw_vs_l8w,
      pct_rev: r.pct_var_rev_lw_vs_l8w,
      pct_profit: r.pct_var_profit_lw_vs_l8w,
    }
  }
  if (variant === "l2_4w") {
    return {
      loads: r.avg_loads_l2_4w,
      rev: r.avg_rev_l2_4w,
      profit: r.avg_profit_l2_4w,
      pct_loads: r.pct_var_loads_l2_4_vs_l8w,
      pct_rev: r.pct_var_rev_l2_4_vs_l8w,
      pct_profit: r.pct_var_profit_l2_4_vs_l8w,
    }
  }
  return {
    loads: r.avg_loads_l5_9w,
    rev: r.avg_rev_l5_9w,
    profit: r.avg_profit_l5_9w,
    pct_loads: r.pct_var_loads_l5_9_vs_l8w,
    pct_rev: r.pct_var_rev_l5_9_vs_l8w,
    pct_profit: r.pct_var_profit_l5_9_vs_l8w,
  }
}

function PctCell({ v }: { v: number | null }) {
  const s = fmtSignedPct(v)
  // Bruno round-3 (2026-05-07): tiered variance band — green ≥17% growth,
  // yellow [12%, 17%) growth, red <12% (incl. negatives). Replaces the old
  // ±50% / around-zero shading.
  const bg = varianceBandClass(v)
  return (
    <td className={`px-3 py-1.5 text-right font-mono ${bg} ${s.className}`}>
      {s.text}
    </td>
  )
}

// Bruno round-3 (2026-05-07): the "Reactive LW?" column now flags any
// customer whose last load was within 7 days AND whose prior load was 8-63
// days before — i.e. they hopped back from the 2-4W or 5-9W stale bucket.
// Customers who load every week aren't reactive (no gap to bridge).
function ReactiveLwBadge({ row }: { row: ReactiveRow }) {
  if (row.reactive_lw_returning) {
    return (
      <span
        className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-[10px] font-semibold text-[#1E40AF]"
        title={
          row.gap_before_last !== null
            ? `Returned after ${row.gap_before_last}d gap`
            : "Returned after a stale period"
        }
      >
        ●
      </span>
    )
  }
  return <span className="text-[#9CA3AF]">—</span>
}
