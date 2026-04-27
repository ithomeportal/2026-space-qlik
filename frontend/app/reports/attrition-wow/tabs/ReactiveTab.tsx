"use client"

import { Loader2 } from "lucide-react"
import { useMemo, useState } from "react"
import {
  useAttritionReactive,
  type AttritionFilters,
  type ReactiveRow,
} from "@/lib/attrition-wow-api"
import { AttritionErrorBanner } from "../ErrorBanner"
import {
  fmtCount,
  fmtPct,
  fmtSignedPct,
  fmtTimestamp,
  fmtUsd,
} from "../format"

interface Props {
  filters: AttritionFilters
}

type Bucket = ReactiveRow["bucket"]

const BUCKET_LABELS: Record<Bucket, { title: string; subtitle: string; days: string }> = {
  lw: {
    title: "Summary — Last Week (1–7 days)",
    subtitle: "Active in the last completed Mon-Sun week",
    days: "1–7",
  },
  l2_4w: {
    title: "Summary — 2 to 4 Weeks (8–28 days)",
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

export function ReactiveTab({ filters }: Props) {
  const { data: res, isLoading, error } = useAttritionReactive(filters)
  const rows = res?.data ?? []

  // Counts per bucket so empty sections collapse cleanly.
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
    for (const r of rows) c[r.bucket] += 1
    return c
  }, [rows])

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
      <AttritionErrorBanner errors={[error]} label="Reactive Customers" />

      {BUCKET_ORDER.map((b) => {
        const meta = BUCKET_LABELS[b]
        const data = rows.filter((r) => r.bucket === b)
        const total = counts[b]
        const open = openBuckets.has(b)
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
                </div>
                <div className="mt-0.5 text-[11px] text-[#6B7280]">
                  {meta.subtitle} · Customers: {total}
                </div>
              </div>
              <div className="text-xs text-[#6B7280]">
                {open ? "▾" : "▸"}
              </div>
            </button>
            {open && total > 0 && <ReactiveTable bucket={b} data={data} />}
            {open && total === 0 && (
              <div className="px-4 py-6 text-center text-xs text-[#9CA3AF]">
                No customers in this bucket.
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function ReactiveTable({
  bucket,
  data,
}: {
  bucket: Bucket
  data: ReactiveRow[]
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

  // Sort: most-attrited first (lowest pct_var_loads_lw_vs_l8w / l2_4 / l5_9)
  const sorted = useMemo(() => {
    const k =
      variant === "lw"
        ? "pct_var_loads_lw_vs_l8w"
        : variant === "l2_4w"
          ? "pct_var_loads_l2_4_vs_l8w"
          : "pct_var_loads_l5_9_vs_l8w"
    return [...data].sort((a, b) => {
      const av = a[k] ?? 0
      const bv = b[k] ?? 0
      return av - bv
    })
  }, [data, variant])

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1280px] text-[11px]">
        <thead className="bg-[#F0FDFA] text-[10px] uppercase tracking-wider text-[#0F766E]">
          <tr>
            <th className="sticky left-0 bg-[#F0FDFA] px-3 py-2 text-left">Team</th>
            <th className="sticky left-[80px] bg-[#F0FDFA] px-3 py-2 text-left">Customer</th>
            <th className="px-3 py-2 text-right">Avg Loads (L8W)</th>
            <th className="px-3 py-2 text-right">{variantLabel.load}</th>
            <th className="px-3 py-2 text-right">% Loads Var</th>
            <th className="px-3 py-2 text-right">Avg Rev (L8W)</th>
            <th className="px-3 py-2 text-right">{variantLabel.rev}</th>
            <th className="px-3 py-2 text-right">% Rev Var</th>
            <th className="px-3 py-2 text-right">Avg Profit (L8W)</th>
            <th className="px-3 py-2 text-right">{variantLabel.prof}</th>
            <th className="px-3 py-2 text-right">% Profit Var</th>
            <th className="px-3 py-2 text-right">Margin (L8W)</th>
            <th className="px-3 py-2 text-right">{variantLabel.margin}</th>
            <th className="px-3 py-2 text-right">Last Load Date</th>
            <th className="px-3 py-2 text-right">Days Since</th>
            <th className="px-3 py-2 text-right">Reactive&nbsp;LW?</th>
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
                <td className="sticky left-[80px] bg-white px-3 py-1.5 truncate max-w-[240px] text-[#111827]" title={r.customer ?? ""}>
                  {r.customer || "—"}
                </td>
                <td className="px-3 py-1.5 text-right font-mono">
                  {fmtCount(r.avg_loads_l8w)}
                </td>
                <td className="px-3 py-1.5 text-right font-mono">
                  {variant === "lw"
                    ? fmtCount(r.lw_loads)
                    : fmtCount(v.loads)}
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
                  {r.reactive_this_week ? (
                    <span className="rounded-full bg-[#DBEAFE] px-2 py-0.5 text-[10px] font-semibold text-[#1E40AF]">
                      ●
                    </span>
                  ) : (
                    <span className="text-[#9CA3AF]">—</span>
                  )}
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
  // Bg shade for ≤-50%, ≥+50%, around-0
  let bg = ""
  if (v !== null) {
    if (v <= -0.5) bg = "bg-[#FEE2E2]"
    else if (v >= 0.5) bg = "bg-[#DCFCE7]"
    else if (v > -0.05 && v < 0.05) bg = "bg-[#FEF3C7]"
  }
  return (
    <td className={`px-3 py-1.5 text-right font-mono ${bg} ${s.className}`}>
      {s.text}
    </td>
  )
}
