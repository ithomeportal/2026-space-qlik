"use client"

import { useEffect, useMemo, useState } from "react"
import { ArrowDown, ArrowUp, Loader2, Maximize2, X } from "lucide-react"
import { fmtAttritionPct } from "@/lib/ops-portal-overview-api"

// Shared building blocks of the Ops Portal side panels (PanelCard, Row,
// sortable mini tables, expand modal, Week/Team buttons).
// Moved verbatim out of SidePanels.tsx (layout 2026-10-28) — one panel per file.

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

export function PanelCard({
  title,
  icon,
  loading,
  error,
  action,
  leadingAction,
  children,
}: {
  title: string
  icon?: string
  loading?: boolean
  error?: unknown
  action?: React.ReactNode
  /** Bruno R11 — small control rendered at the top-left of the header (e.g. expand). */
  leadingAction?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2 text-sm font-semibold text-[#3B82F6]">
        {leadingAction}
        {icon && <span aria-hidden>{icon}</span>}
        <span>{title}</span>
        {action && <span className="ml-1">{action}</span>}
        {loading && <Loader2 className="ml-auto h-3 w-3 animate-spin text-[#6B7280]" />}
      </div>
      {error ? (
        <div className="px-3 py-3 text-xs text-[#DC2626]">Failed to load</div>
      ) : (
        <div className="px-3 py-2">{children}</div>
      )}
    </section>
  )
}

export function Row({
  label,
  value,
  signed,
  numeric,
  highlight,
  bandPct,
  valueClassName,
}: {
  label: string
  value: string
  signed?: boolean
  numeric?: number
  /**
   * Explicit colour for the value cell, overriding the `signed` red/black.
   * Used by the two Attrition rows, whose sign convention is INVERTED — a
   * negative % Δ means the active roster grew, which is good news and must
   * render green (Bruno PDF 2026-08-31 R3, §95).
   */
  valueClassName?: string
  /** Bold + soft background — Bruno round-2 marker for Volume/Profit/Margin. */
  highlight?: boolean
  /**
   * OTP/OTD coloured-band swatch (Bruno round-2): >=95.5% green,
   * >=93% & <95.5% yellow, <93% red. Pass the percentage value.
   */
  bandPct?: number
}) {
  const isNeg = signed && (numeric ?? 0) < 0
  const bandCls =
    bandPct === undefined
      ? ""
      : bandPct >= 95.5
      ? "bg-[#DCFCE7] text-[#166534]"
      : bandPct >= 93
      ? "bg-[#FEF9C3] text-[#854D0E]"
      : "bg-[#FEE2E2] text-[#991B1B]"
  return (
    <tr className={`border-t border-[#F3F4F6] first:border-t-0 ${highlight ? "bg-[#F0F9FF]" : ""}`}>
      <td className={`px-1 py-1 ${highlight ? "font-semibold text-[#1B3A5C]" : "text-[#6B7280]"}`}>
        {label}
      </td>
      <td className="px-1 py-1 text-right tabular-nums">
        {bandPct !== undefined ? (
          <span className={`rounded px-1.5 py-0.5 font-semibold ${bandCls}`}>{value}</span>
        ) : (
          <span
            className={`${
              valueClassName ?? (isNeg ? "text-[#DC2626]" : "text-[#374151]")
            } ${highlight ? "font-bold text-[#1B3A5C]" : ""}`}
          >
            {value}
          </span>
        )}
      </td>
    </tr>
  )
}

/** One attrition row — inverted colours, matching the attrition-wow cards.
 *
 * ⚠ `undefined` (still loading / failed) must render "—", not "0.00%". Zero is
 * a real and meaningful value here — it means the active roster held exactly
 * flat week over week — so a falsy check would print a lie while the panel is
 * still loading. */
export function AttritionRow({ label, pct }: { label: string; pct?: number }) {
  const a = pct === undefined ? null : fmtAttritionPct(pct)
  return (
    <Row
      label={label}
      value={a ? a.text : "—"}
      valueClassName={a ? a.className : undefined}
    />
  )
}

// ---------------------------------------------------------------------------
// R9 — clickable customer-name cell. Looks like a link only when a drill
// handler is provided; otherwise renders plain text (preserves the old look).
// ---------------------------------------------------------------------------

export function CustomerNameCell({ name, onPick }: { name: string; onPick?: (c: string) => void }) {
  if (!onPick) return <>{name}</>
  return (
    <button
      type="button"
      onClick={() => onPick(name)}
      className="truncate text-left text-[#2563EB] hover:underline"
      title={`Drill to ${name}`}
    >
      {name}
    </button>
  )
}

// ---------------------------------------------------------------------------
// R11 (Bruno) — top-left expand button + modal rendering the uncapped table.
// ---------------------------------------------------------------------------

export function ExpandButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={`Expand ${label}`}
      aria-label={`Expand ${label}`}
      className="flex h-5 w-5 items-center justify-center rounded border border-[#BFDBFE] bg-white text-[#2563EB] hover:bg-[#EFF6FF]"
    >
      <Maximize2 className="h-3.5 w-3.5" />
    </button>
  )
}

