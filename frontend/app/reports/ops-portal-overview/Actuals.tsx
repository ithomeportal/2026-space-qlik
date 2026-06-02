"use client"

import { useMemo, useState } from "react"
import { ArrowDown, ArrowUp, Loader2 } from "lucide-react"
import {
  fmtCount,
  fmtPct,
  fmtUsd,
  fmtUsdSigned,
  useOppActuals,
  type OppActualsRow,
  type OppActualsTotals,
  type OppFilters,
} from "@/lib/ops-portal-overview-api"

interface Props {
  filters: OppFilters
}

// Bruno round 3 (2026-05-19): per-cell display mode toggle —
// only the chosen sub-row renders inside each Volume/Revenue/Profit/Margin cell.
// Bruno R4 (2026-05-27): added "all" — Production / Budget / Variance stacked.
type Mode = "production" | "budget" | "variance" | "all"

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
  accessor: (r: OppActualsRow, mode: Mode) => number | string
}[] = [
  { k: "customer_name", label: "Customer Name", align: "left",   numeric: false,
    accessor: (r) => (r.customer_name || "").toUpperCase() },
  { k: "vol", label: "Volume", align: "center", numeric: true,
    accessor: (r, m) => m === "budget" ? r.vol_budget : m === "variance" ? r.vol_var : r.vol },
  { k: "rev", label: "Revenue", align: "center", numeric: true,
    accessor: (r, m) => m === "budget" ? r.rev_budget : m === "variance" ? r.rev_var : r.rev },
  { k: "prof", label: "Profit", align: "center", numeric: true,
    accessor: (r, m) => m === "budget" ? r.prof_budget : m === "variance" ? r.prof_var : r.prof },
  { k: "margin", label: "Margin", align: "center", numeric: true,
    accessor: (r, m) => m === "budget" ? r.margin_budget_pct : m === "variance" ? r.margin_var_pct : r.margin_pct },
  { k: "otp",  label: "OTP %",   align: "right", numeric: true, accessor: (r) => r.otp_pct },
  { k: "otd",  label: "OTD %",   align: "right", numeric: true, accessor: (r) => r.otd_pct },
  { k: "rev_x_l",  label: "Rev. x L",  align: "right", numeric: true, accessor: (r) => r.rev_x_l },
  { k: "prof_x_l", label: "Prof. x L", align: "right", numeric: true, accessor: (r) => r.prof_x_l },
  { k: "vol_x_day",  label: "Vol. x Day",  align: "center", numeric: true, accessor: (r) => r.vol_x_day },
  { k: "prof_x_day", label: "Prof. x Day", align: "center", numeric: true, accessor: (r) => r.prof_x_day },
  { k: "proj_eom_vol",  label: "Proj. EOM Vol.",   align: "center", numeric: true, accessor: (r) => r.proj_eom_vol },
  { k: "proj_eom_prof", label: "Proj. EOM Profit", align: "center", numeric: true, accessor: (r) => r.proj_eom_prof },
]

