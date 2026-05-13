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

type StatusKind = "Top" | "Stable" | "Critical" | "NA"

// Bruno round-4 (2026-05-12): Status text column with explicit Top/Stable/
// Critical labels. Same rule as the old inline dot — both LW & L2W ≥ ref →
// Top, both below → Critical, one of each → Stable.
function computeStatus(
  lw: number | null,
  l2w: number | null,
  ref: number | null,
): StatusKind {
  if (ref === null || lw === null || l2w === null) return "NA"
  const lwBelow = lw < ref
  const l2wBelow = l2w < ref
  if (!lwBelow && !l2wBelow) return "Top"
  if (lwBelow && l2wBelow) return "Critical"
  return "Stable"
}

const STATUS_ORDER: Record<StatusKind, number> = { Critical: 0, Stable: 1, Top: 2, NA: 3 }

interface Props {
  filters: AttritionFilters
  // Bruno round-3 (2026-05-07): clicking a row key in the by-customer or
  // customer_lane view applies the customer (and optionally lane) filter.
  onCustomerClick?: (customer: string) => void
  onLaneClick?: (lane: string) => void
}

type Metric = "loads" | "revenue" | "profit" | "margin"
type Dim = "customer" | "team" | "customer_lane"

const METRICS: { key: Metric; label: string; fmt: (v: number | null | undefined) => string }[] = [
  { key: "loads",   label: "# Loads",    fmt: fmtCount },
  { key: "revenue", label: "$ Revenue",  fmt: fmtUsd },
  { key: "profit",  label: "$ Profit",   fmt: fmtUsd },
  { key: "margin",  label: "% Margin",   fmt: fmtPct },
]

const DIMS: { key: Dim; label: string }[] = [
  { key: "team",          label: "by Team" },
  { key: "customer",      label: "by Customer" },
  { key: "customer_lane", label: "by Customer and Lane" },
]

export function PivotsTab({ filters, onCustomerClick, onLaneClick }: Props) {
  const [metric, setMetric] = useState<Metric>("loads")
  const [dim, setDim] = useState<Dim>("team")
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
            {DIMS.map((d) => (
              <button
                key={d.key}
                onClick={() => setDim(d.key)}
                className={`px-3 py-1.5 ${
                  dim === d.key
                    ? "rounded-md bg-white font-semibold text-[#1B3A5C] shadow-sm"
                    : "text-[#6B7280] hover:text-[#111827]"
                }`}
              >
                {d.label}
              </button>
            ))}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-3 text-[11px] text-[#374151]">
          {/* Bruno round-3: bigger legend explaining the row color band. */}
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-sm bg-[#DCFCE7]" />
            <span>cell ≥ row 8w avg</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="inline-block h-3 w-3 rounded-sm bg-[#FEE2E2]" />
            <span>cell &lt; row 8w avg</span>
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
      />
    </div>
  )
}

function PivotPanel({
  filters,
  dim,
  metric,
  weeks,
  onCustomerClick,
  onLaneClick,
}: {
  filters: AttritionFilters
  dim: Dim
  metric: Metric
  weeks: number
  onCustomerClick?: (customer: string) => void
  onLaneClick?: (lane: string) => void
}) {
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
  const [sortKey, setSortKey] = useState<string>("total")
  const [sortDir, setSortDir] = useState<SortDir>("desc")
  const toggleSort = (k: string) => {
    if (sortKey === k) setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    else {
      setSortKey(k)
      setSortDir("desc")
    }
  }

  // Build wide pivot: weeks (cols, latest first) × dim_keys (rows)
  const { weeksList, pivot } = useMemo(() => {
    const weekSet = new Set<string>()
    const byKey = new Map<string, Map<string, number | null>>()
    for (const r of rows as PivotRow[]) {
      weekSet.add(r.week_start)
      if (!byKey.has(r.dim_key)) byKey.set(r.dim_key, new Map())
      byKey.get(r.dim_key)!.set(r.week_start, r.value)
    }
    const weeksList = Array.from(weekSet).sort().reverse() // latest first
    const pivotEntries = Array.from(byKey.entries()).map(([k, weekMap]) => {
      const values = weeksList.map((w) => weekMap.get(w) ?? null)
      // 8-week ref: avg of the 8 most-recent NON-NULL completed weeks per row
      const ref = (() => {
        const nonNull = values.filter((v): v is number => v !== null)
        if (nonNull.length === 0) return null
        const slice = nonNull.slice(0, 8)
        return slice.reduce((a, b) => a + b, 0) / slice.length
      })()
      const total = values.reduce<number>((a, b) => a + (b ?? 0), 0)
      const status = computeStatus(values[0] ?? null, values[1] ?? null, ref)
      return { dim_key: k, values, ref, total, status }
    })
    pivotEntries.sort((a, b) => {
      if (sortKey === "status") {
        const av = STATUS_ORDER[a.status]
        const bv = STATUS_ORDER[b.status]
        return sortDir === "asc" ? av - bv : bv - av
      }
      if (sortKey === "dim_key") {
        const av = a.dim_key.toLowerCase()
        const bv = b.dim_key.toLowerCase()
        if (av < bv) return sortDir === "asc" ? -1 : 1
        if (av > bv) return sortDir === "asc" ? 1 : -1
        return 0
      }
      if (sortKey === "ref") {
        const av = a.ref
        const bv = b.ref
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
    return { weeksList, pivot: pivotEntries }
  }, [rows, sortKey, sortDir])

  if (isLoading && pivot.length === 0) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-[#6B7280]" />
      </div>
    )
  }

  const headerLabel =
    dim === "team"
      ? "Team"
      : dim === "customer"
        ? "Customer"
        : "Customer · Lane"

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
              <SortTh
                k="dim_key"
                sortKey={sortKey}
                sortDir={sortDir}
                onToggle={toggleSort}
                align="left"
                className="sticky left-[100px] z-10 bg-[#F9FAFB]"
              >
                {headerLabel}
              </SortTh>
              <SortTh
                k="ref"
                sortKey={sortKey}
                sortDir={sortDir}
                onToggle={toggleSort}
                className="bg-[#F9FAFB] text-[#1B3A5C]"
              >
                8-week avg
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
                <td
                  className="sticky left-[100px] z-10 max-w-[320px] truncate bg-white px-3 py-1.5 text-[#111827]"
                  title={row.dim_key}
                >
                  <DimKeyCell
                    dim={dim}
                    value={row.dim_key}
                    onCustomerClick={onCustomerClick}
                    onLaneClick={onLaneClick}
                  />
                </td>
                <td className="bg-white px-3 py-1.5 text-right font-mono font-semibold text-[#1B3A5C]">
                  {row.ref === null ? "—" : fmt(row.ref)}
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
                <td colSpan={weeksList.length + 3} className="py-8 text-center text-xs text-[#9CA3AF]">
                  No data in scope.
                </td>
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
    status === "Top"
      ? "bg-[#DCFCE7] text-[#15803D]"
      : status === "Stable"
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
  // Treat 0 as below-average for non-zero ref (Bruno's coloring rule).
  if (v > ref) return "bg-[#DCFCE7] text-[#15803D]"
  if (v < ref) return "bg-[#FEE2E2] text-[#DC2626]"
  return "text-[#374151]"
}

function fmtMonDay(iso: string): string {
  try {
    const d = new Date(iso + "T00:00:00")
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" })
  } catch {
    return iso
  }
}

