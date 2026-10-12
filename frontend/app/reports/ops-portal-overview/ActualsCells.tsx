"use client"

import { ArrowDown, ArrowUp } from "lucide-react"
import {
  fmtCount,
  fmtUsd,
  fmtUsdSigned,
  type OppActualsRow,
  type OppActualsTotals,
} from "@/lib/ops-portal-overview-api"

// Bruno round 3 (2026-05-19): per-cell display mode toggle —
// only the chosen sub-row renders inside each Volume/Revenue/Profit/Margin cell.
// Bruno R4 (2026-05-27): added "all" — Production / Budget / Variance stacked.
export type Mode = "production" | "budget" | "variance" | "all"

/** What the cells compare the selected window against.
 *  "budget" — CORP: the daily budget table.
 *  "prior_month" — DFW (Bruno PDF 2026-10-12): the SAME days of the previous
 *  month, computed server-side (`*_prev` / `*_vs_prev`, `meta.compare`). */
export type ActualsCompare = "budget" | "prior_month"

export type Metric = "vol" | "rev" | "prof" | "margin"

/** One metric's three legs: the window's actual, the comparison base, and
 *  actual − base. Both the cells and the sort accessors read THIS, so a column
 *  can never sort on one leg while it renders another. */
export interface Leg {
  actual: number
  base: number
  variance: number
}

export function legOf(
  r: OppActualsRow | OppActualsTotals,
  m: Metric,
  compare: ActualsCompare,
): Leg {
  const prior = compare === "prior_month"
  switch (m) {
    case "vol":
      return prior
        ? { actual: r.vol, base: r.vol_prev ?? 0, variance: r.vol_vs_prev ?? 0 }
        : { actual: r.vol, base: r.vol_budget, variance: r.vol_var }
    case "rev":
      return prior
        ? { actual: r.rev, base: r.rev_prev ?? 0, variance: r.rev_vs_prev ?? 0 }
        : { actual: r.rev, base: r.rev_budget, variance: r.rev_var }
    case "prof":
      return prior
        ? { actual: r.prof, base: r.prof_prev ?? 0, variance: r.prof_vs_prev ?? 0 }
        : { actual: r.prof, base: r.prof_budget, variance: r.prof_var }
    case "margin":
      return prior
        ? { actual: r.margin_pct, base: r.margin_prev_pct ?? 0, variance: r.margin_vs_prev_pct ?? 0 }
        : { actual: r.margin_pct, base: r.margin_budget_pct, variance: r.margin_var_pct }
  }
}

/** The value a column sorts on under `mode` — the leg the cell shows on top. */
export function sortValue(leg: Leg, mode: Mode): number {
  return mode === "budget" ? leg.base : mode === "variance" ? leg.variance : leg.actual
}

const BUDGET_PILLS: readonly { k: Mode; label: string }[] = [
  // Bruno (PDF 2026-08-31) R7 renamed two pills. The MODE KEYS are
  // deliberately unchanged — `hideBudget` filters on `o.k !== "production"`
  // and the cell/accessor switches all branch on them, so renaming a key
  // to match its new label would silently unhide the DFW budget pills.
  { k: "all",        label: "All" },
  { k: "production", label: "Actual" },
  { k: "budget",     label: "Budget" },
  { k: "variance",   label: "Actual vs Budget Variances" },
]

// Bruno PDF 2026-10-12 (DFW) R1 — the three buttons, named as he wrote them.
// There is no "base only" pill: the previous month shows inside All.
const PRIOR_MONTH_PILLS: readonly { k: Mode; label: string }[] = [
  { k: "all",        label: "All" },
  { k: "production", label: "Actuals" },
  { k: "variance",   label: "Variances" },
]

/** The mode the table opens on. "all" whenever it has a comparison; with the
 *  budget hidden and nothing else to compare, Production is the only mode
 *  left and MUST be the default (Bruno PDF 2026-08-20 R8). */
export function defaultMode(hideBudget: boolean, compare: ActualsCompare): Mode {
  return hideBudget && compare === "budget" ? "production" : "all"
}