export function Actuals({ filters }: Props) {
  // Bruno R6 (2026-06-02): default the Actuals table to the "All" filter view.
  const [mode, setMode] = useState<Mode>("all")
  const [sortKey, setSortKey] = useState<ColumnKey>("rev")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")

  // Fetch with a stable backend sort; we re-sort client-side for column clicks.
  const { data, isLoading, error } = useOppActuals(filters, { sort: "revenue_desc", limit: 200 })
  const rawRows: OppActualsRow[] = useMemo(() => data?.data ?? [], [data])
  const totals = data?.meta?.totals as OppActualsTotals | undefined

  const rows = useMemo(() => {
    const col = COLUMNS.find((c) => c.k === sortKey)
    if (!col) return rawRows
    const mult = sortDir === "asc" ? 1 : -1
    return [...rawRows].sort((a, b) => {
      const va = col.accessor(a, mode)
      const vb = col.accessor(b, mode)
      if (typeof va === "string" || typeof vb === "string") {
        return String(va).localeCompare(String(vb)) * mult
      }
      return ((va as number) - (vb as number)) * mult
    })
  }, [rawRows, sortKey, sortDir, mode])

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

  return (
    <section className="overflow-hidden rounded-lg border border-[#E5E7EB] bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-3 border-b border-[#E5E7EB] bg-[#F9FAFB] px-3 py-2">
        <span className="rounded-md bg-[#1B3A5C] px-2 py-0.5 text-xs font-semibold uppercase text-white">
          Actuals
        </span>
        <ModePills mode={mode} setMode={setMode} />
        <div className="ml-auto flex items-center gap-2 text-[10px] text-[#6B7280]">
          {isLoading && <Loader2 className="h-3 w-3 animate-spin" />}
          <span>Click any column header to sort</span>
        </div>
      </div>

      {error ? (
        <div className="px-3 py-4 text-sm text-[#DC2626]">Failed to load Actuals</div>
      ) : (
        <div className="max-h-[420px] overflow-auto">
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
                  <ModeCell mode={mode} kind="count"
                    production={totals.vol} budget={totals.vol_budget} variance={totals.vol_var} />
                  <ModeCell mode={mode} kind="usd"
                    production={totals.rev} budget={totals.rev_budget} variance={totals.rev_var} />
                  <ModeCell mode={mode} kind="usd"
                    production={totals.prof} budget={totals.prof_budget} variance={totals.prof_var} />
                  <ModeCell mode={mode} kind="pct"
                    production={totals.margin_pct} budget={totals.margin_budget_pct} variance={totals.margin_var_pct} />
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtPct(totals.otp_pct)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtPct(totals.otd_pct)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(totals.rev_x_l)}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{fmtUsd(totals.prof_x_l)}</td>
                  <td className="px-2 py-1.5" colSpan={4} />
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
                  <td className="px-2 py-1.5 font-semibold text-[#1B3A5C]">{r.customer_name}</td>
                  <ModeCell mode={mode} kind="count"
                    production={r.vol} budget={r.vol_budget} variance={r.vol_var} />
                  <ModeCell mode={mode} kind="usd"
                    production={r.rev} budget={r.rev_budget} variance={r.rev_var} />
                  <ModeCell mode={mode} kind="usd"
                    production={r.prof} budget={r.prof_budget} variance={r.prof_var} />
                  <ModeCell mode={mode} kind="pct"
                    production={r.margin_pct} budget={r.margin_budget_pct} variance={r.margin_var_pct} />
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
        </div>
      )}
    </section>
  )
}

function ModePills({ mode, setMode }: { mode: Mode; setMode: (m: Mode) => void }) {
  const opts: { k: Mode; label: string }[] = [
    { k: "all",        label: "All" },
    { k: "production", label: "Production" },
    { k: "budget",     label: "Budget" },
    { k: "variance",   label: "Variance per Cell" },
  ]
  return (
    <div className="flex rounded-lg border border-[#E5E7EB] bg-white text-xs">
      {opts.map((o) => (
        <button
          key={o.k}
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

function SortableTh({
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

function ModeCell({
  mode,
  kind,
  production,
  budget,
  variance,
}: {
  mode: Mode
  kind: "count" | "usd" | "pct"
  production: number
  budget: number
  variance: number
}) {
  const fmt = (v: number) =>
    kind === "count" ? fmtCount(v)
    : kind === "pct" ? `${v.toFixed(2)}%`
    : fmtUsd(v)
  const fmtSigned = (v: number) =>
    kind === "count" ? `${v >= 0 ? "+" : ""}${fmtCount(v)}`
    : kind === "pct" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`
    : fmtUsdSigned(v)

  if (mode === "all") {
    // Bruno R5 #9: Production (big) with Budget bottom-left + Variance bottom-right.
    // Bruno R5 #10: Production / Budget % shown beside the cell.
    const pct = budget !== 0 ? (production / budget) * 100 : null
    return (
      <td className="px-2 py-1.5 text-center tabular-nums">
        <div className="flex items-center justify-center gap-1.5">
          <div className="min-w-[64px]">
            <div className={`font-semibold text-[#1B3A5C] ${kind !== "count" && production < 0 ? "!text-[#DC2626]" : ""}`}>
              {fmt(production)}
            </div>
            <div className="flex items-center justify-between gap-2 text-[10px]">
              <span className="text-[#6B7280]">{fmt(budget)}</span>
              <span className={variance < 0 ? "font-medium text-[#DC2626]" : "font-medium text-[#16A34A]"}>
                {fmtSigned(variance)}
              </span>
            </div>
          </div>
          {pct !== null && (
            <span className="text-[10px] font-semibold text-[#2563EB]">{Math.round(pct)}%</span>
          )}
        </div>
      </td>
    )
  }
  if (mode === "production") {
    return (
      <td className="px-2 py-1.5 text-center tabular-nums">
        <span className={`font-semibold text-[#1B3A5C] ${kind !== "count" && production < 0 ? "!text-[#DC2626]" : ""}`}>
          {fmt(production)}
        </span>
      </td>
    )
  }
  if (mode === "budget") {
    return (
      <td className="px-2 py-1.5 text-center tabular-nums">
        <span className="font-semibold text-[#1B3A5C]">{fmt(budget)}</span>
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