export function ExpandModal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-5xl flex-col overflow-hidden rounded-lg bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#E5E7EB] bg-[#F9FAFB] px-4 py-2 text-sm font-semibold text-[#1B3A5C]">
          <span>{title}</span>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-6 w-6 items-center justify-center rounded text-[#6B7280] hover:bg-[#E5E7EB]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="overflow-auto px-4 py-3">{children}</div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Mini sortable-table helpers (Bruno R5 #14/#15) — reused by the two Customer
// panels. Client-side: the lists are already capped server-side at 50 rows.
// ---------------------------------------------------------------------------

export type MiniDir = "asc" | "desc"

export function useMiniSort<T, K extends string>(
  rows: T[],
  accessors: Record<K, (r: T) => number | string>,
  initialKey: K,
  initialDir: MiniDir,
) {
  const [sortKey, setSortKey] = useState<K>(initialKey)
  const [sortDir, setSortDir] = useState<MiniDir>(initialDir)
  const sorted = useMemo(() => {
    const acc = accessors[sortKey]
    if (!acc) return rows
    const mult = sortDir === "asc" ? 1 : -1
    return [...rows].sort((a, b) => {
      const va = acc(a)
      const vb = acc(b)
      if (typeof va === "string" || typeof vb === "string") {
        return String(va).localeCompare(String(vb)) * mult
      }
      return ((va as number) - (vb as number)) * mult
    })
    // accessors is a stable literal per render site; key/dir/rows drive it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rows, sortKey, sortDir])
  const onSort = (k: K) => {
    if (k === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortKey(k)
      // Text col → asc, numeric col → desc on first click.
      setSortDir(k === "name" ? "asc" : "desc")
    }
  }
  return { rows: sorted, sortKey, sortDir, onSort }
}

export function MiniTh<K extends string>({
  children,
  k,
  align,
  sortKey,
  dir,
  onSort,
}: {
  children: React.ReactNode
  k: K
  align: "left" | "right"
  sortKey: K
  dir: MiniDir
  onSort: (k: K) => void
}) {
  const active = sortKey === k
  const cls = align === "right" ? "text-right" : "text-left"
  const justify = align === "right" ? "justify-end" : "justify-start"
  return (
    <th className={`px-2 py-1 ${cls}`}>
      <button
        type="button"
        onClick={() => onSort(k)}
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

// ---------------------------------------------------------------------------
// Bruno (PDF 2026-07-13) — Week / Team break-out modals for the Team Budget
// Variance and Team Monthly Projection panels.
// ---------------------------------------------------------------------------

export function WeekTeamButtons({
  onWeek,
  onTeam,
  onTrend,
  lockedTeam,
}: {
  onWeek: () => void
  onTeam: () => void
  // Request 2026-08-25 — only the projection panel has a stored history, so
  // the Variance panel calls this without `onTrend` and gets no third button.
  onTrend?: () => void
  lockedTeam?: string
}) {
  const btn =
    "flex h-5 items-center justify-center rounded border border-[#BFDBFE] bg-white px-1.5 text-[10px] font-semibold text-[#2563EB] hover:bg-[#EFF6FF]"
  return (
    <span className="flex items-center gap-1">
      <button type="button" onClick={onWeek} className={btn} title="Break out by the last 5 weeks">
        Week
      </button>
      {/* Cross-team breakdown is meaningless on the single-team CORP copies. */}
      {!lockedTeam && (
        <button type="button" onClick={onTeam} className={btn} title="Break out by team">
          Team
        </button>
      )}
      {onTrend && (
        <button
          type="button"
          onClick={onTrend}
          className={btn}
          title="This month's high / low path and the monthly error rate"
        >
          Trend
        </button>
      )}
    </span>
  )
}

// Signed colour for a variance/projection numeric cell.
export function signCls(n: number): string {
  return n < 0 ? "text-[#DC2626]" : "text-[#374151]"
}

// "% of total" for a team column's additive cell (null when total is 0). Bruno
// (PDF 2026-07-15) R3/R4: returned as a number so MetricMatrixModal can render it
// small + light-gray beside the value rather than inline at full size.
export function concPct(val: number, total: number): number | null {
  if (!total) return null
  return (val / total) * 100
}