export function ModePills({
  mode,
  setMode,
  hideBudget = false,
  compare = "budget",
}: {
  mode: Mode
  setMode: (m: Mode) => void
  hideBudget?: boolean
  compare?: ActualsCompare
}) {
  // Bruno PDF 2026-08-20 DFW R8 removes All / Budget / Variance per Cell
  // when the comparison is the budget — on DFW they would render empty sub-rows.
  const opts = compare === "prior_month"
    ? PRIOR_MONTH_PILLS
    : BUDGET_PILLS.filter((o) => !(hideBudget && o.k !== "production"))
  // One pill left is a label, not a control — hide the whole strip.
  if (opts.length <= 1) return null
  return (
    <div className="flex rounded-lg border border-[#E5E7EB] bg-white text-xs">
      {opts.map((o) => (
        <button
          key={o.k}
          type="button"
          onClick={() => setMode(o.k)}
          className={`px-3 py-1 ${
            mode === o.k
              ? "bg-[#1B3A5C] font-semibold text-white"
              : "text-[#6B7280] hover:text-[#111827]"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function SortableTh({
  children,
  align = "left",
  active,
  dir,
  onClick,
}: {
  children: React.ReactNode
  align?: "left" | "right" | "center"
  active: boolean
  dir: "asc" | "desc"
  onClick: () => void
}) {
  const cls =
    align === "right" ? "text-right"
    : align === "center" ? "text-center"
    : "text-left"
  const justify =
    align === "right" ? "justify-end"
    : align === "center" ? "justify-center"
    : "justify-start"
  return (
    <th className={`px-2 py-2 ${cls}`}>
      <button
        type="button"
        onClick={onClick}
        className={`inline-flex w-full items-center gap-1 ${justify} ${
          active ? "font-bold text-[#1B3A5C]" : "hover:text-[#374151]"
        }`}
      >
        {children}
        {active && (dir === "asc" ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
      </button>
    </th>
  )
}

export function ModeCell({
  mode,
  kind,
  leg,
}: {
  mode: Mode
  kind: "count" | "usd" | "pct"
  leg: Leg
}) {
  const { actual, base, variance } = leg
  const fmt = (v: number) =>
    kind === "count" ? fmtCount(v)
    : kind === "pct" ? `${v.toFixed(2)}%`
    : fmtUsd(v)
  const fmtSigned = (v: number) =>
    kind === "count" ? `${v >= 0 ? "+" : ""}${fmtCount(v)}`
    : kind === "pct" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`
    : fmtUsdSigned(v)

  if (mode === "all") {
    // Bruno R5 #9: actual (big) with the base bottom-left + variance bottom-right.
    // Bruno R5 #10: actual ÷ base % beside the cell (budget on CORP, the
    // previous month's same days on DFW — Bruno PDF 2026-10-12).
    const pct = base !== 0 ? (actual / base) * 100 : null
    return (
      <td className="px-2 py-1.5 text-center tabular-nums">
        <div className="flex items-center justify-center gap-1.5">
          <div className="min-w-[64px]">
            {/* R15 (2026-06-24, All tab only): big Actual value now blue. */}
            <div className={`font-semibold text-sm text-[#2563EB] ${kind !== "count" && actual < 0 ? "!text-[#DC2626]" : ""}`}>
              {fmt(actual)}
            </div>
            <div className="flex items-center justify-between gap-2 text-[10px]">
              <span className="text-[#6B7280]">{fmt(base)}</span>
              <span className={variance < 0 ? "font-medium text-[#DC2626]" : "font-medium text-[#16A34A]"}>
                {fmtSigned(variance)}
              </span>
            </div>
          </div>
          {/* R15: actual ÷ base % value now black. */}
          {pct !== null && (
            <span className="text-[10px] font-semibold text-[#111827]">{Math.round(pct)}%</span>
          )}
        </div>
      </td>
    )
  }
  if (mode === "production") {
    return (
      <td className="px-2 py-1.5 text-center tabular-nums">
        <span className={`font-semibold text-[#1B3A5C] ${kind !== "count" && actual < 0 ? "!text-[#DC2626]" : ""}`}>
          {fmt(actual)}
        </span>
      </td>
    )
  }
  if (mode === "budget") {
    return (
      <td className="px-2 py-1.5 text-center tabular-nums">
        <span className="font-semibold text-[#1B3A5C]">{fmt(base)}</span>
      </td>
    )
  }
  return (
    <td className="px-2 py-1.5 text-center tabular-nums">
      <span className={variance < 0 ? "font-semibold text-[#DC2626]" : "font-semibold text-[#16A34A]"}>
        {fmtSigned(variance)}
      </span>
    </td>
  )
}
